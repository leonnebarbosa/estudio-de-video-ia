"""Testes da avaliacao do LLM operador (avaliar_operador.py). Usam um servidor HTTP falso em 127.0.0.1;
nunca chamam um modelo de verdade nem executam nada no estudio. Uso: python -I testar_avaliar_operador.py"""
import json, sys, tempfile, threading, unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
import avaliar_operador, mcp_servidor, mcp_ferramentas  # noqa: F401 (o import registra as ferramentas)


def chamada(nome, **args):
    return {"name": nome, "arguments": args}


class Pontuar(unittest.TestCase):
    def test_nome_e_argumento_certos(self):
        ok, _ = avaliar_operador.pontuar({"ferramenta": "planejar_video", "argumentos": {"receita": "podcast", "duracao": 10}},
                                         chamada("planejar_video", receita="podcast", duracao=10, texto="oi"))
        self.assertTrue(ok)

    def test_receita_fora_da_lista(self):
        espera = {"ferramenta": "planejar_video", "argumentos": {"receita": ["anuncio_vertical", "fala_camera"]}}
        self.assertTrue(avaliar_operador.pontuar(espera, chamada("planejar_video", receita="fala_camera"))[0])
        ok, motivo = avaliar_operador.pontuar(espera, chamada("planejar_video", receita="podcast"))
        self.assertFalse(ok)
        self.assertIn("receita", motivo)

    def test_nome_dentro_da_lista_e_fora(self):
        espera = {"ferramenta": ["ver_andamento", "ver_estado"], "argumentos": {}}
        self.assertTrue(avaliar_operador.pontuar(espera, chamada("ver_estado"))[0])
        ok, motivo = avaliar_operador.pontuar(espera, chamada("parar_geracao"))
        self.assertFalse(ok)
        self.assertIn("parar_geracao", motivo)

    def test_argumento_faltando(self):
        ok, motivo = avaliar_operador.pontuar({"ferramenta": "planejar_video", "argumentos": {"formato": "9:16"}}, chamada("planejar_video"))
        self.assertFalse(ok)
        self.assertIn("formato", motivo)

    def test_sem_chamada_quando_devia_perguntar(self):
        self.assertTrue(avaliar_operador.pontuar({"ferramenta": None, "argumentos": {}}, None)[0])

    def test_chamou_quando_devia_perguntar(self):
        ok, motivo = avaliar_operador.pontuar({"ferramenta": None, "argumentos": {}}, chamada("planejar_video"))
        self.assertFalse(ok)
        self.assertIn("planejar_video", motivo)

    def test_nao_chamou_quando_devia(self):
        ok, _ = avaliar_operador.pontuar({"ferramenta": "retomar_fila", "argumentos": {}}, None)
        self.assertFalse(ok)

    def test_alternativas_basta_uma(self):
        espera = [{"ferramenta": "regras_das_tomadas", "argumentos": {"receita": "podcast"}},
                  {"ferramenta": ["listar_personagens", "ver_estado"], "argumentos": {}}]
        self.assertTrue(avaliar_operador.pontuar(espera, chamada("regras_das_tomadas", receita="podcast", qualidade="ugc"))[0])
        self.assertTrue(avaliar_operador.pontuar(espera, chamada("listar_personagens"))[0])
        ok, motivo = avaliar_operador.pontuar(espera, chamada("regras_das_tomadas", receita="fala_camera"))
        self.assertFalse(ok)
        self.assertIn("receita", motivo)
        self.assertFalse(avaliar_operador.pontuar(espera, chamada("planejar_video"))[0])
        self.assertFalse(avaliar_operador.pontuar(espera, None)[0])


class Pedidos(unittest.TestCase):
    def test_arquivo_valido_contra_os_esquemas_reais(self):
        pedidos = avaliar_operador.carregar_pedidos()
        self.assertGreaterEqual(len(pedidos), 11)
        esquemas = {t["name"]: t["inputSchema"] for t in mcp_servidor.listar("operador")}
        for p in pedidos:
            for e in p["espera"] if isinstance(p["espera"], list) else [p["espera"]]:
                nomes = e["ferramenta"] if isinstance(e["ferramenta"], list) else [e["ferramenta"]]
                for n in nomes:
                    if n is None:
                        continue
                    self.assertIn(n, esquemas, p["pedido"])
                    for campo, valor in e["argumentos"].items():
                        prop = esquemas[n]["properties"][campo]
                        for v in valor if isinstance(valor, list) else [valor]:
                            if "enum" in prop:
                                self.assertIn(v, prop["enum"], p["pedido"] + ": " + campo)

    def test_pedidos_de_video_comecam_pelas_regras(self):
        # O agente escreve as tomadas: antes do planejar_video vem regras_das_tomadas (ou uma consulta)
        pedidos = {p["pedido"]: p["espera"] for p in avaliar_operador.carregar_pedidos()}
        video = [e for e in pedidos.values() if isinstance(e, list)]
        self.assertGreaterEqual(len(video), 4)
        for e in video:
            self.assertEqual(e[0]["ferramenta"], "regras_das_tomadas")
            self.assertIn("receita", e[0]["argumentos"])
            self.assertEqual(set(e[1]["ferramenta"]), {"listar_personagens", "listar_receitas", "ver_estado"})
        self.assertFalse([e for e in pedidos.values() if "planejar_video" in str(e)])
        rapido = pedidos["faz um rápido da Ana falando oi, vertical"]
        self.assertEqual(rapido[0]["argumentos"]["qualidade"], "rapido")
        self.assertEqual(pedidos["faz um podcast de 10 segundos com o Bruno"][0]["argumentos"]["receita"], "podcast")
        self.assertEqual(pedidos["uma cena de praia ao pôr do sol, 5 segundos, quadrado"][0]["argumentos"]["receita"], "cena_texto")

    def test_ferramentas_em_formato_openai(self):
        ferr = avaliar_operador.ferramentas_openai()
        self.assertEqual([f["function"]["name"] for f in ferr], [t["name"] for t in mcp_servidor.listar("operador")])
        self.assertEqual(ferr[0]["type"], "function")
        self.assertIn("parameters", ferr[0]["function"])


