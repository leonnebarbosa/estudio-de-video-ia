"""Testes das receitas, das regras das tomadas, do planejar_video e do confirmar_plano (planos.py e mcp_ferramentas.py).
Quem escreve as tomadas e o agente (cliente MCP): aqui elas vem prontas. O ComfyUI nao e chamado: acoes.acao_iniciar_imagem
e trocado por um duble. Uso: python -I estudio/rodar_testes.py (ou python -I testar_planos.py)"""
import json, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
import acoes, continuar_video, mcp_servidor, mcp_ferramentas, personagens, planos, tarefa, validacao  # noqa: F401
from erros import Erro
from imagem_para_video import CAMERAS, DURACOES, duracao_maxima

TOMADA = {"acao": "The character smiles and talks to the camera", "fala": "A internet chegou!", "som": "", "camera": "aproximar", "duracao": 5}
CENA = "Realistic live-action commercial look, a bright modern living room, natural daylight"
TOMADA_CENA = {"acao": "A router on a shelf blinks its green lights", "fala": "", "som": "soft room tone", "camera": "aproximar", "duracao": 5}
SUFIXO = "Chame regras_das_tomadas para ver os limites desta receita."


def rpc(nome, argumentos, nivel="operador"):
    corpo = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": nome, "arguments": argumentos}}).encode()
    return mcp_servidor.atender(corpo, nivel)[1]["result"]


def exemplo_do_texto(t):
    """O JSON de exemplo que regras_das_tomadas devolve (a lista JSON depois de "Exemplo de tomadas")."""
    inicio = t.index("[", t.index("Exemplo de tomadas"))
    return json.loads(t[inicio:t.rindex("]") + 1])


