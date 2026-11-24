"""Testes do importar_url (importar.py): servidor falso em 127.0.0.1, sem internet. Uso: python -I testar_importar.py"""
import io, socket, sys, tempfile, threading, time, unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PIL import Image
import config
import entrada, importar, midias
from erros import Erro


def png():
    b = io.BytesIO()
    Image.new("RGB", (30, 20), "red").save(b, "PNG")
    return b.getvalue()


class Falso(ThreadingHTTPServer):
    """Responde conforme `rotas`: {caminho: (codigo, {cabecalhos}, corpo)}. Conta os pedidos que chegaram."""
    daemon_threads = True

    def __init__(self):
        self.rotas, self.pedidos = {}, 0
        falso = self

        class Atende(BaseHTTPRequestHandler):
            def do_GET(self):
                falso.pedidos += 1
                codigo, cabecalhos, corpo = falso.rotas.get(self.path, (404, {}, b"nada"))
                try:
                    self.send_response(codigo)
                    for k, v in cabecalhos.items():
                        self.send_header(k, v)
                    self.end_headers()
                    self.wfile.write(corpo)
                except OSError:  # o cliente parou de ler (limite): esperado
                    pass

            def log_message(self, *a):
                pass

        super().__init__(("127.0.0.1", 0), Atende)


def aceita_tudo(ip):
    return True


