"""Testes das chaves de acesso remoto (acesso.py) e da leitura de remoto do local.json (config.py).
Usam chaves falsas; nada vem do local.json real. Uso: python -I testar_acesso.py"""
import contextlib, io, json, socket, sys, tempfile, threading, unittest, urllib.error, urllib.request
from pathlib import Path
from unittest import mock

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
import acesso, entrada, links, midias, servidor


class Acesso(unittest.TestCase):
    def com_remoto(self, remoto):
        antes = config.REMOTO
        config.REMOTO = remoto
        self.addCleanup(setattr, config, "REMOTO", antes)

    def test_nivel_por_chave(self):
        self.com_remoto({"escutar": "100.64.0.5", "chaves": {"operador": "o" * 32, "completo": "c" * 32}})
        self.assertEqual(acesso.nivel("o" * 32), "operador")
        self.assertEqual(acesso.nivel("c" * 32), "completo")
        self.assertIsNone(acesso.nivel("x" * 32))
        self.assertIsNone(acesso.nivel(None))
        self.assertIsNone(acesso.nivel(""))

    def test_chave_do_cabecalho_e_do_cookie(self):
        self.assertEqual(acesso.chave_do_pedido({"Authorization": "Bearer abc"}), "abc")
        self.assertEqual(acesso.chave_do_pedido({"Cookie": "a=1; estudio_chave=xyz"}), "xyz")
        self.assertIsNone(acesso.chave_do_pedido({}))

    def test_sem_chaves_nao_fica_pronto(self):
        self.com_remoto({"escutar": "100.64.0.5", "chaves": {}})
        self.assertFalse(acesso.remoto_pronto())

    def test_com_tudo_fica_pronto(self):
        self.com_remoto({"escutar": "100.64.0.5", "chaves": {"operador": "o" * 32, "completo": "c" * 32}})
        self.assertTrue(acesso.remoto_pronto())

    def test_sem_chaves_configuradas_ninguem_entra(self):
        self.com_remoto({"escutar": None, "chaves": {}})
        self.assertIsNone(acesso.nivel("qualquer"))

    def test_config_descarta_valores_ruins(self):
        r = config._remoto({"remoto": {"escutar": "127.0.0.1", "chaves": {"operador": "curta", "completo": "c" * 32}}})
        self.assertIsNone(r["escutar"])
        self.assertNotIn("operador", r["chaves"])
        for ruim in ("0.0.0.0", "224.0.0.1"):
            self.assertIsNone(config._remoto({"remoto": {"escutar": ruim}})["escutar"], ruim)

    def test_config_exige_chave_no_formato_do_gerar(self):
        boa = "a" * 20 + "B9_-"
        for ruim in ("c" * 23, "c" * 31 + " ", "c" * 31 + "!", "ç" * 32, "c" * 16 + "/" + "c" * 16):
            r = config._remoto({"remoto": {"chaves": {"operador": ruim, "completo": boa}}})
            self.assertEqual(r["chaves"], {"completo": boa}, ruim)

    def test_config_recusa_chaves_iguais(self):
        import contextlib, io
        saida = io.StringIO()
        with contextlib.redirect_stdout(saida):
            r = config._remoto({"remoto": {"escutar": "100.64.0.5", "chaves": {"operador": "c" * 32, "completo": "c" * 32}}})
        self.assertEqual(r["chaves"], {})
        self.assertIn("iguais", saida.getvalue())

    def test_config_aceita_ip_valido(self):
        r = config._remoto({"remoto": {"escutar": "100.64.0.5", "chaves": {"completo": "c" * 32}}})
        self.assertEqual(r["escutar"], "100.64.0.5")
        self.assertEqual(r["chaves"], {"completo": "c" * 32})
        self.assertIsNone(config._remoto({"remoto": {"escutar": "nao-e-ip"}})["escutar"])
        self.assertEqual(config._remoto({}), {"escutar": None, "chaves": {}})


IP_REMOTO = "127.0.0.2"  # no Windows todo 127.x.x.x e desta maquina