class Base(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.raiz = Path(d.name)
        for nome in ("projetos", "entrada", "personagens"):
            (self.raiz / nome).mkdir()
        for alvo, nome, valor in ((config, "PROJETOS", self.raiz / "projetos"), (config, "ENTRADA", self.raiz / "entrada"),
                                  (personagens, "PASTA", self.raiz / "personagens"),
                                  # A pele natural das receitas com imagem pede arquivos no ComfyUI: aqui eles "estao la"
                                  (validacao, "faltam_pele", lambda: [])):
            antigo = getattr(alvo, nome)
            setattr(alvo, nome, valor)
            self.addCleanup(setattr, alvo, nome, antigo)
        self.addCleanup(planos.planos._itens.clear)

    def personagem(self, pid="ana", nome="Ana"):
        p = self.raiz / "personagens" / pid
        p.mkdir()
        (p / "ficha.json").write_text(json.dumps({"nome": nome}), encoding="utf-8")
        (p / "frente.png").write_bytes(b"png")


class Receitas(unittest.TestCase):
    def test_as_quatro_receitas_com_ajustes_conhecidos(self):
        r = planos.receitas()
        self.assertEqual(set(r), {"fala_camera", "podcast", "anuncio_vertical", "cena_texto"})
        for rid, x in r.items():
            self.assertEqual(set(x) - {"lugar", "cortes"}, {"nome", "uso", "com_imagem", "ajustes", "instrucao"}, rid)
            # Os cortes vem do campo, e a instrucao diz o mesmo em prosa
            self.assertEqual(x.get("cortes") is True, "corte a cada 2 a 3 s" in x["instrucao"], rid)
            self.assertLessEqual(len(x.get("lugar", "")), validacao.MAX_CENA, rid)
            self.assertLessEqual(set(x["ajustes"]), set(validacao.PADRAO_IMAGEM), rid)
            self.assertEqual(x["ajustes"]["modelo"], "h3", rid)
            # Decisao do usuario (21/11): a qualidade do UGC aprovado, 1,1 MP, e a pele natural onde ha imagem
            self.assertEqual(x["ajustes"]["megapixels"], 1.1, rid)
            self.assertIs(x["ajustes"]["pele"], x["com_imagem"], rid)
            # Um video de 15 s cabe em ate MAX_TOMADAS tomadas dentro dos limites desta resolucao
            mp = x["ajustes"]["megapixels"]
            self.assertGreaterEqual(duracao_maxima(mp) + (validacao.MAX_TOMADAS - 1) * duracao_maxima(mp, primeira=False), 15, rid)
            self.assertTrue(x["instrucao"].strip(), rid)
        self.assertFalse(r["cena_texto"]["com_imagem"])
        self.assertTrue(all(r[k]["com_imagem"] for k in ("fala_camera", "podcast", "anuncio_vertical")))

    def test_regras_fixas_existem(self):
        self.assertEqual(planos.REGRAS.name, "regras_tomadas.md")
        t = planos.REGRAS.read_text(encoding="utf-8")
        self.assertIn("inglês", t)
        self.assertIn("acao", t)


class ChamarLlm(unittest.TestCase):
    """As perguntas de visao vao direto ao Qwen local, num grafo so."""

    def test_chamar_llm_vai_direto_ao_qwen_local(self):
        rodados = []

        def rodar(g, tempo):
            rodados.append(g)
            return {"status": "success", "saidas": {}}
        with mock.patch.object(continuar_video, "rodar", rodar), mock.patch.object(continuar_video, "texto_llm", lambda r: "local"):
            r, t = continuar_video.chamar_llm("descreva", "a.png", "plano", type("M", (), {"rotulo": None})())
        self.assertEqual((r["status"], t), ("success", "local"))
        self.assertEqual(len(rodados), 1)


class Regras(unittest.TestCase):
    def regras(self, receita, qualidade=None):
        args = {"receita": receita} if qualidade is None else {"receita": receita, "qualidade": qualidade}
        r = rpc("regras_das_tomadas", args)
        self.assertFalse(r["isError"], r)
        return r["content"][0]["text"]

    def test_fala_camera_ugc_traz_os_limites_de_1_1_mp(self):
        t = self.regras("fala_camera", "ugc")
        self.assertIn("1,1 MP", t)
        self.assertIn("tomada 1 até 8 s", t)
        self.assertIn("tomadas 2 em diante até 5 s", t)
        for c in CAMERAS:
            self.assertIn(c, t)
        self.assertIn(f"{validacao.MAX_TOMADAS} tomadas", t)
        self.assertIn(planos.receitas()["fala_camera"]["instrucao"], t)
        self.assertIn(planos.REGRAS.read_text(encoding="utf-8").strip()[:80], t)
        # 10 s passa do limite a 1,1 MP: nao aparece entre as duracoes aceitas
        self.assertIn("tomada 1: 3, 3,5, 4,25, 5, 6, 7, 8;", t)

    def test_exemplo_passa_na_validacao_de_cada_receita_e_qualidade(self):
        for rid, receita in planos.receitas().items():
            for q in planos.QUALIDADES:
                t = self.regras(rid, q)
                tomadas = exemplo_do_texto(t)
                mp = planos.com_qualidade(receita, q)["ajustes"]["megapixels"]
                v = validacao.validar_tomadas(tomadas, DURACOES, True)
                validacao.validar_duracoes_h3(v, mp)
                self.assertGreaterEqual(len(v), 2, (rid, q))
                if planos.com_cortes(receita):
                    # Receitas com corte a cada 2 a 3 s: o exemplo segue os cortes (o modelo copia o JSON mais que a prosa)
                    self.assertTrue(all(x["duracao"] <= planos.CORTE_MAX for x in v), (rid, q, v))
                    self.assertGreaterEqual(len(v), 3, (rid, q))
                else:
                    # Sem cortes (cena_texto): o exemplo mostra os dois limites, a tomada 1 longa e as seguintes no maximo
                    self.assertEqual(v[0]["duracao"], duracao_maxima(mp), (rid, q))
                    self.assertTrue(all(x["duracao"] == duracao_maxima(mp, primeira=False) for x in v[1:]), (rid, q))
                self.assertNotIn("siga os cortes", t)
        self.assertEqual({rid for rid, r in planos.receitas().items() if planos.com_cortes(r)}, {"fala_camera", "podcast", "anuncio_vertical"})

    def test_rapido_traz_os_limites_de_0_47_mp(self):
        t = self.regras("fala_camera", "rapido")
        self.assertIn("0,4746 MP", t)
        self.assertIn(f"tomada 1 até {planos._br(duracao_maxima(0.4746))} s", t)
        self.assertIn(f"tomadas 2 em diante até {planos._br(duracao_maxima(0.4746, primeira=False))} s", t)

    def test_qualidade_padrao_e_ugc(self):
        self.assertIn("1,1 MP", self.regras("podcast"))

    def test_cena_texto_diz_que_a_cena_e_obrigatoria(self):
        t = self.regras("cena_texto")
        self.assertIn("Cena: obrigatória", t)
        self.assertIn("inglês", t)
        self.assertNotIn("Cena: obrigatória", self.regras("fala_camera"))

    def test_cena_com_imagem_e_onde_acontece(self):
        lugar = planos.receitas()["podcast"]["lugar"]
        t = self.regras("podcast", "ugc")
        self.assertIn("Cena (opcional): onde acontece", t)
        self.assertIn(lugar, t)
        t = self.regras("fala_camera", "ugc")
        self.assertIn("Cena (opcional): onde acontece", t)
        self.assertIn("o padrão do estúdio (um cômodo claro)", t)
        # Sem a pele natural (rapido) a cena com imagem nao entra no prompt
        self.assertIn("Cena: não mande", self.regras("podcast", "rapido"))

    def test_receita_ou_qualidade_desconhecida(self):
        for args in ({"receita": "nao"}, {"receita": "podcast", "qualidade": "4k"}):
            r = rpc("regras_das_tomadas", args)
            self.assertTrue(r["isError"], args)


class Planos(unittest.TestCase):
    def test_plano_expira_e_nao_confirma_duas_vezes(self):
        p = planos.Planos(); c = p.criar({"x": 1}, "r")
        self.assertEqual(len(c), 6)
        self.assertEqual(p.usar(c), {"x": 1})
        with self.assertRaisesRegex(Erro, "já foi confirmado"): p.usar(c)
        c2 = p.criar({}, "r"); p._itens[c2]["criado"] -= planos.VALIDADE + 1
        with self.assertRaisesRegex(Erro, "expirou"): p.usar(c2)
        with self.assertRaises(Erro): p.usar("naoexiste")

    def test_resumo_uma_linha_geral_e_uma_por_tomada(self):
        pedido = {"projeto": "x", "foto": None, "ajustes": {"proporcao": "9:16 (Portrait Widescreen)", "cena": "",
                  "tomadas": [{"camera": "aproximar", "duracao": 3.5, "fala": "Oi, gente!", "acao": "waves"},
                              {"camera": "afastar", "duracao": 3, "fala": "", "acao": "The character smiles"}]}}
        linhas = planos.resumo(pedido).splitlines()
        self.assertIn("vídeo 9:16", linhas[0])
        self.assertIn("6,5 s", linhas[0])
        self.assertIn("2 tomadas", linhas[0])
        self.assertEqual(linhas[1], "1) 3,5 s, câmera aproximar: Oi, gente!")
        self.assertTrue(linhas[2].startswith("2) 3 s, câmera afastar:"))
        self.assertIn("The character smiles", linhas[2])


class Ferramentas(Base):
    def test_listadas_para_os_dois_niveis(self):
        for nivel in ("operador", "completo"):
            nomes = {f["name"] for f in mcp_servidor.listar(nivel)}
            self.assertLessEqual({"listar_receitas", "regras_das_tomadas", "planejar_video", "confirmar_plano"}, nomes, nivel)

    def test_esquema_das_tomadas_da_a_estrutura(self):
        esquema = next(f for f in mcp_servidor.listar("operador") if f["name"] == "planejar_video")["inputSchema"]
        p = esquema["properties"]
        self.assertNotIn("texto", p)
        self.assertNotIn("duracao", p)
        self.assertIn("tomadas", esquema["required"])
        t = p["tomadas"]
        self.assertEqual((t["type"], t["minItems"], t["maxItems"]), ("array", 1, validacao.MAX_TOMADAS))
        item = t["items"]
        self.assertEqual(item["properties"]["camera"]["enum"], list(CAMERAS))
        self.assertEqual(item["properties"]["duracao"]["enum"], list(DURACOES))
        self.assertLessEqual({"acao", "fala", "camera", "duracao"}, set(item["required"]))
        self.assertIn("cena", p)
        self.assertEqual(p["cena"]["maxLength"], validacao.MAX_CENA)
        r = next(f for f in mcp_servidor.listar("operador") if f["name"] == "regras_das_tomadas")["inputSchema"]
        self.assertEqual(r["properties"]["receita"]["enum"], list(planos.receitas()))
        self.assertEqual((r["properties"]["qualidade"]["enum"], r["properties"]["qualidade"]["default"]), (["ugc", "rapido"], "ugc"))

    def test_listar_receitas(self):
        r = rpc("listar_receitas", {})
        self.assertFalse(r["isError"])
        t = r["content"][0]["text"]
        for rid in ("fala_camera", "podcast", "anuncio_vertical", "cena_texto"):
            self.assertIn(rid, t)
        # A duracao sai das tomadas, nao de uma lista fixa por receita
        self.assertNotIn("Durações:", t)
        self.assertEqual(t.splitlines()[-1], "Duração: a soma das tomadas (veja regras_das_tomadas).")

    def test_planejar_nao_cria_projeto_e_confirmar_inicia(self):
        r = rpc("planejar_video", {"receita": "cena_texto", "formato": "16:9", "qualidade": "ugc", "cena": CENA, "tomadas": [TOMADA_CENA]})
        self.assertFalse(r["isError"], r)
        texto = r["content"][0]["text"]
        codigo = next(c for c in planos.planos._itens)
        self.assertIn(codigo, texto)
        self.assertIn("1) 5 s, câmera aproximar", texto)
        self.assertEqual(list((self.raiz / "projetos").iterdir()), [])
        iniciados = []
        with mock.patch.object(acoes, "acao_iniciar_imagem", iniciados.append):
            r = rpc("confirmar_plano", {"codigo_plano": codigo})
        self.assertFalse(r["isError"], r)
        self.assertEqual(len(iniciados), 1)
        d = iniciados[0]
        self.assertIs(d["autorizacao"], True)
        # O sufixo de 4 hexadecimais evita repetir o nome no mesmo segundo
        self.assertRegex(d["projeto"], r"^mcp_cena_texto_\d{8}_\d{6}_[0-9a-f]{4}$")
        self.assertIsNone(d["foto"])
        self.assertEqual(d["ajustes"]["proporcao"], "16:9 (Widescreen)")
        self.assertEqual(d["ajustes"]["cena"], CENA)
        self.assertEqual(r["content"][0]["text"], f"Começou: {d['projeto']}")
        # Confirmar de novo nao inicia outra vez
        with mock.patch.object(acoes, "acao_iniciar_imagem", iniciados.append):
            r = rpc("confirmar_plano", {"codigo_plano": codigo})
        self.assertTrue(r["isError"])
        self.assertIn("já foi confirmado", r["content"][0]["text"])
        self.assertEqual(len(iniciados), 1)

    def test_confirmar_que_falha_devolve_o_plano(self):
        rpc("planejar_video", {"receita": "cena_texto", "formato": "16:9", "qualidade": "ugc", "cena": CENA, "tomadas": [TOMADA_CENA]})
        codigo = next(c for c in planos.planos._itens)

        def desligado(d):
            raise Erro("O ComfyUI está desligado. Esperando o ComfyUI ficar pronto.", 409)
        with mock.patch.object(acoes, "acao_iniciar_imagem", desligado):
            r = rpc("confirmar_plano", {"codigo_plano": codigo})
        self.assertTrue(r["isError"])
        self.assertIn("desligado", r["content"][0]["text"])
        iniciados = []
        with mock.patch.object(acoes, "acao_iniciar_imagem", iniciados.append):
            self.assertFalse(rpc("confirmar_plano", {"codigo_plano": codigo})["isError"])
        self.assertEqual(len(iniciados), 1)

    def test_planejar_com_personagem(self):
        self.personagem()
        tomadas = [dict(TOMADA, duracao=8), dict(TOMADA, fala="Agora é só aproveitar.", camera="acompanhar", duracao=5)]
        r = rpc("planejar_video", {"receita": "anuncio_vertical", "personagem": "Ana", "formato": "9:16", "qualidade": "ugc",
                                   "tomadas": tomadas, "cena": "  a sunny   rooftop terrace, golden hour  "})
        self.assertFalse(r["isError"], r)
        t = r["content"][0]["text"]
        self.assertIn("personagem Ana", t)
        self.assertIn("13 s", t)
        self.assertIn("2) 5 s, câmera acompanhar: Agora é só aproveitar.", t)
        pedido = next(iter(planos.planos._itens.values()))["pedido"]
        self.assertEqual(pedido["personagem"], {"id": "ana"})
        self.assertIs(pedido["autorizacao"], True)
        # Com imagem, a cena e o lugar atras da pessoa (pele natural): vale a do agente, com os espacos arrumados
        self.assertEqual(pedido["ajustes"]["cena"], "a sunny rooftop terrace, golden hour")
        self.assertIn("Onde: a sunny rooftop terrace, golden hour", t)
        self.assertEqual([x["duracao"] for x in pedido["ajustes"]["tomadas"]], [8, 5])
        self.assertEqual(list((self.raiz / "projetos").iterdir()), [])

    def test_podcast_sem_cena_usa_o_lugar_da_receita(self):
        self.personagem()
        lugar = planos.receitas()["podcast"]["lugar"]
        self.assertIn("podcast", lugar)
        self.assertIn("microphones", lugar)
        r, p = self._planejar_preparando({"receita": "podcast", "personagem": "ana", "formato": "16:9", "qualidade": "ugc", "tomadas": [TOMADA]})
        self.assertFalse(r["isError"], r)
        self.assertEqual(p["cena"], lugar)
        self.assertIn(f"Onde: {lugar}", r["content"][0]["text"])

    def test_podcast_com_cena_do_agente_usa_a_do_agente(self):
        self.personagem()
        r, p = self._planejar_preparando({"receita": "podcast", "personagem": "ana", "formato": "16:9", "qualidade": "ugc",
                                          "cena": "A small radio booth with one microphone, cool blue light", "tomadas": [TOMADA]})
        self.assertFalse(r["isError"], r)
        self.assertEqual(p["cena"], "A small radio booth with one microphone, cool blue light")

    def test_fala_camera_sem_cena_fica_no_padrao_do_estudio(self):
        self.personagem()
        self.assertNotIn("lugar", planos.receitas()["fala_camera"])
        r, p = self._planejar_preparando({"receita": "fala_camera", "personagem": "ana", "formato": "9:16", "qualidade": "ugc", "tomadas": [TOMADA]})
        self.assertFalse(r["isError"], r)
        self.assertEqual(p["cena"], "")
        self.assertIn("Onde: o padrão do estúdio", r["content"][0]["text"])

    def test_tomada_acima_do_limite_recusa_e_lembra_das_regras(self):
        self.personagem()
        for tomadas in ([dict(TOMADA, duracao=10)], [dict(TOMADA, duracao=3), dict(TOMADA, duracao=7)]):
            r = rpc("planejar_video", {"receita": "fala_camera", "personagem": "ana", "formato": "9:16", "qualidade": "ugc", "tomadas": tomadas})
            self.assertTrue(r["isError"], tomadas)
            t = r["content"][0]["text"]
            self.assertTrue(t.startswith("Tomada "), t)
            self.assertTrue(t.endswith(SUFIXO), t)
        self.assertEqual(planos.planos._itens, {})

    def test_rapido_aceita_tomada_1_mais_longa(self):
        self.personagem()
        r = rpc("planejar_video", {"receita": "fala_camera", "personagem": "ana", "formato": "9:16", "qualidade": "rapido",
                                   "tomadas": [dict(TOMADA, duracao=10)]})
        self.assertFalse(r["isError"], r)

    def test_tomadas_ruins_recusam_com_a_mensagem_da_validacao(self):
        self.personagem()
        for tomadas, trecho in (([dict(TOMADA, camera="drone")], "câmera"), ([dict(TOMADA, duracao=4)], "duração"),
                                ([], "tomadas"), ([TOMADA] * (validacao.MAX_TOMADAS + 1), "tomadas"), ("nada", "tomadas"),
                                ([{"camera": "aproximar", "duracao": 5}], "escreva")):
            r = rpc("planejar_video", {"receita": "fala_camera", "personagem": "ana", "formato": "9:16", "qualidade": "ugc", "tomadas": tomadas})
            self.assertTrue(r["isError"], tomadas)
            self.assertIn(trecho, r["content"][0]["text"], tomadas)
            self.assertTrue(r["content"][0]["text"].endswith(SUFIXO), tomadas)

    def test_cena_texto_sem_cena_recusa(self):
        for cena in (None, "", "   "):
            args = {"receita": "cena_texto", "formato": "16:9", "qualidade": "ugc", "tomadas": [TOMADA_CENA]}
            if cena is not None:
                args["cena"] = cena
            r = rpc("planejar_video", args)
            self.assertTrue(r["isError"], cena)
            t = r["content"][0]["text"]
            self.assertIn("cena", t)
            self.assertIn("inglês", t)
            self.assertNotIn(SUFIXO, t)
        self.assertEqual(planos.planos._itens, {})

    def test_personagem_inexistente_lista_os_disponiveis(self):
        self.personagem("bruno", "Bruno")
        r = rpc("planejar_video", {"receita": "fala_camera", "personagem": "carla", "formato": "9:16", "qualidade": "ugc", "tomadas": [TOMADA]})
        self.assertTrue(r["isError"])
        self.assertIn("listar_personagens", r["content"][0]["text"])
        self.assertIn("bruno", r["content"][0]["text"])

    def test_erro_fora_das_tomadas_nao_manda_rever_as_regras(self):
        self.personagem()

        def preparar(d):
            raise Erro("Envie a imagem de novo: o arquivo não foi encontrado.")
        with mock.patch.object(acoes, "preparar_imagem", preparar):
            r = rpc("planejar_video", {"receita": "fala_camera", "personagem": "ana", "formato": "9:16", "tomadas": [TOMADA]})
        self.assertTrue(r["isError"])
        self.assertEqual(r["content"][0]["text"], "Envie a imagem de novo: o arquivo não foi encontrado.")

    def test_receita_com_imagem_sem_personagem(self):
        r = rpc("planejar_video", {"receita": "podcast", "formato": "16:9", "qualidade": "ugc", "tomadas": [TOMADA]})
        self.assertTrue(r["isError"])
        self.assertEqual(r["content"][0]["text"], "Esta receita precisa de um personagem. Chame listar_personagens.")

    def test_argumentos_ruins(self):
        base = {"receita": "cena_texto", "formato": "9:16", "qualidade": "ugc", "cena": CENA, "tomadas": [TOMADA_CENA]}
        for args in ({**base, "receita": "nao"}, {**base, "formato": "4:3"}, {**base, "personagem": "ana"}):
            self.assertTrue(rpc("planejar_video", args)["isError"], args)

    def test_cada_receita_passa_pelo_preparar_imagem(self):
        self.personagem()
        for rid, receita in planos.receitas().items():
            tomadas = [dict(TOMADA_CENA if not receita["com_imagem"] else TOMADA, duracao=5) for _ in range(3)]
            preparados = []
            original = acoes.preparar_imagem
            with mock.patch.object(acoes, "preparar_imagem", lambda d: preparados.append(original(d)) or preparados[-1]):
                args = {"receita": rid, "formato": "9:16", "qualidade": "ugc", "tomadas": tomadas}
                if receita["com_imagem"]:
                    args["personagem"] = "ana"
                else:
                    args["cena"] = CENA
                r = rpc("planejar_video", args)
            self.assertFalse(r["isError"], (rid, r))
            p = preparados[0]["parametros"]
            self.assertEqual((p["megapixels"], p["pele"], len(p["tomadas"])), (1.1, receita["com_imagem"], 3), rid)
        self.assertEqual(list((self.raiz / "projetos").iterdir()), [])

    def test_sem_os_arquivos_da_pele_recusa(self):
        self.personagem()
        with mock.patch.object(validacao, "faltam_pele", lambda: ["x.safetensors"]):
            r = rpc("planejar_video", {"receita": "fala_camera", "personagem": "ana", "formato": "9:16", "qualidade": "ugc", "tomadas": [TOMADA]})
        self.assertTrue(r["isError"])
        self.assertIn("pele natural", r["content"][0]["text"])

    def _planejar_preparando(self, args):
        """Chama planejar_video guardando os parametros que o preparar_imagem montou."""
        preparados, original = [], acoes.preparar_imagem
        with mock.patch.object(acoes, "preparar_imagem", lambda d: preparados.append(original(d)) or preparados[-1]):
            r = rpc("planejar_video", args)
        return r, (preparados[0]["parametros"] if preparados else None)

    def test_qualidade_padrao_e_ugc(self):
        self.personagem()
        r, p = self._planejar_preparando({"receita": "fala_camera", "personagem": "ana", "formato": "9:16", "tomadas": [TOMADA]})
        self.assertFalse(r["isError"], r)
        self.assertEqual((p["megapixels"], p["pele"]), (1.1, True))
        self.assertIn("qualidade UGC (1,1 MP, pele natural)", r["content"][0]["text"])

    def test_qualidade_rapida_baixa_a_resolucao_e_tira_a_pele(self):
        self.personagem()
        # Sem os arquivos da pele natural o rapido passa: ele nao usa a pele
        with mock.patch.object(validacao, "faltam_pele", lambda: ["x.safetensors"]):
            r, p = self._planejar_preparando({"receita": "fala_camera", "personagem": "ana", "formato": "9:16",
                                              "qualidade": "rapido", "tomadas": [TOMADA]})
        self.assertFalse(r["isError"], r)
        self.assertEqual((p["megapixels"], p["pele"]), (0.4746, False))
        self.assertIn("qualidade rápida (0,47 MP)", r["content"][0]["text"])
        # A receita do arquivo nao muda
        self.assertEqual(planos.receitas()["fala_camera"]["ajustes"]["megapixels"], 1.1)

    def test_qualidade_ugc_na_cena_texto_sem_pele(self):
        r, p = self._planejar_preparando({"receita": "cena_texto", "formato": "16:9", "qualidade": "ugc", "cena": CENA, "tomadas": [TOMADA_CENA]})
        self.assertFalse(r["isError"], r)
        self.assertEqual((p["megapixels"], p["pele"]), (1.1, False))
        self.assertIn("qualidade UGC (1,1 MP)", r["content"][0]["text"])

    def test_qualidade_invalida(self):
        for q in ("4k", ["ugc"]):
            r = rpc("planejar_video", {"receita": "cena_texto", "formato": "16:9", "qualidade": q, "cena": CENA, "tomadas": [TOMADA_CENA]})
            self.assertTrue(r["isError"])
            self.assertIn("Qualidade desconhecida", r["content"][0]["text"])
            self.assertIn("rapido", r["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
