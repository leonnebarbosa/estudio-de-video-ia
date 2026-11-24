"""Testes do MCP minimo (mcp_servidor.py, mcp_ferramentas.py e os quatro mcp_*.py das funcoes): chamam atender() direto, sem rede.
Uso: python -I testar_mcp.py"""
import base64, json, re, socket, sys, tempfile, threading, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config, entrada
import acoes, envio, fila, links, midias, planos, servidor, mcp_servidor, mcp_ferramentas, mcp_completo, mcp_consultas, mcp_midias, personagens, projetos, tarefa  # noqa: F401 (o import registra as ferramentas)
from erros import Erro

# A frase da fila consulta o ComfyUI: nos testes ele esta sempre ligado e livre, tambem quando este modulo roda sozinho
import estimativas
estimativas.comfy = lambda: {"ligado": True, "ocupado": False}

OPERADOR = {"ver_estado", "listar_personagens", "listar_projetos", "listar_receitas", "regras_das_tomadas", "planejar_video",
            "confirmar_plano", "ver_andamento", "parar_geracao", "retomar_fila", "ver_resultado", "pedir_envio", "listar_midias", "importar_url",
            "regras_do_modo_livre", "planejar_video_livre", "planejar_imagem", "usar_resultado", "criar_personagem", "listar_modelos_video"}


def chamar(nome, argumentos=None, nivel="operador", base=None):
    return rpc("tools/call", {"name": nome, "arguments": argumentos or {}}, nivel=nivel, base=base)[1]["result"]


def rpc(metodo, params=None, id_=1, nivel="operador", base=None):
    return mcp_servidor.atender(json.dumps({"jsonrpc": "2.0", "id": id_, "method": metodo, "params": params or {}}).encode(), nivel, base)


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