class Falso:
    def __init__(self, respostas):
        self.respostas, self.recebidos = respostas, []
        falso = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                corpo = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                falso.recebidos.append(corpo)
                r = falso.respostas[min(len(falso.recebidos), len(falso.respostas)) - 1]
                status, dados = (r if isinstance(r, tuple) else (200, r))
                dados = json.dumps(dados).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(dados)))
                self.end_headers()
                self.wfile.write(dados)

            def log_message(self, *a):
                pass

        self.srv = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_port}/v1"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def fechar(self):
        self.srv.shutdown()
        self.srv.server_close()


def com_chamada(nome, args):
    return {"choices": [{"message": {"content": None, "tool_calls": [{"id": "1", "type": "function", "function": {"name": nome, "arguments": json.dumps(args)}}]}}]}


class PontaAPonta(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def rodar(self, falso, pedidos):
        self.addCleanup(falso.fechar)
        return avaliar_operador.avaliar(falso.url, "modelo-teste", pedidos, tempo=5)

    def test_um_acerto_gera_relatorio_1_de_1(self):
        falso = Falso([com_chamada("parar_geracao", {})])
        r = self.rodar(falso, [{"pedido": "para tudo", "espera": {"ferramenta": "parar_geracao", "argumentos": {}}}])
        corpo = falso.recebidos[0]
        self.assertEqual(corpo["model"], "modelo-teste")
        self.assertEqual(corpo["tool_choice"], "auto")
        self.assertEqual(corpo["messages"][0]["role"], "system")
        self.assertEqual(corpo["messages"][1], {"role": "user", "content": "para tudo"})
        self.assertTrue(any(t["function"]["name"] == "parar_geracao" for t in corpo["tools"]))
        texto = avaliar_operador.relatorio("modelo-teste", r)
        self.assertIn("1/1", texto)
        self.assertIn("parar_geracao", texto)
        saida = Path(self.tmp.name) / "r.md"
        avaliar_operador.gravar(saida, texto)
        self.assertIn("1/1", saida.read_text(encoding="utf-8"))

    def test_erro_e_texto_sem_chamada_nao_param_a_rodada(self):
        falso = Falso([(500, {"error": "x"}), {"choices": [{"message": {"content": "Qual personagem?"}}]}, com_chamada("retomar_fila", {})])
        pedidos = [{"pedido": "a", "espera": {"ferramenta": "retomar_fila", "argumentos": {}}},
                   {"pedido": "faz um vídeo", "espera": {"ferramenta": None, "argumentos": {}}},
                   {"pedido": "c", "espera": {"ferramenta": "retomar_fila", "argumentos": {}}}]
        r = self.rodar(falso, pedidos)
        self.assertEqual([x["ok"] for x in r], [False, True, True])
        texto = avaliar_operador.relatorio("m", r)
        self.assertIn("2/3", texto)
        self.assertIn("Qual personagem?", texto)

    def test_argumentos_invalidos_contam_como_erro(self):
        resp = {"choices": [{"message": {"tool_calls": [{"function": {"name": "retomar_fila", "arguments": "{quebrado"}}]}}]}
        r = self.rodar(Falso([resp]), [{"pedido": "a", "espera": {"ferramenta": "retomar_fila", "argumentos": {}}}])
        self.assertFalse(r[0]["ok"])

    def test_nada_e_executado_no_estudio(self):
        with mock.patch.dict(mcp_servidor.FERRAMENTAS["parar_geracao"], {"funcao": mock.Mock(side_effect=AssertionError("executou"))}):
            r = self.rodar(Falso([com_chamada("parar_geracao", {})]), [{"pedido": "p", "espera": {"ferramenta": "parar_geracao", "argumentos": {}}}])
        self.assertTrue(r[0]["ok"])


if __name__ == "__main__":
    unittest.main()
