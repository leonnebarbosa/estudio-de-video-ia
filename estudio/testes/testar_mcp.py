"""Testes do MCP minimo (mcp_servidor.py e mcp_ferramentas.py): chamam atender() direto, sem rede.
Uso: python -I testar_mcp.py"""
import base64, json, socket, sys, tempfile, threading, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
import acoes, fila, servidor, mcp_servidor, mcp_ferramentas, personagens, projetos, tarefa  # noqa: F401 (o import registra as ferramentas)
from erros import Erro

OPERADOR = {"ver_estado", "listar_personagens", "listar_projetos", "listar_receitas", "regras_das_tomadas", "planejar_video",
            "confirmar_plano", "ver_andamento", "parar_geracao", "retomar_fila", "ver_resultado"}


def chamar(nome, argumentos=None, nivel="operador"):
    return rpc("tools/call", {"name": nome, "arguments": argumentos or {}}, nivel=nivel)[1]["result"]


def rpc(metodo, params=None, id_=1, nivel="operador"):
    return mcp_servidor.atender(json.dumps({"jsonrpc": "2.0", "id": id_, "method": metodo, "params": params or {}}).encode(), nivel)


class Mcp(unittest.TestCase):
    def registrar(self, nome, niveis, funcao):
        mcp_servidor.registrar(nome, "x", {"type": "object", "properties": {}}, niveis, funcao)
        self.addCleanup(mcp_servidor.FERRAMENTAS.pop, nome)

    def test_initialize_devolve_versao_e_instrucoes(self):
        codigo, r = rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}})
        self.assertEqual(codigo, 200)
        self.assertEqual(r["result"]["protocolVersion"], "2025-03-26")
        self.assertIn("tools", r["result"]["capabilities"])
        self.assertTrue(r["result"]["instructions"])

    def test_versao_desconhecida_cai_na_primeira(self):
        r = rpc("initialize", {"protocolVersion": "1999-01-01"})[1]
        self.assertEqual(r["result"]["protocolVersion"], mcp_servidor.PROTOCOLOS[0])

    def test_notificacao_sem_corpo(self):
        codigo, r = mcp_servidor.atender(b'{"jsonrpc":"2.0","method":"notifications/initialized"}', "operador")
        self.assertEqual((codigo, r), (202, None))

    def test_ping(self):
        self.assertEqual(rpc("ping", id_=7)[1], {"jsonrpc": "2.0", "id": 7, "result": {}})

    def test_corpo_ruim(self):
        self.assertEqual(mcp_servidor.atender(b"{", "operador")[1]["error"]["code"], -32700)
        self.assertEqual(mcp_servidor.atender(b"[]", "operador")[1]["error"]["code"], -32600)
        self.assertEqual(mcp_servidor.atender(b'{"jsonrpc":"2.0","id":1}', "operador")[1]["error"]["code"], -32600)
        self.assertEqual(rpc("nao/existe")[1]["error"]["code"], -32601)

    def test_ver_estado_lista_e_chama(self):
        nomes = [f["name"] for f in rpc("tools/list")[1]["result"]["tools"]]
        self.assertIn("ver_estado", nomes)
        r = rpc("tools/call", {"name": "ver_estado", "arguments": {}})[1]["result"]
        self.assertFalse(r.get("isError"))
        self.assertEqual(r["content"][0]["type"], "text")

    def test_ferramenta_fora_do_nivel(self):
        self.registrar("so_completo_teste", {"completo"}, lambda a: [mcp_servidor.texto("ok")])
        self.assertNotIn("so_completo_teste", [f["name"] for f in rpc("tools/list")[1]["result"]["tools"]])
        self.assertNotIn("so_completo_teste", [f["name"] for f in mcp_servidor.listar("operador")])
        self.assertIn("so_completo_teste", [f["name"] for f in mcp_servidor.listar("completo")])
        r = rpc("tools/call", {"name": "so_completo_teste", "arguments": {}})[1]["result"]
        self.assertTrue(r["isError"])
        self.assertIn("não disponível", r["content"][0]["text"])
        r = rpc("tools/call", {"name": "so_completo_teste", "arguments": {}}, nivel="completo")[1]["result"]
        self.assertFalse(r.get("isError"))

    def test_erro_de_validacao_vira_resultado_com_erro(self):
        def falha(a):
            raise Erro("Projeto não existe.")
        self.registrar("falha_teste", {"operador"}, falha)
        r = rpc("tools/call", {"name": "falha_teste", "arguments": {}})[1]["result"]
        self.assertTrue(r["isError"])
        self.assertEqual(r["content"][0]["text"], "Projeto não existe.")

    def test_nome_malformado_e_parametro_invalido(self):
        for nome in ([], {}, 3, None):
            self.assertEqual(rpc("tools/call", {"name": nome, "arguments": {}})[1]["error"]["code"], -32602, nome)

    def test_ferramenta_inexistente(self):
        r = rpc("tools/call", {"name": "nao_existe", "arguments": {}})[1]["result"]
        self.assertTrue(r["isError"])

    def test_imagem_em_base64(self):
        c = mcp_servidor.imagem(b"\x89PNG")
        self.assertEqual((c["type"], c["mimeType"]), ("image", "image/png"))
        self.assertEqual(c["data"], "iVBORw==")


