"""Testes das chaves de acesso remoto (acesso.py) e da leitura de remoto do local.json (config.py).
Usam chaves falsas; nada vem do local.json real. Uso: python -I testar_acesso.py"""
import json, sys, threading, unittest, urllib.error, urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
import acesso, servidor


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


PORTA = 8197
IP_REMOTO = "127.0.0.2"  # no Windows todo 127.x.x.x e desta maquina
CHAVES = {"operador": "o" * 32, "completo": "c" * 32}


class Servidores(unittest.TestCase):
    """Um servidor local (127.0.0.1) e um remoto (127.0.0.2) na mesma porta de teste."""

    def setUp(self):
        antes, pausa = config.REMOTO, acesso.PAUSA_ERRO
        config.REMOTO = {"escutar": IP_REMOTO, "chaves": dict(CHAVES)}
        acesso.PAUSA_ERRO = 0
        self.addCleanup(setattr, config, "REMOTO", antes)
        self.addCleanup(setattr, acesso, "PAUSA_ERRO", pausa)
        for s in (servidor.criar(PORTA), servidor.criar(PORTA, endereco=IP_REMOTO)):
            fio = threading.Thread(target=s.serve_forever, args=(0.05,), daemon=True)
            fio.start()
            self.addCleanup(fio.join, 5)
            self.addCleanup(s.server_close)
            self.addCleanup(s.shutdown)

    def pedir(self, ip, caminho, chave=None, metodo="GET", corpo=None):
        cab = {"Host": f"{ip}:{PORTA}"}
        if chave:
            cab["Authorization"] = f"Bearer {chave}"
        if corpo is not None:
            cab["Content-Type"] = "application/json"
        p = urllib.request.Request(f"http://{ip}:{PORTA}{caminho}", data=corpo, headers=cab, method=metodo)
        try:
            with urllib.request.urlopen(p, timeout=30) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_servidor_remoto_sabe_que_e_remoto(self):
        s = servidor.criar(PORTA + 1, endereco=IP_REMOTO)
        self.addCleanup(s.server_close)
        self.assertTrue(s.remoto)
        l = servidor.criar(PORTA + 1)
        self.addCleanup(l.server_close)
        self.assertFalse(l.remoto)

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
        p = urllib.request.Request(f"http://{IP_REMOTO}:{PORTA}/api/estado", headers={"Host": "outro.site", "Authorization": f"Bearer {CHAVES['completo']}"})
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
        cab = {"Host": f"{ip}:{PORTA}", **(cabecalhos or {})}
        p = urllib.request.Request(f"http://{ip}:{PORTA}{caminho}", data=corpo, headers=cab, method=metodo)
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
        with socket.create_connection((ip, PORTA), timeout=30) as c:
            c.sendall((f"POST {caminho} HTTP/1.1\r\nHost: {ip}:{PORTA}\r\nContent-Type: application/x-www-form-urlencoded\r\n"
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
        self.assertIsNone(servidor.criar_remoto(PORTA + 2))
        config.REMOTO = {"escutar": None, "chaves": dict(CHAVES)}
        self.assertIsNone(servidor.criar_remoto(PORTA + 2))


if __name__ == "__main__":
    unittest.main()