def porta_livre():
    """Uma porta com ela e as duas seguintes livres nos dois enderecos (127.0.0.1 e 127.0.0.2): outra copia do projeto pode estar
    rodando a suite ao mesmo tempo, e uma porta fixa colidiria."""
    for _ in range(100):
        with socket.socket() as t:
            t.bind(("127.0.0.1", 0))
            porta = t.getsockname()[1]
        try:
            for ip in ("127.0.0.1", IP_REMOTO):
                for passo in range(3):
                    with socket.socket() as t:
                        t.bind((ip, porta + passo))
        except OSError:
            continue
        return porta
    raise RuntimeError("Não achei uma porta livre para os testes.")


CHAVES = {"operador": "o" * 32, "completo": "c" * 32}


class Servidores(unittest.TestCase):
    """Um servidor local (127.0.0.1) e um remoto (127.0.0.2) na mesma porta de teste."""

    def setUp(self):
        antes, pausa = config.REMOTO, acesso.PAUSA_ERRO
        config.REMOTO = {"escutar": IP_REMOTO, "chaves": dict(CHAVES)}
        acesso.PAUSA_ERRO = 0
        self.addCleanup(setattr, config, "REMOTO", antes)
        self.addCleanup(setattr, acesso, "PAUSA_ERRO", pausa)
        # Os envios pelo link gravam so em pastas de teste (nunca na entrada do ComfyUI nem no midias.json de verdade)
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.raiz = Path(d.name)
        for nome in ("entrada", "envios"):
            (self.raiz / nome).mkdir()
        for alvo, nome, valor in ((config, "ENTRADA", self.raiz / "entrada"), (config, "ENVIOS", self.raiz / "envios"), (midias, "ARQUIVO", self.raiz / "midias.json"),
                                  (links, "ARQUIVO", self.raiz / "links.json")):
            antigo = getattr(alvo, nome)
            setattr(alvo, nome, valor)
            self.addCleanup(setattr, alvo, nome, antigo)
        self.porta = porta_livre()
        for s in (servidor.criar(self.porta), servidor.criar(self.porta, endereco=IP_REMOTO)):
            fio = threading.Thread(target=s.serve_forever, args=(0.05,), daemon=True)
            fio.start()
            self.addCleanup(fio.join, 5)
            self.addCleanup(s.server_close)
            self.addCleanup(s.shutdown)

    def pedir(self, ip, caminho, chave=None, metodo="GET", corpo=None):
        cab = {"Host": f"{ip}:{self.porta}"}
        if chave:
            cab["Authorization"] = f"Bearer {chave}"
        if corpo is not None:
            cab["Content-Type"] = "application/json"
        p = urllib.request.Request(f"http://{ip}:{self.porta}{caminho}", data=corpo, headers=cab, method=metodo)
        try:
            with urllib.request.urlopen(p, timeout=30) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_servidor_remoto_sabe_que_e_remoto(self):
        s = servidor.criar(self.porta + 1, endereco=IP_REMOTO)
        self.addCleanup(s.server_close)
        self.assertTrue(s.remoto)
        l = servidor.criar(self.porta + 1)
        self.addCleanup(l.server_close)
        self.assertFalse(l.remoto)

    def pedir_link(self, caminho, cabecalhos=None):
        """GET sem chave ao servidor remoto; devolve (codigo, cabecalhos, corpo)."""
        cab = {"Host": f"{IP_REMOTO}:{self.porta}", **(cabecalhos or {})}
        p = urllib.request.Request(f"http://{IP_REMOTO}:{self.porta}{caminho}", headers=cab)
        try:
            with urllib.request.urlopen(p, timeout=30) as r:
                return r.status, r.headers, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers, e.read()

    def link_de_baixar(self, conteudo=b"0123456789abcdef" * 4, arquivo="final.mp4", nome="ana_video.mp4"):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        arq = Path(d.name) / arquivo
        arq.write_bytes(conteudo)
        links._itens.clear()
        self.addCleanup(links._itens.clear)
        return links.criar_baixar(arq, nome), conteudo

    def test_link_de_baixar_manda_o_tipo_pelo_sufixo(self):
        for arquivo, tipo in (("imagem_1.png", "image/png"), ("foto.jpg", "image/jpeg"), ("foto.JPEG", "image/jpeg"),
                              ("final.mp4", "video/mp4"), ("dados.bin", "application/octet-stream")):
            c, conteudo = self.link_de_baixar(arquivo=arquivo, nome=f"projeto_1{Path(arquivo).suffix}")
            codigo, cab, corpo = self.pedir_link(f"/m/{c}")
            self.assertEqual((codigo, cab["Content-Type"], corpo), (200, tipo, conteudo), arquivo)
            self.assertEqual(cab["Content-Disposition"], f'attachment; filename="projeto_1{Path(arquivo).suffix}"', arquivo)
        # O Range segue valendo para a imagem
        c, conteudo = self.link_de_baixar(arquivo="imagem_1.png", nome="p_1.png")
        codigo, cab, corpo = self.pedir_link(f"/m/{c}", {"Range": "bytes=2-5"})
        self.assertEqual((codigo, cab["Content-Type"], corpo), (206, "image/png", conteudo[2:6]))

    def test_link_de_baixar_vale_sem_chave(self):
        c, conteudo = self.link_de_baixar()
        codigo, cab, corpo = self.pedir_link(f"/m/{c}")
        self.assertEqual((codigo, corpo), (200, conteudo))
        self.assertEqual(cab["Content-Disposition"], 'attachment; filename="ana_video.mp4"')
        self.assertEqual(cab["Content-Type"], "video/mp4")
        self.assertEqual(self.pedir_link(f"/m/{c}?x=1")[0], 200)  # a query nao conta
        codigo, cab, corpo = self.pedir_link(f"/m/{c}", {"Range": "bytes=0-9"})
        self.assertEqual((codigo, corpo), (206, conteudo[:10]))
        self.assertEqual(cab["Content-Range"], f"bytes 0-9/{len(conteudo)}")

    def test_link_invalido_vencido_ou_com_mais_pedacos_da_404(self):
        c, _ = self.link_de_baixar()
        vencido = links.criar_baixar(links._itens[c]["arquivo"], "x.mp4")
        links._itens[vencido]["criado"] -= links.VALIDADE + 1
        for caminho in ("/m/nao-existe", f"/m/{c}/x", f"/m/{c}/../x.png", f"/m/{c}%2Fx", f"/m/{c}/", "/m/", "/m//" + c, f"/m/{vencido}"):
            codigo, _, corpo = self.pedir_link(caminho)
            self.assertEqual(codigo, 404, caminho)
            self.assertEqual(json.loads(corpo), {"erro": "Link inválido ou vencido. Peça outro."}, caminho)

    def test_link_de_envio_nao_baixa_nada(self):
        c = links.criar_enviar("foto")
        self.addCleanup(links._itens.clear)
        codigo, cab, corpo = self.pedir_link(f"/m/{c}")
        self.assertEqual(codigo, 200)
        self.assertNotIn("Content-Disposition", cab)
        self.assertIn("text/html", cab["Content-Type"])

    # --- envio pelo link (PUT /m/<codigo>/<nome>) ---

    def png(self, cor="red"):
        b = io.BytesIO()
        Image.new("RGB", (30, 20), cor).save(b, "PNG")
        return b.getvalue()

    def link_de_enviar(self, tipo="foto"):
        links._itens.clear()
        self.addCleanup(links._itens.clear)
        return links.criar_enviar(tipo)

    def enviar(self, caminho, dados, cabecalhos=None, ip=IP_REMOTO):
        """PUT sem chave; devolve (codigo, corpo em JSON)."""
        p = urllib.request.Request(f"http://{ip}:{self.porta}{caminho}", data=dados, method="PUT", headers={"Host": f"{ip}:{self.porta}", **(cabecalhos or {})})
        try:
            with urllib.request.urlopen(p, timeout=30) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def put_cru(self, caminho, cabecalhos="", corpo=b"", fechar_antes=False):
        """PUT escrito a mao (urllib sempre poe o Content-Length); devolve (codigo, corpo em JSON)."""
        with socket.create_connection((IP_REMOTO, self.porta), timeout=30) as c:
            c.sendall(f"PUT {caminho} HTTP/1.1\r\nHost: {IP_REMOTO}:{self.porta}\r\n{cabecalhos}Connection: close\r\n\r\n".encode() + corpo)
            if fechar_antes:
                c.shutdown(socket.SHUT_WR)  # acabou de enviar, mas ainda le a resposta
            resposta = b""
            while bloco := c.recv(65536):
                resposta += bloco
        cabecalho, _, resto = resposta.partition(b"\r\n\r\n")
        return int(cabecalho.split()[1]), json.loads(resto)

    def test_envio_pelo_link_grava_a_foto_e_gasta_o_link(self):
        c = self.link_de_enviar()
        dados = self.png()
        codigo, corpo = self.enviar(f"/m/{c}/foto.png", dados)
        self.assertEqual(codigo, 200)
        self.assertEqual(corpo, {"midia": "foto.png", "tipo": "foto", "largura": 30, "altura": 20})
        self.assertEqual(entrada.caminho("foto.png").read_bytes(), dados)
        self.assertEqual([m["origem"] for m in midias.listar()], ["link"])
        codigo, corpo = self.enviar(f"/m/{c}/outra.png", dados)
        self.assertEqual((codigo, corpo), (404, {"erro": "Link inválido ou vencido. Peça outro."}))
        self.assertFalse((config.ENTRADA / "outra.png").exists())

    def test_envio_que_nao_e_imagem_da_400_e_o_link_continua(self):
        c = self.link_de_enviar()
        codigo, corpo = self.enviar(f"/m/{c}/foto.png", b"isto nao e uma imagem")
        self.assertEqual(codigo, 400)
        self.assertIn("imagem", corpo["erro"])
        self.assertEqual([p for p in config.ENTRADA.rglob("*") if p.is_file()], [])
        self.assertEqual(self.enviar(f"/m/{c}/foto.png", self.png())[0], 200)

    def test_tipo_errado_para_o_link_da_400(self):
        c = self.link_de_enviar("foto")
        codigo, corpo = self.enviar(f"/m/{c}/voz.mp3", b"x")
        self.assertEqual(codigo, 400)
        self.assertIn("foto", corpo["erro"])
        self.assertEqual([p for p in config.ENTRADA.rglob("*") if p.is_file()], [])
        self.assertIsNotNone(links.ler(c))

    def test_envio_sem_tamanho_da_411(self):
        c = self.link_de_enviar()
        codigo, corpo = self.put_cru(f"/m/{c}/foto.png")
        self.assertEqual((codigo, corpo), (411, {"erro": "Informe o tamanho do arquivo (Content-Length)."}))
        # curl lendo da entrada padrao manda em pedacos, sem tamanho
        codigo, _ = self.put_cru(f"/m/{c}/foto.png", "Transfer-Encoding: chunked\r\n", b"0\r\n\r\n")
        self.assertEqual(codigo, 411)
        self.assertIsNotNone(links.ler(c))

    def test_tamanho_invalido_da_400(self):
        c = self.link_de_enviar()
        for tamanho in ("-1", "abc"):
            self.assertEqual(self.put_cru(f"/m/{c}/foto.png", f"Content-Length: {tamanho}\r\n")[0], 400, tamanho)

    def test_envio_acima_do_limite_da_413_sem_ler(self):
        c = self.link_de_enviar()
        with mock.patch.dict(midias.LIMITES, {"foto": 10}):
            codigo, corpo = self.enviar(f"/m/{c}/foto.png", self.png())
        self.assertEqual(codigo, 413)
        self.assertIn("limite", corpo["erro"])
        self.assertEqual([p for p in config.ENTRADA.rglob("*") if p.is_file()], [])
        self.assertIsNotNone(links.ler(c))

    def test_envio_cortado_no_meio_nao_deixa_arquivo_nem_gasta_o_link(self):
        c = self.link_de_enviar()
        dados = self.png()
        codigo, corpo = self.put_cru(f"/m/{c}/foto.png", f"Content-Length: {len(dados) + 500}\r\n", dados, fechar_antes=True)
        self.assertEqual(codigo, 400)
        self.assertIn("interrompido", corpo["erro"])
        self.assertEqual([p for p in config.ENTRADA.rglob("*") if p.is_file()], [])  # nem o .parte
        self.assertEqual(midias.listar(), [])
        self.assertEqual(self.enviar(f"/m/{c}/foto.png", dados)[0], 200)

    def test_envio_que_para_de_chegar_desiste_sem_deixar_sobra(self):
        c = self.link_de_enviar()
        dados = self.png()
        with mock.patch.object(servidor, "TEMPO_ENVIO", 0.5):
            # Manda uma parte e fica quieto com a conexao aberta (rede que sumiu sem avisar)
            with socket.create_connection((IP_REMOTO, self.porta), timeout=30) as s:
                s.sendall(f"PUT /m/{c}/foto.png HTTP/1.1\r\nHost: {IP_REMOTO}:{self.porta}\r\nContent-Length: {len(dados) + 500}\r\nConnection: close\r\n\r\n".encode() + dados)
                resposta = b""
                while bloco := s.recv(65536):
                    resposta += bloco
        cabecalho, _, resto = resposta.partition(b"\r\n\r\n")
        self.assertEqual(int(cabecalho.split()[1]), 408)
        self.assertIn("parou de chegar", json.loads(resto)["erro"])
        self.assertEqual([p for p in config.ENTRADA.rglob("*") if p.is_file()], [])  # nem o .parte
        self.assertNotIn(c, servidor._enviando)
        self.assertIsNotNone(links.ler(c))
        self.assertEqual(self.enviar(f"/m/{c}/foto.png", dados)[0], 200)

    def test_nome_fora_do_padrao_nunca_sai_da_pasta(self):
        c = self.link_de_enviar()
        # Um pedaco a mais no caminho nao e um nome: 404, sem tocar no link
        for caminho in (f"/m/{c}/../x.png", f"/m/{c}/a/b.png", f"/m/{c}/", f"/m/{c}", "/m/", f"/m/{c}/x.png/"):
            codigo, corpo = self.enviar(caminho, self.png())
            self.assertEqual((codigo, corpo), (404, {"erro": "Link inválido ou vencido. Peça outro."}), caminho)
        self.assertIsNotNone(links.ler(c))
        # %2F fica dentro do pedaco do nome; depois de decodificado, so o ultimo pedaco vale
        codigo, corpo = self.enviar(f"/m/{c}/..%2Fx.png", self.png())
        self.assertEqual((codigo, corpo["midia"]), (200, "x.png"))
        self.assertEqual([p.relative_to(config.ENTRADA).as_posix() for p in config.ENTRADA.rglob("*") if p.is_file()], ["estudio/envios/x.png"])
        self.assertFalse((self.raiz / "x.png").exists())

    def test_erro_inesperado_ao_servir_o_link_vira_500_com_json(self):
        with mock.patch.object(servidor.Pedido, "servir_link", side_effect=RuntimeError("quebrou")), contextlib.redirect_stderr(io.StringIO()):
            codigo, _, corpo = self.pedir_link("/m/abcdef")
        self.assertEqual(codigo, 500)
        self.assertIn("Falha inesperada", json.loads(corpo)["erro"])

    def test_envio_de_outra_origem_403(self):
        c = self.link_de_enviar()
        codigo, _ = self.enviar(f"/m/{c}/foto.png", self.png(), {"Origin": "http://outro.test"})
        self.assertEqual(codigo, 403)
        self.assertEqual([p for p in config.ENTRADA.rglob("*") if p.is_file()], [])
        self.assertIsNotNone(links.ler(c))

    def test_so_o_link_de_enviar_recebe_put(self):
        baixar, _ = self.link_de_baixar()
        for caminho in ("/api/estado", f"/m/{baixar}/x.png", "/m/nao-existe/x.png", "/entrar", "/mcp"):
            codigo, corpo = self.enviar(caminho, self.png())
            self.assertEqual((codigo, corpo), (404, {"erro": "Link inválido ou vencido. Peça outro."}), caminho)
        self.assertFalse((config.ENTRADA / "x.png").exists())
        self.assertIsNotNone(links.ler(baixar))
        vencido = links.criar_enviar("foto")
        links._itens[vencido]["criado"] -= links.VALIDADE + 1
        self.assertEqual(self.enviar(f"/m/{vencido}/x.png", self.png())[0], 404)

    def test_dois_envios_ao_mesmo_tempo_nao_gastam_o_link_duas_vezes(self):
        c = self.link_de_enviar()
        servidor._enviando.add(c)  # como se outro envio ainda estivesse chegando
        self.addCleanup(servidor._enviando.discard, c)
        codigo, corpo = self.enviar(f"/m/{c}/foto.png", self.png())
        self.assertEqual(codigo, 409)
        self.assertEqual([p for p in config.ENTRADA.rglob("*") if p.is_file()], [])
        self.assertIsNotNone(links.ler(c))

    def test_pagina_de_envio_tem_o_campo_do_arquivo(self):
        for tipo, aceita in (("foto", ".png"), ("audio", ".mp3"), ("video", ".mp4")):
            c = self.link_de_enviar(tipo)
            codigo, cab, corpo = self.pedir_link(f"/m/{c}")
            html = corpo.decode("utf-8")
            self.assertEqual(codigo, 200, tipo)
            self.assertIn("text/html", cab["Content-Type"])
            self.assertIn('type="file"', html)
            self.assertIn(aceita, html.split("accept=")[1].split(">")[0])
            self.assertNotIn("<!--TIPO", html)  # nenhuma marca ficou sem preencher
            self.assertNotIn("<!--ACCEPT", html)
            self.assertNotIn("<!--LIMITE", html)
            self.assertNotIn("http://", html)  # nada pedido a outros enderecos
        # Com mais pedacos no caminho ou depois de gasto, 404
        self.assertEqual(self.pedir_link(f"/m/{c}/x")[0], 404)
        self.enviar(f"/m/{c}/clipe.mp4", b"x")  # nao e um video: 400, o link continua
        self.assertEqual(self.pedir_link(f"/m/{c}")[0], 200)
        links.gastar(c)
        self.assertEqual(self.pedir_link(f"/m/{c}")[0], 404)

    def test_so_o_link_dispensa_a_chave(self):
        self.assertEqual(self.pedir_link("/api/estado")[0], 401)
        self.assertEqual(self.pedir_link("/video/ana/final.mp4")[0], 401)

    def test_remoto_sem_chave_401(self):
        codigo, corpo = self.pedir(IP_REMOTO, "/api/estado")
        self.assertEqual(codigo, 401)
        self.assertEqual(json.loads(corpo), {"erro": "Chave de acesso necessária."})
        self.assertEqual(self.pedir(IP_REMOTO, "/pagina/nova.css")[0], 401)

    def test_remoto_chave_errada_401(self):
        self.assertEqual(self.pedir(IP_REMOTO, "/api/estado", "x" * 32)[0], 401)

    def test_remoto_chave_completa_200(self):
        self.assertEqual(self.pedir(IP_REMOTO, "/api/estado", CHAVES["completo"])[0], 200)

    def test_remoto_chave_operador_nao_usa_a_api(self):
        self.assertEqual(self.pedir(IP_REMOTO, "/api/estado", CHAVES["operador"])[0], 403)
        self.assertEqual(self.pedir(IP_REMOTO, "/api/parar", CHAVES["operador"], "POST", b"{}")[0], 403)

    def test_remoto_recusa_host_de_fora(self):
        p = urllib.request.Request(f"http://{IP_REMOTO}:{self.porta}/api/estado", headers={"Host": "outro.site", "Authorization": f"Bearer {CHAVES['completo']}"})
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(p, timeout=30)
        self.assertEqual(e.exception.code, 403)

    def test_remoto_nao_desliga_o_estudio(self):
        codigo, corpo = self.pedir(IP_REMOTO, "/api/desligar", CHAVES["completo"], "POST", b"{}")
        self.assertEqual(codigo, 403)
        self.assertEqual(json.loads(corpo), {"erro": "Desligar o estúdio só pelo próprio computador."})
        self.assertEqual(self.pedir("127.0.0.1", "/api/estado")[0], 200)
        self.assertEqual(self.pedir(IP_REMOTO, "/api/estado", CHAVES["completo"])[0], 200)

    def test_remoto_nao_abre_janelas_no_pc(self):
        for rota in ("/api/abrir-pasta", "/api/abrir-instalador"):
            codigo, corpo = self.pedir(IP_REMOTO, rota, CHAVES["completo"], "POST", b"{}")
            self.assertEqual(codigo, 403, rota)
            self.assertEqual(json.loads(corpo), {"erro": "Isso só funciona no próprio computador."})

    def test_local_sem_chave_continua_200(self):
        self.assertEqual(self.pedir("127.0.0.1", "/api/estado")[0], 200)

    def test_mcp_exige_chave_ate_no_local(self):
        ping = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}).encode()
        self.assertEqual(self.pedir("127.0.0.1", "/mcp", None, "POST", ping)[0], 401)
        codigo, corpo = self.pedir("127.0.0.1", "/mcp", CHAVES["operador"], "POST", ping)
        self.assertEqual(codigo, 200)
        self.assertEqual(json.loads(corpo)["result"], {})
        self.assertEqual(self.pedir(IP_REMOTO, "/mcp", CHAVES["completo"], "POST", ping)[0], 200)

    def test_mcp_limite_do_corpo_depende_da_chave(self):
        grande = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {"lixo": "x" * 2_000_000}}).encode()
        codigo, corpo = self.pedir("127.0.0.1", "/mcp", CHAVES["completo"], "POST", grande)
        self.assertEqual(codigo, 200)
        self.assertEqual(json.loads(corpo)["result"], {})
        self.assertEqual(self.pedir("127.0.0.1", "/mcp", CHAVES["operador"], "POST", grande)[0], 413)

    def test_mcp_notificacao_202_e_get_405(self):
        n = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode()
        self.assertEqual(self.pedir("127.0.0.1", "/mcp", CHAVES["operador"], "POST", n)[0], 202)
        self.assertEqual(self.pedir("127.0.0.1", "/mcp", CHAVES["operador"])[0], 405)

    def pedir_cru(self, ip, caminho, metodo="GET", corpo=None, cabecalhos=None):
        """Sem seguir redirecionamentos: devolve (codigo, cabecalhos, corpo)."""
        class SemRedirecionar(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        cab = {"Host": f"{ip}:{self.porta}", **(cabecalhos or {})}
        p = urllib.request.Request(f"http://{ip}:{self.porta}{caminho}", data=corpo, headers=cab, method=metodo)
        try:
            with urllib.request.build_opener(SemRedirecionar).open(p, timeout=30) as r:
                return r.status, r.headers, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers, e.read()

    def entrar(self, chave, cabecalhos=None):
        return self.pedir_cru(IP_REMOTO, "/entrar", "POST", f"chave={chave}".encode(),
                              {"Content-Type": "application/x-www-form-urlencoded", **(cabecalhos or {})})

    def test_remoto_raiz_sem_cookie_vai_para_a_entrada(self):
        codigo, cab, _ = self.pedir_cru(IP_REMOTO, "/")
        self.assertEqual(codigo, 303)
        self.assertEqual(cab["Location"], "/entrar")

    def test_remoto_tela_de_entrada_sem_chave(self):
        codigo, cab, corpo = self.pedir_cru(IP_REMOTO, "/entrar")
        self.assertEqual(codigo, 200)
        self.assertIn("text/html", cab["Content-Type"])
        self.assertIn("name=\"chave\"".encode(), corpo)

    def test_entrar_com_chave_completa_poe_o_cookie(self):
        codigo, cab, _ = self.entrar(CHAVES["completo"])
        self.assertEqual(codigo, 303)
        self.assertEqual(cab["Location"], "/")
        cookie = cab["Set-Cookie"]
        self.assertIn(f"estudio_chave={CHAVES['completo']}", cookie)
        for parte in ("HttpOnly", "SameSite=Strict", "Path=/", "Max-Age=2592000"):
            self.assertIn(parte, cookie)
        pagina = {"Cookie": f"estudio_chave={CHAVES['completo']}"}
        self.assertEqual(self.pedir_cru(IP_REMOTO, "/api/estado", cabecalhos=pagina)[0], 200)
        self.assertEqual(self.pedir_cru(IP_REMOTO, "/", cabecalhos=pagina)[0], 200)

    def test_entrar_com_chave_operador_ou_errada_401(self):
        for chave in (CHAVES["operador"], "x" * 32, ""):
            codigo, cab, corpo = self.entrar(chave)
            self.assertEqual(codigo, 401, chave)
            self.assertIsNone(cab["Set-Cookie"])
            self.assertIn("Chave inválida.".encode(), corpo)
            self.assertIn(b"name=\"chave\"", corpo)

    def test_entrar_de_outra_origem_403(self):
        codigo, cab, _ = self.entrar(CHAVES["completo"], {"Origin": "http://exemplo.com"})
        self.assertEqual(codigo, 403)
        self.assertIsNone(cab["Set-Cookie"])

    def test_cookie_nao_vale_para_outra_origem_na_api(self):
        pagina = {"Cookie": f"estudio_chave={CHAVES['completo']}", "Origin": "http://exemplo.com"}
        self.assertEqual(self.pedir_cru(IP_REMOTO, "/api/parar", "POST", b"{}", pagina)[0], 403)

    def test_local_nao_tem_entrada(self):
        self.assertEqual(self.pedir("127.0.0.1", "/entrar")[0], 404)
        codigo, _, _ = self.pedir_cru("127.0.0.1", "/entrar", "POST", b"chave=x", {"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(codigo, 404)

    def test_remoto_outros_caminhos_seguem_barrados(self):
        self.assertEqual(self.pedir(IP_REMOTO, "/pagina/nova.css")[0], 401)
        self.assertEqual(self.pedir(IP_REMOTO, "/entrar/x")[0], 401)

    def pedir_tamanho(self, ip, caminho, tamanho):
        """POST com o Content-Length escrito a mao (urllib nao manda um valor invalido); devolve (codigo, corpo)."""
        import socket
        with socket.create_connection((ip, self.porta), timeout=30) as c:
            c.sendall((f"POST {caminho} HTTP/1.1\r\nHost: {ip}:{self.porta}\r\nContent-Type: application/x-www-form-urlencoded\r\n"
                       f"Content-Length: {tamanho}\r\nConnection: close\r\n\r\nchave=x").encode())
            resposta = b""
            while bloco := c.recv(65536):
                resposta += bloco
        cabecalho, _, corpo = resposta.partition(b"\r\n\r\n")
        return int(cabecalho.split()[1]), corpo

    def test_tamanho_invalido_400_sem_ler_o_corpo(self):
        for tamanho in ("-1", "abc"):
            for ip in (IP_REMOTO, "127.0.0.1"):
                codigo, corpo = self.pedir_tamanho(ip, "/entrar", tamanho)
                self.assertEqual(codigo, 400, (ip, tamanho))
                self.assertEqual(json.loads(corpo), {"erro": "Tamanho do pedido inválido."})

    def test_criar_remoto_sem_chaves_devolve_none(self):
        config.REMOTO = {"escutar": IP_REMOTO, "chaves": {}}
        self.assertIsNone(servidor.criar_remoto(self.porta + 2))
        config.REMOTO = {"escutar": None, "chaves": dict(CHAVES)}
        self.assertIsNone(servidor.criar_remoto(self.porta + 2))


if __name__ == "__main__":
    unittest.main()