class Operador(unittest.TestCase):
    """As ferramentas do nivel operador (o agente que conversa com o usuario). Sem ComfyUI, sem ffmpeg de verdade, projetos numa pasta temporaria."""

    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.raiz = Path(d.name)
        for nome in ("projetos", "personagens"):
            (self.raiz / nome).mkdir()
        for alvo, nome, valor in ((config, "PROJETOS", self.raiz / "projetos"), (personagens, "PASTA", self.raiz / "personagens")):
            antigo = getattr(alvo, nome)
            setattr(alvo, nome, valor)
            self.addCleanup(setattr, alvo, nome, antigo)

    def test_operador_tem_so_as_ferramentas_dele(self):
        nomes = {f["name"] for f in rpc("tools/list")[1]["result"]["tools"]}
        self.assertEqual(nomes, OPERADOR)
        self.assertEqual(len(nomes), 11)
        self.assertLessEqual(OPERADOR, {f["name"] for f in mcp_servidor.listar("completo")})
        # Nenhuma ferramenta de apagar no operador
        self.assertFalse([n for n in nomes if "apagar" in n or "excluir" in n or "delete" in n])
        # A qualidade do planejar_video: duas opcoes, "ugc" quando o modelo nao disser
        esquema = next(f for f in mcp_servidor.listar("operador") if f["name"] == "planejar_video")["inputSchema"]
        q = esquema["properties"]["qualidade"]
        self.assertEqual((q["enum"], q["default"]), (["ugc", "rapido"], "ugc"))
        # Fora do required: sem ela vale o default
        self.assertNotIn("qualidade", esquema["required"])
        regras = next(f for f in mcp_servidor.listar("operador") if f["name"] == "regras_das_tomadas")["inputSchema"]
        self.assertEqual(regras["required"], ["receita"])

    def test_descricoes_tem_exemplo(self):
        for f in mcp_servidor.listar("operador"):
            for parte in ("Quando usar", "Quando não usar", "Exemplo"):
                self.assertIn(parte, f["description"], (f["name"], parte))

    def test_listar_personagens(self):
        self.assertIn("Nenhum personagem", chamar("listar_personagens")["content"][0]["text"])
        for pid, nome in (("ana", "Ana"), ("bruno", "Bruno")):
            p = self.raiz / "personagens" / pid
            p.mkdir()
            (p / "ficha.json").write_text(json.dumps({"nome": nome}), encoding="utf-8")
            (p / "frente.png").write_bytes(b"png")
        r = chamar("listar_personagens")
        self.assertFalse(r["isError"])
        t = r["content"][0]["text"]
        self.assertIn("ana: Ana", t)
        self.assertIn("bruno: Bruno", t)
        self.assertNotIn("{", t)

    def test_listar_projetos_os_10_mais_recentes(self):
        self.assertIn("Nenhum projeto", chamar("listar_projetos")["content"][0]["text"])
        lista = [{"nome": f"p{i:02d}", "tipo": "imagem" if i % 2 else "texto", "quando": 1_800_000_000 - i * 60,
                  "final": {"marca": 1} if i == 0 else None} for i in range(12)]
        with mock.patch.object(projetos, "listar_projetos", lambda: lista):
            t = chamar("listar_projetos")["content"][0]["text"]
        linhas = [x for x in t.splitlines() if x.startswith("p")]
        self.assertEqual(len(linhas), 10)
        self.assertTrue(linhas[0].startswith("p00"))
        self.assertIn("pronto", linhas[0])
        self.assertIn("incompleto", linhas[1])
        self.assertIn("imagem", linhas[1])
        self.assertNotIn("p10", t)

    def test_ver_andamento(self):
        with mock.patch.object(tarefa.tarefa, "resumo", lambda: None):
            self.assertEqual(chamar("ver_andamento")["content"][0]["text"], "Nada gerando agora.")
        with mock.patch.object(tarefa.tarefa, "resumo", lambda: {"projeto": "x", "rodando": False, "segundos": 9}):
            self.assertEqual(chamar("ver_andamento")["content"][0]["text"], "Nada gerando agora.")
        r = {"projeto": "mcp_podcast_1", "modo": "gerar", "rodando": True, "etapa": "gerar", "segundos": 125,
             "progresso": {"tomada": 2, "total": 4, "etapa": "gerar", "valor": 3, "maximo": 8}}
        with mock.patch.object(tarefa.tarefa, "resumo", lambda: r):
            t = chamar("ver_andamento")["content"][0]["text"]
        for parte in ("mcp_podcast_1", "125 s", "tomada 2 de 4", "passo 3 de 8"):
            self.assertIn(parte, t)
        self.assertNotIn("{", t)

    def test_parar_pausa_a_fila(self):
        f = fila.Fila(lambda *a: None, lambda: False, tarefa.tarefa.trava, lambda: True, arquivo=self.raiz / "fila.json")
        parados = []
        with mock.patch.object(tarefa.tarefa, "fila", f), mock.patch.object(tarefa.tarefa, "parar", lambda: parados.append(1)):
            r = chamar("parar_geracao")
        self.assertFalse(r["isError"], r)
        self.assertEqual(parados, [1])
        self.assertTrue(f.resumo()["pausada"])
        self.assertEqual(f.resumo()["motivo"], "Parado pelo agente (MCP).")
        self.assertFalse(tarefa.tarefa.trava.locked())
        self.assertIn("retomar_fila", r["content"][0]["text"])

    def test_retomar_fila(self):
        pedidos = []
        with mock.patch.object(acoes, "acao_fila", lambda d: pedidos.append(d) or {"pausada": False, "motivo": "", "itens": [{"projeto": "a"}]}):
            r = chamar("retomar_fila")
        self.assertFalse(r["isError"], r)
        self.assertEqual(pedidos, [{"acao": "continuar"}])
        self.assertIn("1 pedido", r["content"][0]["text"])

        def ocupado(d):
            raise Erro("Uma imagem está sendo pintada.", 409)
        with mock.patch.object(acoes, "acao_fila", ocupado):
            r = chamar("retomar_fila")
        self.assertTrue(r["isError"])
        self.assertIn("pintada", r["content"][0]["text"])

    def test_ver_resultado_sem_video(self):
        (self.raiz / "projetos" / "mcp_podcast_1").mkdir()
        chamados = []
        with mock.patch.object(mcp_ferramentas, "_ler_final", lambda v: chamados.append(v)):
            r = chamar("ver_resultado", {"projeto": "mcp_podcast_1"})
        self.assertFalse(r["isError"], r)
        self.assertEqual(r["content"], [{"type": "text", "text": "Ainda não terminou."}])
        self.assertEqual(chamados, [])

    def test_ver_resultado_projeto_ruim(self):
        for args in ({"projeto": "nao_existe"}, {"projeto": "../fora"}, {}):
            r = chamar("ver_resultado", args)
            self.assertTrue(r["isError"], args)
        self.assertIn("listar_projetos", chamar("ver_resultado", {"projeto": "nao_existe"})["content"][0]["text"])

    def test_ver_resultado_com_video(self):
        pasta = self.raiz / "projetos" / "mcp_podcast_1"
        pasta.mkdir()
        (pasta / "final.mp4").write_bytes(b"mp4")
        with mock.patch.object(mcp_ferramentas, "_ler_final", lambda v: (10.04, b"\x89PNG")):
            r = chamar("ver_resultado", {"projeto": "mcp_podcast_1"})
        self.assertFalse(r["isError"], r)
        t, img = r["content"]
        self.assertIn("10 s", t["text"])
        # A chave operador nao abre o /video/ (403): o texto manda para a pagina
        self.assertNotIn("/video/", t["text"])
        self.assertIn("abra na página do estúdio, em Projetos", t["text"])
        self.assertEqual((img["type"], img["data"]), ("image", "iVBORw=="))
        # Sem conseguir ler o quadro: so o texto
        with mock.patch.object(mcp_ferramentas, "_ler_final", lambda v: (None, None)):
            r = chamar("ver_resultado", {"projeto": "mcp_podcast_1"})
        self.assertFalse(r["isError"], r)
        self.assertEqual(len(r["content"]), 1)
        self.assertIn("Projetos", r["content"][0]["text"])
        # A chave completa abre o endereco do video
        with mock.patch.object(mcp_ferramentas, "_ler_final", lambda v: (10.04, b"\x89PNG")):
            r = chamar("ver_resultado", {"projeto": "mcp_podcast_1"}, nivel="completo")
        self.assertIn("/video/mcp_podcast_1/final.mp4", r["content"][0]["text"])
        self.assertIsNone(mcp_servidor.nivel_atual())

    def test_ler_final_le_a_duracao_do_ffmpeg(self):
        saida = "Input #0, mov,mp4\n  Duration: 00:00:10.04, start: 0.000000, bitrate: 900 kb/s\n"

        def rodar(cmd, **k):
            Path(cmd[-1]).write_bytes(b"\x89PNG")
            return mock.Mock(returncode=0, stderr=saida.encode())
        with mock.patch.object(mcp_ferramentas.subprocess, "run", rodar):
            self.assertEqual(mcp_ferramentas._ler_final(self.raiz / "final.mp4"), (10.04, b"\x89PNG"))

        def falha(cmd, **k):
            raise OSError("sem ffmpeg")
        with mock.patch.object(mcp_ferramentas.subprocess, "run", falha):
            self.assertEqual(mcp_ferramentas._ler_final(self.raiz / "final.mp4"), (None, None))

    def test_instrucoes_por_nivel(self):
        def instrucoes(nivel):
            return rpc("initialize", {"protocolVersion": "2025-06-18"}, nivel=nivel)[1]["result"]["instructions"]
        operador, completo = instrucoes("operador"), instrucoes("completo")
        self.assertEqual(operador, mcp_servidor.INSTRUCOES.read_text(encoding="utf-8").strip())
        self.assertTrue(completo.startswith(operador))
        extra = completo[len(operador):]
        for parte in ("chamar_api", "confirmar: true", "enviar_arquivo", "ver_log"):
            self.assertIn(parte, extra)
            self.assertNotIn(parte, operador)

    def test_instrucoes_curtas_e_com_as_regras(self):
        t = mcp_servidor.INSTRUCOES.read_text(encoding="utf-8")
        self.assertLessEqual(len(t.strip().splitlines()), 45)
        for parte in ("ver_estado", "listar_receitas", "listar_personagens", "planejar_video", "confirmar_plano", "parar_geracao", "rapido"):
            self.assertIn(parte, t)