class Importar(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.raiz = Path(d.name)
        for nome in ("entrada", "envios"):
            (self.raiz / nome).mkdir()
        for alvo, nome, valor in ((config, "ENTRADA", self.raiz / "entrada"), (config, "ENVIOS", self.raiz / "envios"),
                                  (midias, "ARQUIVO", self.raiz / "midias.json")):
            antigo = getattr(alvo, nome)
            setattr(alvo, nome, valor)
            self.addCleanup(setattr, alvo, nome, antigo)
        self.falso = Falso()
        self.porta = self.falso.server_address[1]
        threading.Thread(target=self.falso.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
        self.addCleanup(self.falso.server_close)
        self.addCleanup(self.falso.shutdown)
        self.url = f"http://127.0.0.1:{self.porta}"

    def entrada(self):
        # Os arquivos da entrada: na raiz e em input/estudio/envios, onde o envio novo vai
        return sorted(p.name for d in (config.ENTRADA, entrada.pasta_envios()) if d.is_dir() for p in d.iterdir() if p.is_file())

    def libera(self):
        """O 127.0.0.1 do servidor falso passa pela conferencia (so nos testes que precisam conectar)."""
        p = mock.patch.object(importar, "_ip_permitido", aceita_tudo)
        p.start()
        self.addCleanup(p.stop)

    def test_ip_permitido_so_publico(self):
        for ip in ("127.0.0.1", "10.0.0.5", "192.168.1.10", "169.254.1.1", "100.64.0.9", "224.0.0.1", "0.0.0.0", "::1",
                   "::ffff:127.0.0.1", "fe80::1", "fc00::1", "fec0::1", "::7f00:1", "64:ff9b::a00:1", "64:ff9b::7f00:1"):
            self.assertFalse(importar._ip_permitido(ip), ip)
        self.assertTrue(importar._ip_permitido("93.184.216.34"))
        self.assertTrue(importar._ip_permitido("64:ff9b::5db8:d822"))  # NAT64 com 93.184.216.34 embutido: redes so IPv6 dependem dela

    def test_enderecos_malformados_viram_erro_claro(self):
        for url in ("http://[::1/a.png", "http://[abc/a.png"):
            with self.assertRaisesRegex(Erro, "Endereço inválido"):
                importar.baixar(url, "foto")

    def test_redirecionamento_malformado_vira_erro_claro(self):
        self.libera()
        self.falso.rotas["/x"] = (302, {"Location": "http://[::1/a.png"}, b"")
        with self.assertRaisesRegex(Erro, "inválido"):
            importar.baixar(f"{self.url}/x", "foto")
        self.assertEqual(self.entrada(), [])

    def test_image_jpg_tem_extensao(self):
        self.libera()
        self.falso.rotas["/baixar"] = (200, {"Content-Type": "image/jpg"}, png())
        self.assertRegex(importar.baixar(f"{self.url}/baixar", "foto")["arquivo"], r"^importado_[0-9a-f]{4}\.jpg$")

    def test_https_manda_o_host_sem_a_porta_padrao(self):
        """A conexao https usa HTTPConnection em cima do socket ja cifrado; o Host nao pode sair "nome:443" (quebra link assinado)."""
        enviado = []

        class SocketFalso:
            def settimeout(self, t): pass
            def sendall(self, dados): enviado.append(bytes(dados))
            def close(self): pass
            def shutdown(self, como): pass
            def do_handshake(self): pass

        for esquema, porta, esperado in (("https", 443, b"Host: exemplo.test\r\n"), ("https", 8443, b"Host: exemplo.test:8443\r\n"),
                                         ("http", 80, b"Host: exemplo.test\r\n")):
            enviado.clear()
            with mock.patch.object(importar, "_enderecos", return_value=["93.184.216.34"]), \
                 mock.patch.object(importar.socket, "create_connection", return_value=SocketFalso()), \
                 mock.patch.object(importar.ssl, "create_default_context") as ctx:
                ctx.return_value.wrap_socket.side_effect = lambda sock, **k: sock
                conexao, caminho, sock, vigia = importar._conectar(f"{esquema}://exemplo.test:{porta}/a.png", time.monotonic() + 30)
            vigia.parar()
            conexao.putrequest("GET", caminho)
            conexao.endheaders()
            self.assertIn(esperado, b"".join(enviado), (esquema, porta))

    def test_https_soma_as_raizes_do_certifi(self):
        """O Windows desta maquina nao tem as raizes novas do Let's Encrypt (Root YE, 2025): Wikimedia e Civitai davam
        "certificate has expired" (teste com o Claude Code em 24/11). As raizes do certifi entram junto com as do sistema."""
        import certifi
        with mock.patch.object(importar.ssl, "create_default_context") as ctx:
            contexto = importar._contexto_ssl()
        self.assertIs(contexto, ctx.return_value)
        ctx.return_value.load_verify_locations.assert_called_once_with(certifi.where())
        # Sem o certifi (ou com o arquivo dele quebrado) fica o contexto do sistema, sem erro
        with mock.patch.object(importar.ssl, "create_default_context") as ctx, mock.patch.dict(sys.modules, {"certifi": None}):
            self.assertIs(importar._contexto_ssl(), ctx.return_value)
        with mock.patch.object(importar.ssl, "create_default_context") as ctx:
            ctx.return_value.load_verify_locations.side_effect = OSError("sem arquivo")
            self.assertIs(importar._contexto_ssl(), ctx.return_value)

    def test_recusa_rede_interna_sem_conectar(self):
        with self.assertRaisesRegex(Erro, "rede interna"):
            importar.baixar(f"{self.url}/foto.png", "foto")
        self.assertEqual(self.falso.pedidos, 0)
        self.assertEqual(self.entrada(), [])

    def test_recusa_se_qualquer_endereco_do_nome_for_interno(self):
        resposta = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80)), (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 80))]
        with mock.patch.object(importar.socket, "getaddrinfo", return_value=resposta), mock.patch.object(importar.socket, "create_connection") as con:
            with self.assertRaisesRegex(Erro, "rede interna"):
                importar.baixar("http://exemplo.test/foto.png", "foto")
        con.assert_not_called()

    def test_conecta_no_ip_conferido_e_nao_no_nome(self):
        """O nome so e resolvido uma vez: a conexao vai para o IP devolvido nessa resolucao."""
        self.libera()
        self.falso.rotas["/a.png"] = (200, {"Content-Type": "image/png"}, png())
        resposta = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", self.porta))]
        with mock.patch.object(importar.socket, "getaddrinfo", return_value=resposta) as g:
            r = importar.baixar(f"http://nome-que-nao-existe.test:{self.porta}/a.png", "foto")
        self.assertEqual([c.args[0] for c in g.call_args_list].count("nome-que-nao-existe.test"), 1)  # o nome nao e resolvido de novo ao conectar
        self.assertEqual(r["arquivo"], "a.png")

    def test_baixa_foto_e_registra(self):
        self.libera()
        self.falso.rotas["/fotos/ana.png"] = (200, {"Content-Type": "image/png", "Content-Length": str(len(png()))}, png())
        r = importar.baixar(f"{self.url}/fotos/ana.png", "foto")
        self.assertEqual((r["arquivo"], r["largura"], r["altura"]), ("ana.png", 30, 20))
        self.assertEqual(self.entrada(), ["ana.png"])
        self.assertEqual((entrada.pasta_envios() / "ana.png").read_bytes(), png())
        reg = midias.listar("foto")
        self.assertEqual((reg[0]["nome"], reg[0]["origem"]), ("ana.png", "url"))

    def test_sem_nome_com_extensao_usa_importado_e_o_content_type(self):
        self.libera()
        self.falso.rotas["/baixar?id=7"] = (200, {"Content-Type": "image/png; charset=binary"}, png())
        r = importar.baixar(f"{self.url}/baixar?id=7", "foto")
        self.assertRegex(r["arquivo"], r"^importado_[0-9a-f]{4}\.png$")

    def test_segue_redirecionamento_para_destino_publico(self):
        self.libera()
        self.falso.rotas["/x"] = (302, {"Location": "/y.png"}, b"")
        self.falso.rotas["/y.png"] = (200, {"Content-Type": "image/png"}, png())
        self.assertEqual(importar.baixar(f"{self.url}/x", "foto")["arquivo"], "y.png")

    def test_redirecionamento_para_ip_interno_e_recusado(self):
        with mock.patch.object(importar, "_ip_permitido", lambda ip: ip == "127.0.0.1"):
            self.falso.rotas["/x.png"] = (302, {"Location": "http://10.0.0.1/segredo.png"}, b"")
            with self.assertRaisesRegex(Erro, "rede interna"):
                importar.baixar(f"{self.url}/x.png", "foto")
        self.assertEqual(self.falso.pedidos, 1)
        self.assertEqual(self.entrada(), [])

    def test_redirecionamento_para_localhost_pelo_nome_e_recusado(self):
        with mock.patch.object(importar, "_ip_permitido", lambda ip: ip == "127.0.0.1"):
            self.falso.rotas["/x.png"] = (301, {"Location": "http://[::1]/"}, b"")
            with self.assertRaisesRegex(Erro, "rede interna"):
                importar.baixar(f"{self.url}/x.png", "foto")

    def test_mais_de_tres_redirecionamentos(self):
        self.libera()
        for i in range(6):
            self.falso.rotas[f"/r{i}"] = (302, {"Location": f"/r{i + 1}"}, b"")
        with self.assertRaisesRegex(Erro, "redireciona mais de 3"):
            importar.baixar(f"{self.url}/r0", "foto")
        self.assertEqual(self.falso.pedidos, importar.MAX_REDIRECIONAMENTOS + 1)

    def test_exatamente_tres_redirecionamentos_passam(self):
        self.libera()
        for i in range(3):
            self.falso.rotas[f"/r{i}"] = (302, {"Location": f"/r{i + 1}"}, b"")
        self.falso.rotas["/r3"] = (200, {"Content-Type": "image/png"}, png())
        self.assertRegex(importar.baixar(f"{self.url}/r0", "foto")["arquivo"], r"^importado_.*\.png$")

    def test_para_no_limite_sem_content_length(self):
        self.libera()
        self.falso.rotas["/g.png"] = (200, {"Content-Type": "image/png"}, b"\x89PNG" + b"0" * 5000)  # sem Content-Length: fecha a conexao
        with mock.patch.dict(importar.LIMITE, {"foto": 1000}):
            with self.assertRaisesRegex(Erro, "limite"):
                importar.baixar(f"{self.url}/g.png", "foto")
        self.assertEqual(self.entrada(), [])
        self.assertEqual(midias.listar(), [])

    def test_content_length_acima_do_limite_recusa_antes_de_ler(self):
        self.libera()
        self.falso.rotas["/g.png"] = (200, {"Content-Length": "5000"}, b"0" * 5000)
        with mock.patch.dict(importar.LIMITE, {"foto": 1000}):
            with self.assertRaisesRegex(Erro, "limite"):
                importar.baixar(f"{self.url}/g.png", "foto")
        self.assertEqual(self.entrada(), [])

    def test_content_length_menor_que_o_corpo_le_so_o_declarado_e_recusa_o_que_nao_e_imagem(self):
        self.libera()
        self.falso.rotas["/g.png"] = (200, {"Content-Length": "10"}, b"0" * 5000)
        with mock.patch.dict(importar.LIMITE, {"foto": 1000}):
            with self.assertRaises(Erro):
                importar.baixar(f"{self.url}/g.png", "foto")
        self.assertEqual(self.entrada(), [])

    def test_download_cortado_no_meio_nao_deixa_arquivo(self):
        self.libera()
        self.falso.rotas["/c.png"] = (200, {"Content-Length": "5000"}, png())  # promete 5000, entrega menos
        with self.assertRaisesRegex(Erro, "interrompido"):
            importar.baixar(f"{self.url}/c.png", "foto")
        self.assertEqual(self.entrada(), [])

    def test_passou_do_tempo(self):
        self.libera()
        self.falso.rotas["/t.png"] = (200, {}, png())
        with mock.patch.dict(importar.TEMPO, {"foto": -1}):
            with self.assertRaisesRegex(Erro, "cancelado"):
                importar.baixar(f"{self.url}/t.png", "foto")
        self.assertEqual(self.entrada(), [])

    def pinga(self, nos_cabecalhos):
        """Servidor que larga 1 byte a cada 0,1 s (nos cabecalhos ou no corpo): o timeout do socket nunca estoura, so o prazo total pega."""
        cabecalho, corpo = b"HTTP/1.0 200 OK\r\nContent-Type: image/png\r\n\r\n", png()

        class Lento(BaseHTTPRequestHandler):
            def do_GET(h):
                try:
                    if not nos_cabecalhos:
                        h.wfile.write(cabecalho)
                        h.wfile.flush()
                    for b in (cabecalho + corpo if nos_cabecalhos else corpo):
                        h.wfile.write(bytes([b]))
                        h.wfile.flush()
                        time.sleep(0.1)
                except OSError:
                    pass

            def log_message(h, *a):
                pass

        lento = ThreadingHTTPServer(("127.0.0.1", 0), Lento)
        lento.daemon_threads = True
        threading.Thread(target=lento.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
        self.addCleanup(lento.server_close)
        self.addCleanup(lento.shutdown)
        return f"http://127.0.0.1:{lento.server_address[1]}/lento.png"

    def confere_prazo(self, url):
        inicio = time.monotonic()
        with mock.patch.dict(importar.TEMPO, {"foto": 0.7}):
            with self.assertRaisesRegex(Erro, "cancelado"):
                importar.baixar(url, "foto")
        self.assertLess(time.monotonic() - inicio, 3)  # sem o vigia, o servidor seguraria a leitura por uns 9 s
        self.assertEqual(self.entrada(), [])
        self.assertEqual(midias.listar(), [])
        time.sleep(0.05)
        self.assertEqual([t for t in threading.enumerate() if isinstance(t, threading.Timer)], [])  # o vigia foi cancelado

    def test_prazo_vale_contra_corpo_pingado(self):
        self.libera()
        self.confere_prazo(self.pinga(nos_cabecalhos=False))

    def test_prazo_vale_contra_cabecalhos_pingados(self):
        self.libera()
        self.confere_prazo(self.pinga(nos_cabecalhos=True))

    def test_prazo_vale_no_https_onde_o_wrap_socket_troca_o_socket(self):
        """Sem TLS de verdade: um contexto falso devolve OUTRO socket feito do mesmo descritor, como o SSLSocket (o antigo fica inutil)."""
        self.libera()
        chamadas = []

        class SocketTls(socket.socket):
            def do_handshake(self):
                pass

        class ContextoFalso:
            def load_verify_locations(self, *a, **k): pass  # as raizes do certifi (importar._contexto_ssl)

            def wrap_socket(self, sock, server_hostname=None, do_handshake_on_connect=True):
                chamadas.append(server_hostname)
                tempo = sock.gettimeout()  # o SSLSocket de verdade tambem herda o timeout
                novo = SocketTls(fileno=sock.detach())
                novo.settimeout(tempo)
                return novo

        url = self.pinga(nos_cabecalhos=False).replace("http://", "https://")
        host = "nome-publico.test"
        resposta = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", int(url.split(":")[2].split("/")[0])))]
        with mock.patch.object(importar.ssl, "create_default_context", return_value=ContextoFalso()),                 mock.patch.object(importar.socket, "getaddrinfo", return_value=resposta):
            self.confere_prazo(url.replace("127.0.0.1", host))
        self.assertEqual(chamadas, [host])  # o certificado e conferido contra o nome original, nao contra o IP

    def test_prazo_e_um_so_para_os_redirecionamentos(self):
        self.libera()
        self.falso.rotas["/r"] = (302, {"Location": self.pinga(nos_cabecalhos=True)}, b"")
        self.confere_prazo(f"{self.url}/r")

    def test_conteudo_que_nao_e_midia(self):
        self.libera()
        self.falso.rotas["/p.png"] = (200, {"Content-Type": "text/html"}, b"<html>oi</html>")
        with self.assertRaisesRegex(Erro, "imagem"):
            importar.baixar(f"{self.url}/p.png", "foto")
        self.assertEqual(self.entrada(), [])
        self.assertEqual(midias.listar(), [])

    def test_resposta_de_erro_do_site(self):
        self.libera()
        with self.assertRaisesRegex(Erro, "404"):
            importar.baixar(f"{self.url}/nao-existe.png", "foto")

    def test_so_http_e_https(self):
        for url in ("file:///etc/passwd", "ftp://exemplo.test/a.png", "gopher://exemplo.test/", "//exemplo.test/a.png", "exemplo.test/a.png"):
            with self.assertRaisesRegex(Erro, "http"):
                importar.baixar(url, "foto")

    def test_recusa_usuario_e_senha_no_endereco(self):
        self.libera()
        with self.assertRaisesRegex(Erro, "usuário e senha"):
            importar.baixar(f"http://usuario:senha@127.0.0.1:{self.porta}/a.png", "foto")
        self.assertEqual(self.falso.pedidos, 0)

    def test_tipo_e_url_ruins(self):
        with self.assertRaises(Erro):
            importar.baixar(f"{self.url}/a.png", "documento")
        for url in ("", "   ", None, 5):
            with self.assertRaises(Erro):
                importar.baixar(url, "foto")


if __name__ == "__main__":
    unittest.main()