class Registro(unittest.TestCase):
    """O registro das chamadas (logs/mcp.log): uma linha por chamada, para ver onde um agente parou."""

    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.arq = Path(d.name) / "mcp.log"
        trocas = [(mcp_servidor, "REGISTRO", self.arq)]
        for nome in ("ENTRADA", "ENVIOS"):  # o enviar_arquivo deste teste nunca toca a entrada de verdade
            (Path(d.name) / nome.lower()).mkdir()
            trocas.append((config, nome, Path(d.name) / nome.lower()))
        trocas += [(planos, "ARQUIVO", Path(d.name) / "planos.json"), (links, "ARQUIVO", Path(d.name) / "links.json")]  # nada vai para logs/ de verdade
        for alvo, nome, valor in trocas:
            self.addCleanup(setattr, alvo, nome, getattr(alvo, nome))
            setattr(alvo, nome, valor)

    def linhas(self):
        return self.arq.read_text(encoding="utf-8").splitlines() if self.arq.is_file() else []

    def test_desligado_por_padrao_nao_grava(self):
        mcp_servidor.REGISTRO = None
        self.assertFalse(chamar("listar_receitas")["isError"])
        self.assertEqual(self.linhas(), [])

    def test_uma_linha_por_chamada_com_nivel_ferramenta_e_resultado(self):
        self.assertFalse(chamar("listar_receitas")["isError"])
        r = chamar("planejar_video", {"formato": "9:16", "tomadas": [{"acao": "The character waves.", "camera": "aproximar"}]})
        self.assertTrue(r["isError"])
        ok, erro = self.linhas()
        self.assertRegex(ok, r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d operador listar_receitas ok \d+\.\ds args=\{\} -> ")
        self.assertIn(" operador planejar_video ERRO ", erro)
        self.assertIn('"formato": "9:16"', erro)
        self.assertIn("Falta a receita", erro)

    def test_ferramenta_que_nao_existe_tambem_fica_registrada(self):
        self.assertTrue(chamar("gerar_video_magico", {"x": 1})["isError"])
        (linha,) = self.linhas()
        self.assertIn(" operador gerar_video_magico ERRO ", linha)
        self.assertIn(mcp_servidor.INDISPONIVEL, linha)

    def test_textos_longos_sao_cortados(self):
        prompt = "a" * 5000
        chamar("planejar_video_livre", {"prompt": prompt, "referencias": [], "formato": "9:16", "duracao": 5})
        chamar("enviar_arquivo", {"nome": "x.png", "tipo": "foto", "conteudo_base64": "QUJD" * 3000}, nivel="completo")
        livre, envio = self.linhas()
        self.assertNotIn("a" * 400, livre)
        self.assertIn("(5000 caracteres)", livre)
        self.assertNotIn("QUJDQUJD", envio)
        self.assertIn("(12000 caracteres)", envio)
        self.assertLess(max(len(livre), len(envio)), 1500)

    def test_o_codigo_do_link_nao_vai_para_o_registro(self):
        r = chamar("pedir_envio", {"tipo": "foto"}, base="http://exemplo.test:8190")
        codigo = re.search(r"/m/([\w-]+)", r["content"][0]["text"])[1]
        (linha,) = self.linhas()
        self.assertNotIn(codigo, linha)
        self.assertIn("http://exemplo.test:8190/m/<código>", linha)

    def test_initialize_e_tools_list_ficam_registrados(self):
        rpc("initialize", {"protocolVersion": "2025-03-26"})
        rpc("tools/list")
        a, b = self.linhas()
        self.assertTrue(a.endswith(" operador initialize"))
        self.assertTrue(b.endswith(" operador tools/list"))

    def test_falha_ao_gravar_nao_quebra_a_chamada(self):
        mcp_servidor.REGISTRO = self.arq.parent  # uma pasta: abrir para escrever falha
        self.assertFalse(chamar("listar_receitas")["isError"])

    def test_arquivo_grande_vira_o_ponto_um(self):
        self.arq.write_text("x" * 50, encoding="utf-8")
        with mock.patch.object(mcp_servidor, "MAX_REGISTRO", 10):
            chamar("listar_receitas")
        self.assertEqual(self.arq.with_name("mcp.log.1").read_text(encoding="utf-8"), "x" * 50)
        self.assertEqual(len(self.linhas()), 1)


class Operador(unittest.TestCase):
    """As ferramentas do nivel operador (o agente que conversa com o usuario). Sem ComfyUI, sem ffmpeg de verdade, projetos numa pasta temporaria."""

    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.raiz = Path(d.name)
        for nome in ("projetos", "personagens", "entrada", "envios"):
            (self.raiz / nome).mkdir()
        for alvo, nome, valor in ((config, "PROJETOS", self.raiz / "projetos"), (personagens, "PASTA", self.raiz / "personagens"),
                                  (config, "ENTRADA", self.raiz / "entrada"), (config, "ENVIOS", self.raiz / "envios"),
                                  (midias, "ARQUIVO", self.raiz / "midias.json"), (planos, "ARQUIVO", self.raiz / "planos.json"),
                                  (links, "ARQUIVO", self.raiz / "links.json")):
            antigo = getattr(alvo, nome)
            setattr(alvo, nome, valor)
            self.addCleanup(setattr, alvo, nome, antigo)

    def test_operador_tem_so_as_ferramentas_dele(self):
        nomes = {f["name"] for f in rpc("tools/list")[1]["result"]["tools"]}
        self.assertEqual(nomes, OPERADOR)
        self.assertEqual(len(nomes), 20)
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

    def foto_enviada(self, nome="ana.png", tipo="foto", conteudo=None):
        """Uma foto de verdade (PNG pequeno) na entrada, registrada como midia."""
        if conteudo is None:
            from PIL import Image
            Image.new("RGB", (8, 8), (200, 100, 50)).save(self.raiz / "entrada" / nome)
        else:
            (self.raiz / "entrada" / nome).write_bytes(conteudo)
        midias.registrar(nome, tipo, "link", {})

    def pastas_de_personagens(self):
        return sorted(p.name for p in (self.raiz / "personagens").iterdir())

    def test_criar_personagem_devolve_o_id_e_aparece_na_lista(self):
        self.foto_enviada()
        r = chamar("criar_personagem", {"nome": "Ana Souza", "foto": "ana.png"})
        self.assertFalse(r["isError"], r)
        t = r["content"][0]["text"]
        self.assertIn("ana_souza", t)
        self.assertIn("campo personagem", t)
        self.assertIn("planejar_video", t)
        self.assertIn("página", t)
        self.assertIn("opcionais", t)
        self.assertEqual(self.pastas_de_personagens(), ["ana_souza"])
        self.assertTrue((self.raiz / "personagens" / "ana_souza" / "ficha.json").is_file())
        self.assertIn("ana_souza: Ana Souza · Original", chamar("listar_personagens")["content"][0]["text"])
        # A foto enviada continua como midia
        self.assertEqual(midias.tipo_de("ana.png"), "foto")

    def test_criar_personagem_manda_so_as_chaves_sem_gpu_e_com_autorizacao(self):
        self.foto_enviada()
        pedidos = []
        with mock.patch.object(acoes, "acao_personagem_criar", lambda d: pedidos.append(d) or {"id": "ana"}):
            r = chamar("criar_personagem", {"nome": "  Ana  ", "foto": "ana.png", "descricao": "Morena, de óculos"})
        self.assertFalse(r["isError"], r)
        self.assertEqual(pedidos, [{"nome": "Ana", "descricao": "Morena, de óculos", "foto": "ana.png", "autorizacao": True}])
        pedidos.clear()
        with mock.patch.object(acoes, "acao_personagem_criar", lambda d: pedidos.append(d) or {"id": "ana"}):
            chamar("criar_personagem", {"nome": "Ana", "foto": "ana.png"})
        self.assertEqual(pedidos, [{"nome": "Ana", "descricao": "", "foto": "ana.png", "autorizacao": True}])

    def test_criar_personagem_recusa_foto_que_nao_e_midia_de_foto(self):
        self.foto_enviada("voz.mp3", "audio", b"x")
        for foto in ("sumiu.png", "voz.mp3", "", None, 3):
            r = chamar("criar_personagem", {"nome": "Ana", "foto": foto})
            self.assertTrue(r["isError"], foto)
            self.assertIn("listar_midias", r["content"][0]["text"], foto)
        self.assertEqual(chamar("criar_personagem", {"nome": "Ana"})["isError"], True)
        self.assertEqual(self.pastas_de_personagens(), [])

    def test_criar_personagem_recusa_nome_vazio(self):
        self.foto_enviada()
        for nome in ("", "   ", None, 7):
            r = chamar("criar_personagem", {"nome": nome, "foto": "ana.png"})
            self.assertTrue(r["isError"], nome)
            self.assertIn("nome", r["content"][0]["text"])
        self.assertEqual(self.pastas_de_personagens(), [])

    def test_criar_personagem_recusa_descricao_que_nao_e_texto(self):
        self.foto_enviada()
        r = chamar("criar_personagem", {"nome": "Ana", "foto": "ana.png", "descricao": ["x"]})
        self.assertTrue(r["isError"])
        self.assertEqual(self.pastas_de_personagens(), [])

    def test_criar_personagem_com_foto_que_nao_abre_como_imagem_nao_deixa_pasta(self):
        self.foto_enviada("quebrada.png", "foto", b"isto nao e uma imagem")
        with mock.patch.object(acoes, "acao_personagem_criar") as a:
            r = chamar("criar_personagem", {"nome": "Ana", "foto": "quebrada.png"})
        self.assertTrue(r["isError"])
        self.assertIn("imagem", r["content"][0]["text"])
        self.assertIn("listar_midias", r["content"][0]["text"])
        a.assert_not_called()
        self.assertEqual(self.pastas_de_personagens(), [])

    def test_criar_personagem_traduz_os_erros_da_acao(self):
        self.foto_enviada()
        with mock.patch.object(acoes, "acao_personagem_criar", side_effect=ValueError("Dê um nome ao personagem.")):
            r = chamar("criar_personagem", {"nome": "Ana", "foto": "ana.png"})
        self.assertTrue(r["isError"])
        self.assertIn("Nada foi criado", r["content"][0]["text"])
        with mock.patch.object(acoes, "acao_personagem_criar", side_effect=Erro("A foto do personagem não foi encontrada. Envie de novo.", 404)):
            r = chamar("criar_personagem", {"nome": "Ana", "foto": "ana.png"})
        self.assertTrue(r["isError"])
        self.assertIn("A foto do personagem não foi encontrada", r["content"][0]["text"])
        self.assertIn("Nada foi criado", r["content"][0]["text"])

    def test_criar_personagem_repetido_nao_cria_duplicata(self):
        self.foto_enviada()
        chamar("criar_personagem", {"nome": "Ana", "foto": "ana.png"})
        for nome in ("Ana", "  ana ", "ANA"):
            r = chamar("criar_personagem", {"nome": nome, "foto": "ana.png"})
            self.assertFalse(r["isError"], r)
            t = r["content"][0]["text"]
            self.assertIn("Esse personagem já existia (id ana); nada novo foi criado.", t)
            self.assertIn("Use o id ana no campo personagem.", t)
        self.assertEqual(self.pastas_de_personagens(), ["ana"])

    def test_criar_personagem_com_o_mesmo_nome_e_outra_foto_cria_outro(self):
        self.foto_enviada()
        self.foto_enviada("ana2.png")
        chamar("criar_personagem", {"nome": "Ana", "foto": "ana.png"})
        t = chamar("criar_personagem", {"nome": "Ana", "foto": "ana2.png"})["content"][0]["text"]
        self.assertIn("ana_2", t)
        self.assertNotIn("já existia", t)
        self.assertEqual(self.pastas_de_personagens(), ["ana", "ana_2"])
        # Outro nome com a mesma foto tambem e outro personagem
        self.assertIn("bruno", chamar("criar_personagem", {"nome": "Bruno", "foto": "ana.png"})["content"][0]["text"])
        self.assertEqual(self.pastas_de_personagens(), ["ana", "ana_2", "bruno"])

    def test_criar_personagem_sem_foto_diz_o_que_falta(self):
        for args in ({"nome": "Ana"}, {"nome": "Ana", "foto": None}, {"nome": "Ana", "foto": ""}):
            r = chamar("criar_personagem", args)
            self.assertTrue(r["isError"], args)
            t = r["content"][0]["text"]
            self.assertIn("Falta a foto: mande o nome de uma mídia de listar_midias.", t)
            self.assertNotIn("None", t)
        self.assertEqual(self.pastas_de_personagens(), [])

    def test_lista_vazia_cita_criar_personagem(self):
        t = chamar("listar_personagens")["content"][0]["text"]
        self.assertIn("Nenhum personagem", t)
        self.assertIn("criar_personagem", t)

    def test_listar_personagens_mostra_pessoa_e_visual(self):
        for pid, ficha in (("mov", {"nome": "mov"}),
                           ("mov_biquini", {"nome": "mov (Biquíni)", "copia_de": "mov", "visual": "Biquíni"})):
            p = self.raiz / "personagens" / pid
            p.mkdir()
            (p / "ficha.json").write_text(json.dumps(ficha), encoding="utf-8")
            (p / "frente.png").write_bytes(b"png")
        t = chamar("listar_personagens")["content"][0]["text"]
        self.assertIn("mov: mov · Original", t)
        self.assertNotIn("mov: mov · Original (frente", t)
        self.assertIn("mov_biquini: mov · Biquíni (frente ainda não aprovada)", t)

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
        self.assertNotIn("p10", t)
        # O agente ve "vídeo" e "imagem", nunca o tipo interno: projeto de imagem e "texto" por dentro e o de vídeo de receita, "imagem"
        self.assertIn(": vídeo,", linhas[1])
        self.assertIn(": imagem,", linhas[0])
        self.assertNotIn("texto", t)

    def test_listar_projetos_traduz_cada_tipo_interno(self):
        tipos = {"texto": ": imagem,", "imagem": ": vídeo,", "wan": ": vídeo,", "troca": ": vídeo (troca),", "editar": ": vídeo (edição),", None: ": vídeo (continuação),"}
        lista = [{"nome": f"p{i}", "tipo": tipo, "quando": 1_800_000_000 - i, "final": None} for i, tipo in enumerate(tipos)]
        with mock.patch.object(projetos, "listar_projetos", lambda: lista):
            linhas = chamar("listar_projetos")["content"][0]["text"].splitlines()
        for linha, esperado in zip(linhas, tipos.values()):
            self.assertIn(esperado, linha)
        d = next(f for f in mcp_servidor.listar("operador") if f["name"] == "listar_projetos")["description"]
        self.assertIn("projetos de vídeo e de imagem", d)

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

    def test_ver_andamento_diz_quanto_falta_e_freia_a_consulta_repetida(self):
        # Um agente local consultou o andamento mais de 70 vezes em 5 minutos, uma a cada 4 s
        r = {"projeto": "mcp_livre_1", "rodando": True, "etapa": "tomada 1", "segundos": 200,
             "progresso": {"tomada": 1, "total": 1, "valor": 3, "maximo": 8, "s_passo": 60.0}}
        with mock.patch.object(tarefa.tarefa, "resumo", lambda: r), mock.patch.object(mcp_consultas, "_ultima_consulta", [float("-inf")]):
            primeira = chamar("ver_andamento")["content"][0]["text"]
            segunda = chamar("ver_andamento")["content"][0]["text"]
            mcp_consultas._ultima_consulta[0] -= mcp_consultas.INTERVALO_ANDAMENTO + 1
            terceira = chamar("ver_andamento")["content"][0]["text"]
        self.assertIn("faltam cerca de 5 min", primeira)
        self.assertIn("espere ele perguntar", primeira)
        self.assertNotIn("Pare de consultar", primeira)
        self.assertIn("Pare de consultar", segunda)
        self.assertIn("mcp_livre_1", segunda)
        self.assertNotIn("Pare de consultar", terceira)

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
        with mock.patch.object(mcp_consultas, "_ler_final", lambda v: chamados.append(v)):
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
        with mock.patch.object(mcp_consultas, "_ler_final", lambda v: (10.04, b"\x89PNG")):
            r = chamar("ver_resultado", {"projeto": "mcp_podcast_1"})
        self.assertFalse(r["isError"], r)
        t, img = r["content"]
        self.assertIn("10 s", t["text"])
        # A chave operador nao abre o /video/ (403): o texto traz o link temporario, nao a pagina
        self.assertNotIn("/video/", t["text"])
        self.assertNotIn("abra na página", t["text"])
        self.assertIn("/m/", t["text"])
        self.assertEqual((img["type"], img["data"]), ("image", "iVBORw=="))
        # Sem conseguir ler o quadro: so o texto
        with mock.patch.object(mcp_consultas, "_ler_final", lambda v: (None, None)):
            r = chamar("ver_resultado", {"projeto": "mcp_podcast_1"})
        self.assertFalse(r["isError"], r)
        self.assertEqual(len(r["content"]), 1)
        self.assertIn("/m/", r["content"][0]["text"])
        # A chave completa tambem recebe o link para baixar (nunca o /video/)
        with mock.patch.object(mcp_consultas, "_ler_final", lambda v: (10.04, b"\x89PNG")):
            r = chamar("ver_resultado", {"projeto": "mcp_podcast_1"}, nivel="completo")
        self.assertIn("/m/", r["content"][0]["text"])
        self.assertNotIn("/video/", r["content"][0]["text"])
        self.assertIsNone(mcp_servidor.nivel_atual())

    def test_ver_resultado_da_um_link_que_baixa_o_final(self):
        pasta = self.raiz / "projetos" / "mcp_podcast_1"
        pasta.mkdir()
        (pasta / "final.mp4").write_bytes(b"mp4")
        self.addCleanup(links._itens.clear)
        for nivel in ("operador", "completo"):
            with mock.patch.object(mcp_consultas, "_ler_final", lambda v: (10.04, None)):
                r = chamar("ver_resultado", {"projeto": "mcp_podcast_1"}, nivel=nivel, base="http://exemplo.test:8190")
            t = r["content"][0]["text"]
            self.assertIn("http://exemplo.test:8190/m/", t, nivel)
            self.assertIn("curl -o", t, nivel)
            self.assertIn("pelo menos 30 minutos", t, nivel)
            codigo = re.search(r"/m/([\w-]+)", t).group(1)
            self.assertEqual(links.ler(codigo)["arquivo"], pasta / "final.mp4", nivel)
            self.assertEqual(links.ler(codigo)["nome"], "mcp_podcast_1.mp4", nivel)
        self.assertEqual(mcp_servidor.base_atual(), f"http://127.0.0.1:{config.PORTA}")

    def projeto_de_imagem(self, nome="mcp_imagem_1", quantidade=2, prontas=(1, 2)):
        """Um projeto de texto para imagem como o job deixa: interface.json, estado.json e um PNG por imagem pronta."""
        from PIL import Image
        pasta = self.raiz / "projetos" / nome
        pasta.mkdir()
        (pasta / "interface.json").write_text(json.dumps({"tipo": "texto", "prompt": "um gato", "quantidade": quantidade}), encoding="utf-8")
        itens = []
        for n in prontas:
            Image.new("RGB", (1000, 500), (n * 40, 10, 10)).save(pasta / f"imagem_{n}.png")
            itens.append({"n": n, "arquivo": f"imagem_{n}.png", "semente": n, "segundos": 12})
        (pasta / "estado.json").write_text(json.dumps({"tipo": "texto", "imagens": itens}), encoding="utf-8")
        return pasta

    def test_ver_resultado_de_imagem_da_um_link_por_imagem(self):
        pasta = self.projeto_de_imagem()
        self.addCleanup(links._itens.clear)
        r = chamar("ver_resultado", {"projeto": "mcp_imagem_1"}, base="http://exemplo.test:8190")
        self.assertFalse(r["isError"], r)
        t, img = r["content"]
        self.assertEqual(img["type"], "image")
        self.assertEqual(img["mimeType"], "image/png")
        self.assertIn("2 imagens", t["text"])
        self.assertIn("exatamente como vieram", t["text"])
        achados = re.findall(r"Imagem (\d): http://exemplo\.test:8190/m/([\w-]+) \(vale pelo menos 30 minutos\)", t["text"])
        self.assertEqual([n for n, _ in achados], ["1", "2"])
        for n, codigo in achados:
            self.assertEqual(links.ler(codigo)["arquivo"], pasta / f"imagem_{n}.png")
            self.assertEqual(links.ler(codigo)["nome"], f"mcp_imagem_1_{n}.png")
        self.assertNotIn("final.mp4", t["text"])

    def tarefa_falsa(self, rodando=None, fila=()):
        """A tarefa do estudio trocada por um duble: `rodando` e o projeto em andamento (ou None) e `fila`, os nomes na fila."""
        t = mock.Mock()
        t.rodando.return_value = rodando is not None
        t.projeto = rodando
        t.fila.tem.side_effect = lambda p: p in fila
        p = mock.patch.object(tarefa, "tarefa", t)
        p.start()
        self.addCleanup(p.stop)
        return t

    def test_ver_resultado_de_imagem_em_andamento_diz_quantas_estao_prontas(self):
        self.projeto_de_imagem(quantidade=3, prontas=(1,))
        self.addCleanup(links._itens.clear)
        self.tarefa_falsa(rodando="mcp_imagem_1")
        r = chamar("ver_resultado", {"projeto": "mcp_imagem_1"})
        self.assertFalse(r["isError"], r)
        self.assertEqual(len(r["content"]), 1)
        t = r["content"][0]["text"]
        self.assertIn("1 de 3", t)
        self.assertIn("espere", t)
        self.assertNotIn("/m/", t)
        self.assertEqual(links._itens, {})
        # Nada pronto ainda, e esperando na fila: tambem e espera
        self.projeto_de_imagem("mcp_imagem_2", quantidade=2, prontas=())
        self.tarefa_falsa(rodando="outro", fila=("mcp_imagem_2",))
        self.assertIn("0 de 2", chamar("ver_resultado", {"projeto": "mcp_imagem_2"})["content"][0]["text"])

    def test_ver_resultado_de_imagem_parada_no_meio_entrega_as_prontas(self):
        pasta = self.projeto_de_imagem(quantidade=3, prontas=(1, 2))
        self.addCleanup(links._itens.clear)
        # Outro projeto rodando nao faz este continuar "gerando"
        self.tarefa_falsa(rodando="outro_projeto")
        r = chamar("ver_resultado", {"projeto": "mcp_imagem_1"}, base="http://exemplo.test:8190")
        self.assertFalse(r["isError"], r)
        t, img = r["content"]
        self.assertEqual(img["type"], "image")
        self.assertIn("A geração parou em 2 de 3 imagens. Continuar é pela página do estúdio.", t["text"])
        self.assertNotIn("espere", t["text"])
        achados = re.findall(r"Imagem (\d): http://exemplo\.test:8190/m/([\w-]+) \(vale pelo menos 30 minutos\)", t["text"])
        self.assertEqual([n for n, _ in achados], ["1", "2"])
        for n, codigo in achados:
            self.assertEqual(links.ler(codigo)["arquivo"], pasta / f"imagem_{n}.png")

    def test_ver_resultado_de_imagem_parada_sem_nenhuma_pronta(self):
        self.projeto_de_imagem(quantidade=2, prontas=())
        self.addCleanup(links._itens.clear)
        self.tarefa_falsa()
        r = chamar("ver_resultado", {"projeto": "mcp_imagem_1"})
        self.assertFalse(r["isError"], r)
        self.assertEqual(r["content"], [{"type": "text", "text": "A geração parou sem nenhuma imagem pronta. Planeje de novo ou veja na página do estúdio."}])
        self.assertEqual(links._itens, {})

    def test_listar_projetos_mostra_pronto_no_projeto_de_imagem_completo(self):
        self.projeto_de_imagem("mcp_imagem_pronto", quantidade=2, prontas=(1, 2))
        self.projeto_de_imagem("mcp_imagem_andando", quantidade=2, prontas=(1,))
        linhas = {x.split(":")[0]: x for x in chamar("listar_projetos")["content"][0]["text"].splitlines() if x.startswith("mcp_imagem")}
        self.assertIn("pronto", linhas["mcp_imagem_pronto"])
        self.assertNotIn("incompleto", linhas["mcp_imagem_pronto"])
        self.assertIn("incompleto", linhas["mcp_imagem_andando"])

    def test_usar_resultado_de_imagem_copia_e_registra_como_foto(self):
        pasta = self.projeto_de_imagem()
        antes = (pasta / "imagem_2.png").read_bytes()
        r = chamar("usar_resultado", {"projeto": "mcp_imagem_1", "imagem": 2})
        self.assertFalse(r["isError"], r)
        t = r["content"][0]["text"]
        self.assertIn("mcp_imagem_1_2.png", t)
        # A foto serve na imagem e no video de receita; o video gerado e que so serve de referencia no modo livre
        self.assertIn("planejar_imagem e planejar_video", t)
        copia = self.raiz / "entrada" / "estudio" / "envios" / "mcp_imagem_1_2.png"
        self.assertEqual(copia.read_bytes(), antes)
        self.assertEqual(midias.tipo_de("mcp_imagem_1_2.png"), "foto")
        registro = midias.listar("foto")
        self.assertEqual([(m["nome"], m["origem"], m["largura"], m["altura"]) for m in registro], [("mcp_imagem_1_2.png", "mcp", 1000, 500)])
        # O original fica no projeto, e a primeira imagem e o padrao
        self.assertEqual((pasta / "imagem_2.png").read_bytes(), antes)
        self.assertTrue((pasta / "imagem_1.png").is_file())
        chamar("usar_resultado", {"projeto": "mcp_imagem_1"})
        self.assertTrue((self.raiz / "entrada" / "estudio" / "envios" / "mcp_imagem_1_1.png").is_file())
        # De novo: o mesmo nome, sem copia a mais
        chamar("usar_resultado", {"projeto": "mcp_imagem_1", "imagem": 2})
        self.assertEqual(sorted(p.name for p in (self.raiz / "entrada" / "estudio" / "envios").iterdir()), ["mcp_imagem_1_1.png", "mcp_imagem_1_2.png"])

    def test_usar_resultado_de_imagem_que_nao_existe_ou_nao_ficou_pronta(self):
        self.projeto_de_imagem(quantidade=3, prontas=(1,))
        self.tarefa_falsa(rodando="mcp_imagem_1")
        r = chamar("usar_resultado", {"projeto": "mcp_imagem_1", "imagem": 2})
        self.assertTrue(r["isError"])
        self.assertIn("ver_andamento", r["content"][0]["text"])
        self.assertIn("Nada foi copiado", r["content"][0]["text"])
        self.projeto_de_imagem("mcp_imagem_2", quantidade=1, prontas=(1,))
        r = chamar("usar_resultado", {"projeto": "mcp_imagem_2", "imagem": 3})
        self.assertTrue(r["isError"])
        self.assertIn("tem: 1", r["content"][0]["text"])
        for imagem in (0, "a", True):
            self.assertTrue(chamar("usar_resultado", {"projeto": "mcp_imagem_2", "imagem": imagem})["isError"], imagem)
        self.assertEqual(list((self.raiz / "entrada").iterdir()), [])
        self.assertEqual(midias.listar(), [])

    def test_usar_resultado_aceita_imagem_pronta_de_projeto_parado(self):
        self.projeto_de_imagem(quantidade=3, prontas=(1,))
        self.tarefa_falsa()
        r = chamar("usar_resultado", {"projeto": "mcp_imagem_1", "imagem": 1})
        self.assertFalse(r["isError"], r)
        self.assertTrue((self.raiz / "entrada" / "estudio" / "envios" / "mcp_imagem_1_1.png").is_file())
        # A que nao ficou pronta nao vem mais: a geracao parou, entao esperar nao adianta
        r = chamar("usar_resultado", {"projeto": "mcp_imagem_1", "imagem": 2})
        self.assertTrue(r["isError"])
        t = r["content"][0]["text"]
        self.assertIn("parou", t)
        self.assertIn("Nada foi copiado", t)
        self.assertNotIn("ver_andamento", t)
        self.assertIn("tem: 1", t)

    def test_usar_resultado_de_video_copia_para_os_envios_como_video(self):
        pasta = self.raiz / "projetos" / "mcp_podcast_1"
        pasta.mkdir()
        (pasta / "final.mp4").write_bytes(b"mp4 de mentira")
        info = {"quadros": 240, "fps": 24.0, "largura": 540, "altura": 960, "audio": True, "duracao": 10.0}
        with mock.patch.object(envio, "examinar_video", lambda v: info):
            r = chamar("usar_resultado", {"projeto": "mcp_podcast_1"})
            self.assertFalse(r["isError"], r)
            self.assertIn("mcp_podcast_1.mp4", r["content"][0]["text"])
            self.assertIn("planejar_video_livre", r["content"][0]["text"])
            copia = self.raiz / "envios" / "mcp_podcast_1.mp4"
            self.assertEqual(copia.read_bytes(), b"mp4 de mentira")
            self.assertEqual(midias.tipo_de("mcp_podcast_1.mp4"), "video")
            m = midias.listar("video")[0]
            self.assertEqual((m["nome"], m["origem"], m["duracao"], m["largura"]), ("mcp_podcast_1.mp4", "mcp", 10.0, 540))
            # O original continua no projeto; de novo: nada a mais
            self.assertEqual((pasta / "final.mp4").read_bytes(), b"mp4 de mentira")
            chamar("usar_resultado", {"projeto": "mcp_podcast_1"})
        self.assertEqual([p.name for p in (self.raiz / "envios").iterdir()], ["mcp_podcast_1.mp4"])

    def test_usar_resultado_sem_resultado_ou_projeto_desconhecido(self):
        (self.raiz / "projetos" / "mcp_podcast_2").mkdir()
        r = chamar("usar_resultado", {"projeto": "mcp_podcast_2"})
        self.assertTrue(r["isError"])
        self.assertIn("ver_andamento", r["content"][0]["text"])
        for args in ({"projeto": "nao_existe"}, {"projeto": "../fora"}, {}):
            r = chamar("usar_resultado", args)
            self.assertTrue(r["isError"], args)
        self.assertIn("listar_projetos", chamar("usar_resultado", {"projeto": "nao_existe"})["content"][0]["text"])
        self.assertEqual(midias.listar(), [])

    def test_pedir_envio_da_um_link_que_recebe_o_arquivo(self):
        self.addCleanup(links._itens.clear)
        for nivel in ("operador", "completo"):
            for tipo, limite in (("foto", "30 MB"), ("audio", "50 MB"), ("video", "200 MB")):
                r = chamar("pedir_envio", {"tipo": tipo}, nivel=nivel, base="http://exemplo.test:8190")
                self.assertFalse(r["isError"], r)
                t = r["content"][0]["text"]
                codigo = re.search(r"http://exemplo\.test:8190/m/([\w-]+)", t).group(1)
                self.assertIn(f'curl -T <arquivo> "http://exemplo.test:8190/m/{codigo}/"', t)
                self.assertIn("navegador", t)
                self.assertIn("1 hora", t)
                self.assertIn(limite, t)
                self.assertIn("listar_midias", t)
                self.assertNotIn("{", t)
                self.assertEqual((links.ler(codigo)["acao"], links.ler(codigo)["tipo"]), ("enviar", tipo))

    def test_pedir_envio_recusa_tipo_ruim(self):
        links._itens.clear()
        self.addCleanup(links._itens.clear)
        for args in ({"tipo": "documento"}, {"tipo": ""}, {}):
            r = chamar("pedir_envio", args)
            self.assertTrue(r["isError"], args)
            self.assertIn("foto, audio ou video", r["content"][0]["text"])
        self.assertEqual(links._itens, {})

    def test_listar_midias_sem_nada(self):
        self.assertEqual(chamar("listar_midias")["content"][0]["text"], "Nenhuma mídia enviada ainda. Chame pedir_envio.")
        self.assertEqual(chamar("listar_midias", {"tipo": "foto"})["content"][0]["text"], "Nenhuma mídia do tipo foto enviada ainda. Chame pedir_envio.")

    def test_listar_midias_uma_por_linha_com_as_medidas(self):
        agora = 1_000_000.0
        casos = [("ana.png", "foto", agora - 120, {"largura": 1024, "altura": 1536}),
                 ("voz.mp3", "audio", agora - 30, {"duracao": 14.8}),
                 ("clipe.mp4", "video", agora - 7200, {"duracao": 8.0, "largura": 1280, "altura": 720, "quadros": 192})]
        for nome, tipo, quando, info in casos:
            (config.ENVIOS if tipo == "video" else config.ENTRADA).joinpath(nome).write_bytes(b"x")
            with mock.patch.object(midias.time, "time", return_value=quando):
                midias.registrar(nome, tipo, "link", info)
        with mock.patch.object(mcp_midias.time, "time", return_value=agora):
            t = chamar("listar_midias")["content"][0]["text"]
            so_video = chamar("listar_midias", {"tipo": "video"})["content"][0]["text"]
        self.assertEqual(t.splitlines(), ["voz.mp3 (áudio 14,8 s, enviada há 30 s)",
                                          "ana.png (foto 1024x1536, enviada há 2 min)",
                                          "clipe.mp4 (vídeo 8 s, 1280x720, enviada há 2 h)"])
        self.assertEqual(so_video, "clipe.mp4 (vídeo 8 s, 1280x720, enviada há 2 h)")
        self.assertTrue(chamar("listar_midias", {"tipo": "documento"})["isError"])

    def test_importar_url_devolve_o_nome_e_as_medidas(self):
        r = {"arquivo": "ana.png", "largura": 1024, "altura": 1536}
        with mock.patch.object(mcp_midias.importar, "baixar", return_value=r) as b:
            t = chamar("importar_url", {"url": "https://exemplo.test/ana.png", "tipo": "foto"})
        b.assert_called_once_with("https://exemplo.test/ana.png", "foto")
        self.assertFalse(t["isError"], t)
        self.assertEqual(t["content"][0]["text"].splitlines()[0], "Importei ana.png (foto 1024x1536). Use esse nome nas ferramentas; chame listar_midias para ver as mídias do estúdio.")
        self.assertNotIn("{", t["content"][0]["text"])

    def test_importar_url_recusa_rede_interna_com_mensagem(self):
        r = chamar("importar_url", {"url": "http://127.0.0.1:9/a.png", "tipo": "foto"})
        self.assertTrue(r["isError"])
        self.assertIn("rede interna", r["content"][0]["text"])
        r = chamar("importar_url", {"url": "https://exemplo.test/a.png", "tipo": "documento"})
        self.assertTrue(r["isError"])
        self.assertIn("foto, audio ou video", r["content"][0]["text"])

    def test_ler_final_le_a_duracao_do_ffmpeg(self):
        saida = "Input #0, mov,mp4\n  Duration: 00:00:10.04, start: 0.000000, bitrate: 900 kb/s\n"

        def rodar(cmd, **k):
            Path(cmd[-1]).write_bytes(b"\x89PNG")
            return mock.Mock(returncode=0, stderr=saida.encode())
        with mock.patch.object(mcp_consultas.subprocess, "run", rodar):
            self.assertEqual(mcp_consultas._ler_final(self.raiz / "final.mp4"), (10.04, b"\x89PNG"))

        def falha(cmd, **k):
            raise OSError("sem ffmpeg")
        with mock.patch.object(mcp_consultas.subprocess, "run", falha):
            self.assertEqual(mcp_consultas._ler_final(self.raiz / "final.mp4"), (None, None))

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

    def test_instrucoes_do_operador_citam_as_ferramentas_de_midia(self):
        t = mcp_servidor.INSTRUCOES.read_text(encoding="utf-8")
        for nome in ("pedir_envio", "listar_midias", "importar_url", "regras_do_modo_livre", "planejar_video_livre",
                     "planejar_imagem", "usar_resultado", "criar_personagem"):
            self.assertIn(nome, t)
        # a fase de imagem: aprovar antes de confirmar, o tempo vem do resumo, imagem gerada so vira midia por usar_resultado
        for parte in ("Tempo estimado", "image 1", "image 2", "só vale depois de usar_resultado"):
            self.assertIn(parte, t)
        for parte in ("audio_fala", "cenario", "resolucao", "curl", "ver_resultado"):
            self.assertIn(parte, t)
        self.assertNotIn("também é pela página", t)
        # As fotos da imagem vao num campo com nome: um modelo local mandou "foto" e o plano saiu de outra coisa
        self.assertIn("campo imagens", t)
        # O "faltam cerca de N min" do ver_andamento e do estudio: a regra nao pode proibir esse numero
        self.assertNotIn("nunca diga outro número de tempo", t)
        self.assertIn("nunca invente um tempo", t)
        # Um modelo local inventou um link de envio e pediu permissao para planejar: as duas regras ficam escritas
        self.assertIn("Nunca escreva um link por conta própria", t)
        self.assertIn("Não peça permissão para planejar", t)
        self.assertLessEqual(len(t.strip().splitlines()), 50)
        completo = mcp_servidor.INSTRUCOES.with_name("instrucoes_completo.md").read_text(encoding="utf-8")
        for nome in ("pedir_envio", "importar_url", "enviar_arquivo"):
            self.assertIn(nome, completo)

    def test_instrucoes_so_mandam_argumentos_que_a_ferramenta_aceita(self):
        esquemas = {f["name"]: f["inputSchema"]["properties"] for f in mcp_servidor.listar("operador")}
        # (ferramenta, argumento, aceita) para o que as instrucoes dizem de cada ferramenta
        tabela = [("planejar_video", "foto", True), ("planejar_video", "audio_fala", True), ("planejar_video", "cenario", True),
                  ("planejar_video", "resolucao", True), ("regras_das_tomadas", "audio_fala", True),
                  ("regras_das_tomadas", "resolucao", True), ("regras_das_tomadas", "foto", False),
                  ("planejar_imagem", "prompt", True), ("planejar_imagem", "imagens", True), ("planejar_imagem", "formato", True),
                  ("planejar_imagem", "quantidade", True), ("usar_resultado", "projeto", True), ("usar_resultado", "imagem", True),
                  ("criar_personagem", "nome", True), ("criar_personagem", "foto", True), ("criar_personagem", "descricao", True)]
        for ferramenta, arg, aceita in tabela:
            self.assertEqual(arg in esquemas[ferramenta], aceita, (ferramenta, arg))
        for arquivo in ("instrucoes_operador.md", "instrucoes_completo.md"):
            t = mcp_servidor.INSTRUCOES.with_name(arquivo).read_text(encoding="utf-8")
            self.assertNotIn("e em regras_das_tomadas, mande foto", t)

    def test_ver_resultado_repetido_nao_enche_os_links_nem_derruba_um_de_envio(self):
        self.projeto_de_imagem(quantidade=4, prontas=(1, 2, 3, 4))
        links.recarregar()
        self.addCleanup(links.recarregar)
        envio_pendente = links.criar_enviar("foto")
        r = chamar("ver_resultado", {"projeto": "mcp_imagem_1"}, base="http://exemplo.test:8190")
        primeiros = re.findall(r"/m/([\w-]+)", r["content"][0]["text"])
        self.assertEqual(len(primeiros), 4)
        depois = len(links._itens)
        for _ in range(60):
            t = chamar("ver_resultado", {"projeto": "mcp_imagem_1"}, base="http://exemplo.test:8190")["content"][0]["text"]
            self.assertEqual(re.findall(r"/m/([\w-]+)", t), primeiros)
        self.assertEqual(len(links._itens), depois)
        self.assertEqual(links.ler(envio_pendente)["acao"], "enviar")
        for codigo in primeiros:
            self.assertEqual(links.ler(codigo)["acao"], "baixar")

    def test_descricoes_nao_se_contradizem_sobre_criar_personagem_e_usar_resultado(self):
        d = {f["name"]: f["description"] for f in mcp_servidor.listar("operador")}
        # O criar_personagem manda usar o pedir_envio: o pedir_envio nao pode dizer que nao serve para isso
        self.assertNotIn("criar personagens", d["pedir_envio"])
        self.assertNotIn("menu Personagem", d["pedir_envio"])
        # A foto serve na imagem e no video de receita; o video gerado so serve de referencia no modo livre
        self.assertIn("planejar_imagem e planejar_video", d["usar_resultado"])
        self.assertIn("só em planejar_video_livre", d["usar_resultado"])
        t = mcp_servidor.INSTRUCOES.read_text(encoding="utf-8")
        self.assertIn("só vale depois de usar_resultado", t)
        self.assertRegex(t, r"vídeo gerado[^\n]*planejar_video_livre")

    def test_a_lista_de_ferramentas_do_operador_nao_passa_de_20500_caracteres(self):
        # O modelo local le tudo isto a cada conversa: cada acrescimo de texto tem de ser pago com um corte
        tamanho = len(json.dumps(mcp_servidor.listar("operador"), ensure_ascii=False))
        self.assertLess(tamanho, 20500)

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
        for alvo, valor in ((midias, "midias.json"), (planos, "planos.json"), (links, "links.json")):
            antigo = alvo.ARQUIVO
            alvo.ARQUIVO = self.raiz / valor
            self.addCleanup(setattr, alvo, "ARQUIVO", antigo)

    def porta_livre(self):
        with socket.socket() as t:
            t.bind(("127.0.0.1", 0))
            return t.getsockname()[1]

    def apontar(self, porta):
        antigo = mcp_completo.PORTA_API
        mcp_completo.PORTA_API = porta
        self.addCleanup(setattr, mcp_completo, "PORTA_API", antigo)

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
            codigo, corpo = mcp_completo._postar(rota, {})
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
        self.assertEqual((entrada.pasta_envios() / "pequena.png").read_bytes(), PNG)
        self.assertIn("pequena.png", r["content"][0]["text"])
        (m,) = midias.listar()
        self.assertEqual((m["nome"], m["tipo"], m["origem"]), ("pequena.png", "foto", "mcp"))

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
        self.assertEqual(mcp_completo.LIMITE_ARQUIVO, 20 * 1024 * 1024)
        with mock.patch.object(mcp_completo, "LIMITE_ARQUIVO", 10):
            r = chamar("enviar_arquivo", {"tipo": "foto", "nome": "grande.png", "conteudo_base64": base64.b64encode(b"x" * 11).decode()}, nivel="completo")
        self.assertTrue(r["isError"])
        self.assertIn("pedir_envio", r["content"][0]["text"])
        self.assertIn("importar_url", r["content"][0]["text"])

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
