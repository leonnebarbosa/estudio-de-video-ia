"""Teste do servidor no ar, numa porta de teste. Le os projetos reais, so para leitura; nao usa o ComfyUI nem gera nada.

Uso: python -I testar_servidor.py
"""
import json, sys, threading, unittest, urllib.error, urllib.parse, urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config, servidor

PORTA = 8199


class Servidor(unittest.TestCase):
    def setUp(self):
        self.s = servidor.criar(PORTA)
        self.fio = threading.Thread(target=self.s.serve_forever, daemon=True)
        self.fio.start()
        self.addCleanup(self.fio.join, 5)
        self.addCleanup(self.s.server_close)
        self.addCleanup(self.s.shutdown)

    def pegar(self, caminho):
        pedido = urllib.request.Request(f"http://127.0.0.1:{PORTA}{caminho}", headers={"Host": f"127.0.0.1:{PORTA}"})
        with urllib.request.urlopen(pedido, timeout=30) as r:
            return r.status, r.read()

    def test_servidor_responde(self):
        codigo, corpo = self.pegar("/")
        self.assertEqual(codigo, 200)
        self.assertIn(b"<html", corpo.lower())
        codigo, corpo = self.pegar("/api/estado")
        self.assertEqual(codigo, 200)
        estado = json.loads(corpo)
        # Os projetos reais mudam com o uso: compara com o que esta no disco em vez de um numero fixo
        self.assertEqual(len(estado["projetos"]), len(list(config.PROJETOS.glob("*/estado.json"))))
        com_video = sorted(p.parent.name for p in config.PROJETOS.glob("*/final.mp4"))
        if not com_video:
            self.skipTest("nenhum projeto com final.mp4 para conferir o envio de video")
        codigo, corpo = self.pegar(f"/video/{urllib.parse.quote(com_video[0])}/final.mp4")
        self.assertEqual(codigo, 200)
        self.assertGreater(len(corpo), 1000)

    def test_pagina_serve_so_a_pasta(self):
        for caminho, tipo in (("/pagina/estilo.css", "text/css"), ("/pagina/js/base.js", "text/javascript")):
            pedido = urllib.request.Request(f"http://127.0.0.1:{PORTA}{caminho}", headers={"Host": f"127.0.0.1:{PORTA}"})
            with urllib.request.urlopen(pedido, timeout=30) as r:
                self.assertEqual(r.status, 200)
                self.assertTrue(r.headers["Content-Type"].startswith(tipo), r.headers["Content-Type"])
                self.assertEqual(r.headers["Cache-Control"], "no-store")
                self.assertGreater(len(r.read()), 100)
        for caminho in ("/pagina/../config.py", "/pagina/js/..%5C..%5Cconfig.py", "/pagina/js/%2e%2e/%2e%2e/config.py", r"/pagina/js/..\..\config.py", "/pagina/nao_existe.js"):
            with self.assertRaises(urllib.error.HTTPError, msg=caminho) as c:
                self.pegar(caminho)
            self.assertEqual(c.exception.code, 404, caminho)

    def test_descartar_imagem_tem_rota_e_recusa_projeto_inexistente(self):
        # Sem confirmar e com um projeto que nao existe: so confere que a rota responde, sem tocar em nada do disco
        pedido = urllib.request.Request(f"http://127.0.0.1:{PORTA}/api/apagar-imagem", method="POST",
                                        data=json.dumps({"projeto": "nao_existe_teste_8199", "arquivo": "imagem_1.png"}).encode(),
                                        headers={"Host": f"127.0.0.1:{PORTA}", "Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as c:
            urllib.request.urlopen(pedido, timeout=30)
        self.assertEqual(c.exception.code, 404)
        self.assertIn("Projeto não encontrado", json.loads(c.exception.read())["erro"])


class PcNovo(unittest.TestCase):
    """Num PC novo as pastas de dados (fora do git) nao existem; e uma falha inesperada tem que virar mensagem, nao conexao caida."""

    def setUp(self):
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.raiz = Path(tmp.name)
        antigos = {k: getattr(config, k) for k in ("PROJETOS", "ENVIOS", "LOGS")}
        for k in antigos:
            setattr(config, k, self.raiz / k.lower())
        self.addCleanup(lambda: [setattr(config, k, v) for k, v in antigos.items()])

    def test_criar_faz_as_pastas_de_dados(self):
        s = servidor.criar(PORTA + 1)
        s.server_close()
        for k in ("projetos", "envios", "logs"):
            self.assertTrue((self.raiz / k).is_dir(), k)

    def test_falha_inesperada_vira_mensagem(self):
        s = servidor.criar(PORTA + 1)
        fio = threading.Thread(target=s.serve_forever, daemon=True)
        fio.start()
        self.addCleanup(fio.join, 5)
        self.addCleanup(s.server_close)
        self.addCleanup(s.shutdown)
        original = servidor.acoes.acao_iniciar_texto
        servidor.acoes.acao_iniciar_texto = lambda d: (_ for _ in ()).throw(FileNotFoundError("pasta sumiu"))
        self.addCleanup(setattr, servidor.acoes, "acao_iniciar_texto", original)
        pedido = urllib.request.Request(f"http://127.0.0.1:{PORTA + 1}/api/iniciar-texto", method="POST", data=b"{}",
                                        headers={"Host": f"127.0.0.1:{PORTA + 1}", "Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as c:
            urllib.request.urlopen(pedido, timeout=30)
        self.assertEqual(c.exception.code, 500)
        self.assertIn("FileNotFoundError", json.loads(c.exception.read())["erro"])


if __name__ == "__main__":
    unittest.main()