NOVAS = {"chamar_api", "enviar_arquivo", "ver_log"}
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
SO_PARA_CHECAR = {"/api/ligar-comfy", "/api/parar"}  # tem efeito de verdade: so se confere na lista


class Completo(unittest.TestCase):
    """As ferramentas so do nivel completo (o Claude Code): passagem para a API, envio de arquivo e o fim do log."""

    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.raiz = Path(d.name)
        for nome in ("projetos", "entrada", "envios", "logs"):
            (self.raiz / nome).mkdir()
        for nome in ("PROJETOS", "ENTRADA", "ENVIOS", "LOGS"):
            antigo = getattr(config, nome)
            setattr(config, nome, self.raiz / nome.lower())
            self.addCleanup(setattr, config, nome, antigo)

    def porta_livre(self):
        with socket.socket() as t:
            t.bind(("127.0.0.1", 0))
            return t.getsockname()[1]

    def apontar(self, porta):
        antigo = mcp_ferramentas.PORTA_API
        mcp_ferramentas.PORTA_API = porta
        self.addCleanup(setattr, mcp_ferramentas, "PORTA_API", antigo)

    def no_ar(self):
        porta = self.porta_livre()
        s = servidor.criar(porta)
        fio = threading.Thread(target=s.serve_forever, args=(0.05,), daemon=True)
        fio.start()
        self.addCleanup(fio.join, 5)
        self.addCleanup(s.server_close)
        self.addCleanup(s.shutdown)
        self.apontar(porta)
        return porta

    def test_so_o_completo_enxerga_as_tres(self):
        self.assertLessEqual(NOVAS, {f["name"] for f in mcp_servidor.listar("completo")})
        self.assertFalse(NOVAS & {f["name"] for f in mcp_servidor.listar("operador")})
        r = chamar("ver_log", {"linhas": 1}, nivel="operador")
        self.assertTrue(r["isError"])
        self.assertEqual(r["content"][0]["text"], mcp_servidor.INDISPONIVEL)

    def test_rotas_sem_desligar_enviar_nem_abrir_e_todas_existem(self):
        rotas = servidor.ROTAS_POST
        self.assertIsInstance(rotas, frozenset)
        # Abrir pasta e instalador abre janelas no PC, que quem esta longe nao ve
        fora = {"/api/desligar", "/api/enviar", "/api/abrir-pasta", "/api/abrir-instalador"}
        self.assertFalse(fora & rotas)
        for r in ("/api/apagar", "/api/iniciar-imagem", "/api/fila", "/api/loras/salvar"):
            self.assertIn(r, rotas)
        esquema = next(f for f in mcp_servidor.listar("completo") if f["name"] == "chamar_api")["inputSchema"]
        self.assertEqual(set(esquema["properties"]["rota"]["enum"]), set(rotas))
        # E o inverso: toda rota /api/ do do_POST (menos as de fora) esta na lista
        import re, inspect
        fonte = inspect.getsource(servidor.Pedido.do_POST)
        achadas = set(re.findall(r'"(/api/[a-z/-]+)"', fonte)) - fora
        self.assertEqual(achadas, set(rotas))
        # A lista tem de bater com o do_POST: nenhuma rota dela pode dar "nao encontrado"
        self.no_ar()
        for rota in sorted(rotas - SO_PARA_CHECAR):
            codigo, corpo = mcp_ferramentas._postar(rota, {})
            self.assertNotEqual((codigo, corpo.get("erro")), (404, "Endereço não encontrado."), rota)

    def test_rota_fora_da_lista(self):
        for rota in ("/api/desligar", "/api/enviar", "/api/abrir-pasta", "/api/abrir-instalador", "/api/nao-existe", "/mcp", "http://outro/api/apagar"):
            r = chamar("chamar_api", {"rota": rota, "dados": {}}, nivel="completo")
            self.assertTrue(r["isError"], rota)

    def test_dados_precisam_ser_objeto(self):
        self.assertTrue(chamar("chamar_api", {"rota": "/api/apagar", "dados": [1]}, nivel="completo")["isError"])

    def test_chamar_api_devolve_o_erro_do_estudio(self):
        self.no_ar()
        r = chamar("chamar_api", {"rota": "/api/apagar", "dados": {"projeto": "nao_existe_teste"}}, nivel="completo")
        self.assertTrue(r["isError"])
        self.assertTrue(r["content"][0]["text"])
        self.assertNotIn("{", r["content"][0]["text"])

    def test_chamar_api_sucesso_devolve_o_json(self):
        self.no_ar()
        (config.PROJETOS / "p_teste").mkdir()
        (config.PROJETOS / "p_teste" / "estado.json").write_text("{}")
        r = chamar("chamar_api", {"rota": "/api/apagar", "dados": {"projeto": "p_teste"}}, nivel="completo")
        self.assertFalse(r["isError"], r)
        # Sem confirmar, so diz o que apagaria, como na pagina
        self.assertTrue((config.PROJETOS / "p_teste" / "estado.json").exists())
        self.assertNotIn("apagado", json.loads(r["content"][0]["text"]))

    def test_chamar_api_servidor_fora_do_ar(self):
        self.apontar(self.porta_livre())
        self.assertTrue(chamar("chamar_api", {"rota": "/api/fila", "dados": {}}, nivel="completo")["isError"])

    def test_enviar_arquivo_grava_a_foto(self):
        r = chamar("enviar_arquivo", {"tipo": "foto", "nome": "pequena.png", "conteudo_base64": base64.b64encode(PNG).decode()}, nivel="completo")
        self.assertFalse(r["isError"], r)
        self.assertEqual((config.ENTRADA / "pequena.png").read_bytes(), PNG)

    def test_enviar_arquivo_recusa_o_ruim(self):
        b64 = base64.b64encode(PNG).decode()
        casos = [{"tipo": "foto", "nome": "a.png", "conteudo_base64": "isto não é base64!!"},
                 {"tipo": "foto", "nome": "a.png", "conteudo_base64": ""},
                 {"tipo": "documento", "nome": "a.png", "conteudo_base64": b64},
                 {"tipo": "foto", "nome": "a.exe", "conteudo_base64": b64}]
        for c in casos:
            self.assertTrue(chamar("enviar_arquivo", c, nivel="completo")["isError"], c)
        self.assertEqual(list(config.ENTRADA.iterdir()), [])

    def test_enviar_arquivo_limite_de_20_mb(self):
        self.assertEqual(mcp_ferramentas.LIMITE_ARQUIVO, 20 * 1024 * 1024)
        with mock.patch.object(mcp_ferramentas, "LIMITE_ARQUIVO", 10):
            r = chamar("enviar_arquivo", {"tipo": "foto", "nome": "grande.png", "conteudo_base64": base64.b64encode(b"x" * 11).decode()}, nivel="completo")
        self.assertTrue(r["isError"])
        self.assertIn("envie pela página", r["content"][0]["text"])

    def test_ver_log_o_fim(self):
        (config.LOGS / "estudio.log").write_text("\n".join(f"linha {i}" for i in range(1, 301)) + "\n", encoding="utf-8")
        t = chamar("ver_log", {"linhas": 3}, nivel="completo")["content"][0]["text"]
        self.assertEqual(t.splitlines(), ["linha 298", "linha 299", "linha 300"])
        self.assertEqual(len(chamar("ver_log", {"linhas": 200}, nivel="completo")["content"][0]["text"].splitlines()), 200)

    def test_ver_log_limites_e_ausente(self):
        for n in (0, 201, "x", None):
            self.assertTrue(chamar("ver_log", {"linhas": n}, nivel="completo")["isError"], n)
        r = chamar("ver_log", {"linhas": 5}, nivel="completo")
        self.assertIn("Ainda não há log", r["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
