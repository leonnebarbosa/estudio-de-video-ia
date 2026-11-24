"""Testes das receitas, das regras das tomadas, do planejar_video e do confirmar_plano (planos.py e mcp_ferramentas.py).
Quem escreve as tomadas e o agente (cliente MCP): aqui elas vem prontas. O ComfyUI nao e chamado: acoes.acao_iniciar_imagem
e trocado por um duble. Uso: python -I estudio/rodar_testes.py (ou python -I testar_planos.py)"""
import json, sys, tempfile, time, unittest, wave
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
import caminhos, acoes, continuar_video, editar_video, mcp_servidor, mcp_ferramentas, mcp_planejar, midias, personagens, planos, tarefa, validacao, video_avancado  # noqa: F401
from erros import Erro
from imagem_para_video import CAMERAS, DURACOES, duracao_maxima

# A frase da fila consulta o ComfyUI: nos testes ele esta sempre ligado e livre, tambem quando este modulo roda sozinho
import estimativas
estimativas.comfy = lambda: {"ligado": True, "ocupado": False}

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
                                  (personagens, "PASTA", self.raiz / "personagens"), (midias, "ARQUIVO", self.raiz / "midias.json"),
                                  # Nada vai para logs/ de verdade: os planos gravam neste arquivo
                                  (planos, "ARQUIVO", self.raiz / "planos.json"),
                                  # A pele natural das receitas com imagem pede arquivos no ComfyUI: aqui eles "estao la"
                                  (validacao, "faltam_pele", lambda: [])):
            antigo = getattr(alvo, nome)
            setattr(alvo, nome, valor)
            self.addCleanup(setattr, alvo, nome, antigo)
        planos.planos.recarregar()
        self.addCleanup(planos.planos._itens.clear)
        # A frase da fila do resumo le a tarefa: aqui a placa esta livre, sem olhar a fila de verdade do estudio
        livre = mock.Mock()
        livre.rodando.return_value = False
        livre.fila.resumo.return_value = {"pausada": False, "motivo": "", "intervalo": 15, "proxima_em": None, "itens": []}
        p = mock.patch.object(tarefa, "tarefa", livre)
        p.start()
        self.addCleanup(p.stop)

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

    def test_as_linhas_que_o_modo_audio_tira_existem_no_md_e_somem_com_audio(self):
        """O modo audio tira linhas do regras_tomadas.md pelo comeco delas: se alguem reescrever o md, este teste avisa."""
        linhas = planos.REGRAS.read_text(encoding="utf-8").strip().splitlines()
        for comeco in planos._FORA_DO_AUDIO:
            self.assertTrue([l for l in linhas if l.startswith(comeco)], f"o regras_tomadas.md não tem mais a linha '{comeco}'")
        receita = planos.com_audio(planos.com_qualidade(planos.receitas()["fala_camera"], "ugc"))
        t = planos.regras("fala_camera", receita, "ugc", {"nome": "voz.wav", "cortes": [(0.0, 6.4), (6.4, 14.8)]})
        for l in linhas:
            if l.startswith(planos._FORA_DO_AUDIO):
                self.assertNotIn(l, t)
        sem = planos.regras("fala_camera", planos.com_qualidade(planos.receitas()["fala_camera"], "ugc"), "ugc")
        for l in linhas:
            if l.startswith(planos._FORA_DO_AUDIO):
                self.assertIn(l, sem)

    def test_a_linha_final_serve_a_receita_e_repete_a_resolucao_pedida(self):
        def final(args):
            t = rpc("regras_das_tomadas", args)["content"][0]["text"]
            return t[t.index("Depois, chame planejar_video"):]
        assert_cena = final({"receita": "cena_texto"})
        self.assertNotIn("personagem", assert_cena)
        self.assertNotIn("foto", assert_cena)
        self.assertIn(", a cena e as tomadas", assert_cena)
        com_imagem = final({"receita": "fala_camera"})
        self.assertIn("o personagem (ou a foto)", com_imagem)
        self.assertNotIn("resolução", com_imagem)
        self.assertIn('resolucao "720p"', final({"receita": "fala_camera", "resolucao": "720p"}))

    def test_receita_ou_qualidade_desconhecida(self):
        for args in ({"receita": "nao"}, {"receita": "podcast", "qualidade": "4k"}):
            r = rpc("regras_das_tomadas", args)
            self.assertTrue(r["isError"], args)


class Persistencia(Base):
    """Os planos sobrevivem ao religamento do estudio (Planos.recarregar() esvazia a memoria e le o arquivo de novo)."""

    def test_os_testes_nao_gravam_em_logs(self):
        self.assertIsNotNone(planos.ARQUIVO)
        self.assertNotEqual(Path(planos.ARQUIVO).parent, config.LOGS)

    def test_plano_recarregado_confirma_uma_vez(self):
        p = planos.planos
        c = p.criar({"projeto": "mcp_x", "n": [1, 2]}, "resumo", "livre")
        p.recarregar()
        self.assertEqual(p.tipo_de(c), "livre")
        self.assertRegex(p.vale_ate(c), r"^\d\d:\d\d$")
        self.assertEqual(p.usar(c), {"projeto": "mcp_x", "n": [1, 2]})
        with self.assertRaisesRegex(Erro, "já foi confirmado"):
            p.usar(c)

    def test_plano_usado_continua_recusado_depois_de_recarregar(self):
        p = planos.planos
        c = p.criar({"x": 1}, "r")
        p.usar(c)
        p.recarregar()
        with self.assertRaisesRegex(Erro, "já foi confirmado"):
            p.usar(c)

    def test_plano_devolvido_volta_a_valer_depois_de_recarregar(self):
        p = planos.planos
        c = p.criar({"x": 1}, "r")
        p.usar(c)
        p.devolver(c)
        p.recarregar()
        self.assertEqual(p.usar(c), {"x": 1})

    def test_plano_vencido_some_ao_recarregar(self):
        p = planos.planos
        c = p.criar({"x": 1}, "r")
        dados = json.loads(planos.ARQUIVO.read_text(encoding="utf-8"))
        dados[c]["criado"] -= planos.VALIDADE + 1
        planos.ARQUIVO.write_text(json.dumps(dados), encoding="utf-8")
        p.recarregar()
        with self.assertRaisesRegex(Erro, "não encontrado"):
            p.usar(c)
        self.assertEqual(p._itens, {})

    def test_tipo_desconhecido_sobrevive_mas_item_malformado_nao(self):
        agora = time.time()
        bom = {"pedido": {"a": 1}, "resumo": "r", "criado": agora, "usado": False, "tipo": "imagem"}
        ruins = {"a": "texto", "b": {**bom, "pedido": "x"}, "c": {**bom, "criado": "ontem"}, "d": {**bom, "usado": "nao"},
                 "e": {**bom, "tipo": 3}, "f": {k: v for k, v in bom.items() if k != "resumo"}}
        planos.ARQUIVO.write_text(json.dumps({**ruins, "ok": bom}), encoding="utf-8")
        planos.planos.recarregar()
        self.assertEqual(planos.planos.tipo_de("ok"), "imagem")
        self.assertEqual(set(planos.planos._itens), {"ok"})

    def test_arquivo_corrompido_ou_ausente_vale_como_vazio(self):
        p = planos.planos
        p.recarregar()  # ainda sem arquivo
        with self.assertRaises(Erro):
            p.usar("abcdef")
        for lixo in ("{nao e json", "[]", ""):
            planos.ARQUIVO.write_text(lixo, encoding="utf-8")
            p.recarregar()
            self.assertEqual(p._itens, {}, lixo)
            c = p.criar({"x": 1}, "r")
            self.assertEqual(p.usar(c), {"x": 1})

    def test_gravacao_que_falha_ao_usar_nao_reabre_o_plano(self):
        p = planos.planos
        c = p.criar({"x": 1}, "r")
        with mock.patch.object(caminhos, "gravar_json", side_effect=PermissionError):
            self.assertEqual(p.usar(c), {"x": 1})  # a chamada em si nao quebra
        p.recarregar()
        with self.assertRaises(Erro):  # recusado (nao encontrado), nunca confirmado de novo
            p.usar(c)

    def test_plano_usado_e_velho_continua_dando_ja_confirmado(self):
        p = planos.planos
        c = p.criar({"x": 1}, "r")
        p.usar(c)
        dados = json.loads(planos.ARQUIVO.read_text(encoding="utf-8"))
        dados[c]["criado"] -= planos.VALIDADE + 60
        sem_uso = p.criar({"y": 1}, "r")
        dados[sem_uso] = {**json.loads(planos.ARQUIVO.read_text(encoding="utf-8"))[sem_uso], "criado": time.time() - planos.VALIDADE - 60}
        planos.ARQUIVO.write_text(json.dumps(dados), encoding="utf-8")
        p.recarregar()
        with self.assertRaisesRegex(Erro, "já foi confirmado"):
            p.usar(c)
        with self.assertRaisesRegex(Erro, "não encontrado"):  # o vencido sem uso continua caindo
            p.usar(sem_uso)

    def test_esvaziar_a_memoria_na_mao_nao_recarrega_do_arquivo(self):
        p = planos.planos
        c = p.criar({"x": 1}, "r")
        p._itens.clear()
        with self.assertRaises(Erro):
            p.usar(c)

    def test_falha_ao_gravar_nao_quebra_o_criar(self):
        planos.ARQUIVO = self.raiz  # uma pasta no lugar do arquivo
        p = planos.planos
        c = p.criar({"x": 1}, "r")
        self.assertEqual(p.usar(c), {"x": 1})
        p.devolver(c)
        self.assertEqual(p.usar(c), {"x": 1})

    def test_confirmar_plano_funciona_com_plano_recarregado(self):
        iniciados = []
        rpc("planejar_video", {"receita": "cena_texto", "formato": "16:9", "qualidade": "ugc", "cena": CENA, "tomadas": [TOMADA_CENA]})
        codigo = next(iter(planos.planos._itens))
        planos.planos.recarregar()
        with mock.patch.object(acoes, "acao_iniciar_imagem", iniciados.append):
            r = rpc("confirmar_plano", {"codigo_plano": codigo})
            repetido = rpc("confirmar_plano", {"codigo_plano": codigo})
        self.assertFalse(r["isError"], r)
        self.assertEqual(len(iniciados), 1)
        self.assertTrue(repetido["isError"])


class Planos(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        antigo = planos.ARQUIVO
        planos.ARQUIVO = Path(d.name) / "planos.json"  # os Planos() novos daqui tambem nao gravam em logs/
        self.addCleanup(setattr, planos, "ARQUIVO", antigo)

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
        self.assertTrue(linhas[1].startswith("Tempo estimado: cerca de "), linhas[1])
        self.assertEqual(linhas[2], "1) 3,5 s, câmera aproximar: Oi, gente!")
        self.assertTrue(linhas[3].startswith("2) 3 s, câmera afastar:"))
        self.assertIn("The character smiles", linhas[3])

    def test_resumo_mostra_o_rotulo_do_visual_e_a_raiz_segue_com_o_nome(self):
        with tempfile.TemporaryDirectory() as d:
            for pid, ficha in (("ana", {"nome": "Ana"}), ("ana_praia", {"nome": "Ana (Praia)", "copia_de": "ana", "visual": "Praia"})):
                pasta = Path(d) / pid
                pasta.mkdir()
                (pasta / "ficha.json").write_text(json.dumps(ficha), encoding="utf-8")
                (pasta / "frente.png").write_bytes(b"png")
            tomadas = [{"camera": "aproximar", "duracao": 3, "fala": "Oi", "acao": "waves"}]

            def linha(pid):
                pedido = {"projeto": "x", "foto": None, "personagem": {"id": pid},
                          "ajustes": {"proporcao": "9:16 (Portrait Widescreen)", "cena": "", "tomadas": tomadas}}
                with mock.patch.object(personagens, "PASTA", Path(d)):
                    return planos.resumo(pedido).splitlines()[0]
            self.assertIn(", personagem Ana · Praia, ", linha("ana_praia"))
            self.assertIn(", personagem Ana, ", linha("ana"))
            self.assertNotIn("Original", linha("ana"))

    def test_resumo_tempo_estimado_usa_as_tomadas_os_megapixels_e_a_pele(self):
        def pedido(**a):
            return {"projeto": "x", "foto": None, "ajustes": {"proporcao": "9:16 (Portrait Widescreen)", "cena": "", "megapixels": 0.4746,
                    "tomadas": [{"camera": "aproximar", "duracao": 5, "fala": "Oi", "acao": "waves"}], **a}}
        self.assertEqual(planos.resumo(pedido()).splitlines()[1],
                         "Tempo estimado: cerca de 4 min (só a geração; não conta espera na fila).")
        # 5 s a 1,2 MP: 496 s; com a pele natural, 496 * 350 / 312 = 556 s
        self.assertIn("cerca de 8 min", planos.resumo(pedido(megapixels=1.2)).splitlines()[1])
        self.assertIn("cerca de 9 min", planos.resumo(pedido(megapixels=1.2, pele=True)).splitlines()[1])

    def test_resumo_livre_usa_a_estimativa_do_modo_livre(self):
        d = {"proporcao": "9:16 (Portrait Widescreen)", "referencias": [], "duracao": 5, "megapixels": 1.2, "prompt": "x <d>[Portuguese (Brazil)] oi</d>"}
        # 5 s na maxima: 496 s pela formula das receitas (8 min) e cerca de 580 s no modo livre (10 min)
        self.assertIn("Tempo estimado: cerca de 10 min", planos.resumo_livre(d))
        with mock.patch.object(planos.estimativas, "video_livre", return_value=100):
            self.assertIn("Tempo estimado: cerca de 2 min", planos.resumo_livre(d))


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
        self.assertEqual(set(item["required"]), {"acao", "camera"})
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
        # O resumo mostra o tempo estimado e o que ha na frente (aqui, a placa esta livre)
        self.assertIn("Tempo estimado: cerca de ", texto)
        self.assertIn("A placa está livre: começa assim que você confirmar.", texto)
        # Confirmar de novo nao inicia outra vez
        with mock.patch.object(acoes, "acao_iniciar_imagem", iniciados.append):
            r = rpc("confirmar_plano", {"codigo_plano": codigo})
        self.assertTrue(r["isError"])
        self.assertIn("já foi confirmado", r["content"][0]["text"])
        self.assertEqual(len(iniciados), 1)

    def test_confirmar_na_fila_diz_a_posicao(self):
        rpc("planejar_video", {"receita": "cena_texto", "formato": "16:9", "qualidade": "ugc", "cena": CENA, "tomadas": [TOMADA_CENA]})
        codigo = next(c for c in planos.planos._itens)
        itens = [{"id": "a1", "projeto": "outro1", "modo": "gerar", "tipo": "imagem", "criado": 0},
                 {"id": "a2", "projeto": "outro2", "modo": "gerar", "tipo": "imagem", "criado": 0}]
        falsa = mock.Mock()
        falsa.rodando.return_value = True
        falsa.fila.resumo.side_effect = lambda: {"pausada": False, "motivo": "", "intervalo": 15, "proxima_em": None, "itens": list(itens)}

        def iniciar(d):
            itens.append({"id": "a3", "projeto": d["projeto"], "modo": "gerar", "tipo": "imagem", "criado": 0})
        with mock.patch.object(tarefa, "tarefa", falsa), mock.patch.object(acoes, "acao_iniciar_imagem", iniciar):
            r = rpc("confirmar_plano", {"codigo_plano": codigo})
        self.assertFalse(r["isError"], r)
        self.assertEqual(r["content"][0]["text"], f"Entrou na fila: {itens[2]['projeto']} (posição 3)")

    def test_planejar_diz_o_que_ha_na_frente(self):
        falsa = mock.Mock()
        falsa.rodando.return_value = True
        falsa.fila.resumo.return_value = {"pausada": False, "motivo": "", "intervalo": 15, "proxima_em": None,
                                          "itens": [{"id": "a1", "projeto": "o", "modo": "gerar", "tipo": "imagem", "criado": 0}] * 2}
        with mock.patch.object(tarefa, "tarefa", falsa):
            r = rpc("planejar_video", {"receita": "cena_texto", "formato": "16:9", "qualidade": "ugc", "cena": CENA, "tomadas": [TOMADA_CENA]})
        self.assertFalse(r["isError"], r)
        self.assertIn("Há 1 geração em andamento e 2 na fila: este pedido entra atrás delas.", r["content"][0]["text"])

    def test_confirmar_que_falha_devolve_o_plano(self):
        rpc("planejar_video", {"receita": "cena_texto", "formato": "16:9", "qualidade": "ugc", "cena": CENA, "tomadas": [TOMADA_CENA]})
        codigo = next(c for c in planos.planos._itens)

        def desligado(d):
            raise Erro("O ComfyUI está desligado. Esperando o ComfyUI ficar pronto.", 409)
        with mock.patch.object(acoes, "acao_iniciar_imagem", desligado):
            r = rpc("confirmar_plano", {"codigo_plano": codigo})
        self.assertTrue(r["isError"])
        t = r["content"][0]["text"]
        self.assertIn("desligado", t)
        # Um agente local tratou a falha como sucesso e foi buscar o resultado: a mensagem diz que nada comecou e o que fazer
        self.assertIn("Nada começou", t)
        self.assertIn(f"O plano {codigo} continua valendo até ", t)
        self.assertRegex(t, "continua valendo até [0-2][0-9]:[0-5][0-9]")
        self.assertIn("ver_estado", t)
        self.assertIn("confirmar_plano de novo", t)
        # O agente repetiu a confirmacao seis vezes em 20 s: a mensagem manda avisar o usuario e esperar
        self.assertIn("Não chame confirmar_plano de novo agora", t)
        self.assertIn("espere ele pedir", t)
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
        self.assertEqual(r["content"][0]["text"], "Esta receita precisa de um personagem ou de uma foto. Chame listar_personagens ou listar_midias.")

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
        self.assertIn("qualidade UGC, 1,1 MP, pele natural", r["content"][0]["text"])

    def test_qualidade_rapida_baixa_a_resolucao_e_tira_a_pele(self):
        self.personagem()
        # Sem os arquivos da pele natural o rapido passa: ele nao usa a pele
        with mock.patch.object(validacao, "faltam_pele", lambda: ["x.safetensors"]):
            r, p = self._planejar_preparando({"receita": "fala_camera", "personagem": "ana", "formato": "9:16",
                                              "qualidade": "rapido", "tomadas": [TOMADA]})
        self.assertFalse(r["isError"], r)
        self.assertEqual((p["megapixels"], p["pele"]), (0.4746, False))
        self.assertIn("qualidade rápida, 540p (0,47 MP)", r["content"][0]["text"])
        # A receita do arquivo nao muda
        self.assertEqual(planos.receitas()["fala_camera"]["ajustes"]["megapixels"], 1.1)

    def test_qualidade_ugc_na_cena_texto_sem_pele(self):
        r, p = self._planejar_preparando({"receita": "cena_texto", "formato": "16:9", "qualidade": "ugc", "cena": CENA, "tomadas": [TOMADA_CENA]})
        self.assertFalse(r["isError"], r)
        self.assertEqual((p["megapixels"], p["pele"]), (1.1, False))
        self.assertIn("qualidade UGC, 1,1 MP", r["content"][0]["text"])

    def test_qualidade_invalida(self):
        for q in ("4k", ["ugc"]):
            r = rpc("planejar_video", {"receita": "cena_texto", "formato": "16:9", "qualidade": q, "cena": CENA, "tomadas": [TOMADA_CENA]})
            self.assertTrue(r["isError"])
            self.assertIn("Qualidade desconhecida", r["content"][0]["text"])
            self.assertIn("rapido", r["content"][0]["text"])


def _imagem(caminho, largura, altura):
    from PIL import Image
    Image.new("RGB", (largura, altura), (120, 90, 60)).save(caminho)


SINGULARITY = "Minimax-h3_Singularity_ref2va_v2_pruned_int8.safetensors"
OFICIAL_REF2VA = "minimax_h3_ref2va_pruned_int8_convrot.safetensors"
OPCOES = {"modelos": [SINGULARITY, OFICIAL_REF2VA, "Outro_ref2va_turbo_int8.safetensors"], "samplers": ["euler"],
          "loras_estilo": ["H3-Cinematic-V2.safetensors", "feltStopMotionStyle_H3_v01.safetensors", "H3_Motion_BoosterV2.safetensors"]}


class ModeloELoras(Base):
    """Modelo da tomada 1, modelo das seguintes e LoRAs de estilo pelo planejar_video (pedido do usuário em 23/11, depois que um
    Claude Code não conseguiu escolher o Singularity nem a LoRA Cinematic num vídeo de cinema)."""
    def setUp(self):
        super().setUp()
        import ambiente
        p = mock.patch.object(ambiente, "ler_opcoes", lambda: OPCOES)
        p.start()
        self.addCleanup(p.stop)
        # A tabela de forças recomendadas vem do arquivo local (modelos_locais.json): no teste, uma fixa
        import extras
        e = mock.patch.object(extras, "secao", lambda nome: {"forca_lora": {"h3-cinematic-v2.safetensors": 0.85}} if nome == "pagina" else {})
        e.start()
        self.addCleanup(e.stop)

    def planejar(self, **extra):
        return rpc("planejar_video", {"receita": "cena_texto", "formato": "16:9", "cena": CENA, "tomadas": [TOMADA_CENA], **extra})

    def ajustes_do_plano(self):
        return planos.planos._itens[next(iter(planos.planos._itens))]["pedido"]["ajustes"]

    def test_esquema_tem_os_campos_e_a_ferramenta_lista_as_opcoes(self):
        p = next(f for f in mcp_servidor.listar("operador") if f["name"] == "planejar_video")["inputSchema"]["properties"]
        self.assertLessEqual({"modelo_tomada1", "modelo_seguintes", "loras"}, set(p))
        self.assertEqual(p["loras"]["maxItems"], validacao.MAX_LORAS_VIDEO)
        r = rpc("listar_modelos_video", {})
        self.assertFalse(r["isError"], r)
        t = r["content"][0]["text"]
        for parte in ("Minimax-h3_Singularity_ref2va_v2_pruned_int8", "Singularity V2", "Outro_ref2va_turbo_int8", "H3-Cinematic-V2",
                      "feltStopMotionStyle_H3_v01", "padrão", "H3-Cinematic-V2 (força 0,85)", "feltStopMotionStyle_H3_v01 (força 0,8;"):
            self.assertIn(parte, t)
        # O ref2va oficial é o padrão das seguintes; na tomada 1 ele não é opção (validacao.validar_imagem recusa)
        tomada1 = t.split("Tomadas 2 em diante")[0]
        self.assertNotIn("minimax_h3_ref2va_pruned_int8_convrot", tomada1)

    def test_modelo_e_loras_entram_no_plano_e_no_resumo(self):
        r = self.planejar(modelo_tomada1="Minimax-h3_Singularity_ref2va_v2_pruned_int8", modelo_seguintes="outro_ref2va_turbo_int8.safetensors",
                          loras=[{"nome": "H3-Cinematic-V2", "forca": 0.7}, {"nome": "h3_motion_boosterv2"}])
        self.assertFalse(r["isError"], r)
        a = self.ajustes_do_plano()
        self.assertEqual(a["primeira"], SINGULARITY)
        self.assertEqual(a["seguintes"], "Outro_ref2va_turbo_int8.safetensors")
        # Sem força e fora da tabela de recomendadas, 0,8: o mesmo padrão da página
        self.assertEqual(a["loras"], [["H3-Cinematic-V2.safetensors", 0.7], ["H3_Motion_BoosterV2.safetensors", 0.8]])
        t = r["content"][0]["text"]
        self.assertIn("Modelo da tomada 1: Singularity V2", t)
        self.assertIn("Tomadas seguintes: Outro_ref2va_turbo_int8", t)
        self.assertIn("LoRAs de estilo: H3-Cinematic-V2 (0,7), H3_Motion_BoosterV2 (0,8)", t)

    def test_sem_forca_vale_a_recomendada_pelo_autor(self):
        r = self.planejar(loras=[{"nome": "H3-Cinematic-V2"}])
        self.assertFalse(r["isError"], r)
        self.assertEqual(self.ajustes_do_plano()["loras"], [["H3-Cinematic-V2.safetensors", 0.85]])

    def test_sem_escolha_fica_o_padrao(self):
        r = self.planejar()
        self.assertFalse(r["isError"], r)
        a = self.ajustes_do_plano()
        self.assertFalse(a.get("primeira") or a.get("seguintes") or a.get("loras"))
        self.assertNotIn("Modelo da tomada 1", r["content"][0]["text"])

    def test_recusa_o_que_nao_esta_instalado(self):
        r = self.planejar(modelo_tomada1="nao_existe")
        self.assertTrue(r["isError"])
        self.assertIn("listar_modelos_video", r["content"][0]["text"])
        r = self.planejar(modelo_tomada1=OFICIAL_REF2VA)  # o oficial já é o padrão das seguintes, não da tomada 1
        self.assertTrue(r["isError"])
        r = self.planejar(loras=[{"nome": "nao_existe"}])
        self.assertTrue(r["isError"])
        self.assertIn("listar_modelos_video", r["content"][0]["text"])
        r = self.planejar(loras=[{"nome": n} for n in OPCOES["loras_estilo"]])
        self.assertTrue(r["isError"])
        self.assertIn(str(validacao.MAX_LORAS_VIDEO), r["content"][0]["text"])
        r = self.planejar(loras=[{"nome": "H3-Cinematic-V2", "forca": 3}])
        self.assertTrue(r["isError"])

    def test_pele_natural_nao_deixa_trocar_o_modelo(self):
        # Com personagem na qualidade ugc a pele natural usa o Singularity em todas as tomadas: escolher modelo seria ignorado
        self.personagem()
        base = {"receita": "fala_camera", "personagem": "ana", "formato": "9:16", "tomadas": [TOMADA]}
        r = rpc("planejar_video", {**base, "modelo_tomada1": SINGULARITY})
        self.assertTrue(r["isError"])
        self.assertIn("rapido", r["content"][0]["text"])
        # A LoRA de estilo vale junto com a pele, e na qualidade rápida o modelo também
        self.assertFalse(rpc("planejar_video", {**base, "loras": [{"nome": "H3-Cinematic-V2"}]})["isError"])
        self.assertFalse(rpc("planejar_video", {**base, "qualidade": "rapido", "modelo_tomada1": SINGULARITY})["isError"])

    def test_semente_entra_no_plano_e_no_resumo(self):
        # Pedido do usuário em 24/11: o agente repetiu o ugc_santarem_12mp sem poder fixar a semente 2026 do original
        r = self.planejar(semente=2026)
        self.assertFalse(r["isError"], r)
        self.assertEqual(self.ajustes_do_plano()["semente"], 2026)
        self.assertIn("Semente: 2026 (fixa)", r["content"][0]["text"])

    def test_sem_semente_sorteia_e_o_resumo_nao_fala_dela(self):
        r = self.planejar()
        self.assertFalse(r["isError"], r)
        self.assertIsNone(self.ajustes_do_plano()["semente"])
        self.assertNotIn("Semente", r["content"][0]["text"])

    def test_semente_invalida_e_recusada(self):
        for ruim in (-1, 1.5, "abc", True, mcp_planejar.MAX_SEMENTE):
            r = self.planejar(semente=ruim)
            self.assertTrue(r["isError"], ruim)
            self.assertIn("semente", r["content"][0]["text"].lower())
        self.assertFalse(planos.planos._itens)



class Resolucao(Base):
    """Resolucao em "p" (480p, 540p, 720p, maxima), foto conferida no registro de midias e avisos do resumo."""

    def test_tabela_e_a_mesma_do_menu_da_pagina(self):
        self.assertEqual(tuple(planos.RESOLUCOES.values()), validacao.QUALIDADES_IMAGEM_MENU)

    def test_com_qualidade_troca_so_os_megapixels(self):
        receita = planos.receitas()["fala_camera"]
        r = planos.com_qualidade(receita, "ugc", "720p")
        self.assertEqual((r["ajustes"]["megapixels"], r["ajustes"]["pele"]), (0.88, receita["ajustes"]["pele"]))
        r = planos.com_qualidade(receita, "rapido", "480p")
        self.assertEqual((r["ajustes"]["megapixels"], r["ajustes"]["pele"]), (0.39, False))
        # Sem resolucao, valem os megapixels da qualidade
        self.assertEqual(planos.com_qualidade(receita, "ugc")["ajustes"]["megapixels"], 1.1)
        with self.assertRaises(Erro) as e:
            planos.com_qualidade(receita, "ugc", "4k")
        for nome in ("480p", "540p", "720p", "maxima"):
            self.assertIn(nome, e.exception.mensagem)

    def test_nome_da_resolucao(self):
        self.assertEqual(planos.nome_resolucao(0.88), "720p (0,88 MP)")
        self.assertEqual(planos.nome_resolucao(1.2), "máxima (1,2 MP)")
        self.assertEqual(planos.nome_resolucao(0.39), "480p (0,39 MP)")
        self.assertEqual(planos.nome_resolucao(0.4746), "540p (0,47 MP)")
        self.assertEqual(planos.nome_resolucao(1.1), "1,1 MP")

    def test_avisos_da_resolucao(self):
        self.assertEqual(planos.avisos_resolucao(1.1), [])
        self.assertEqual(planos.avisos_resolucao(0.4746), [])
        for mp, comeco in ((0.39, "Aviso: 480p ainda não foi rodada nesta placa; deve ser um pouco mais rápida que 540p, com menos detalhe."),
                           (0.88, "Aviso: 720p ainda não foi rodada exatamente; deve levar perto de 2 vezes o tempo de 540p."),
                           (1.2, "Aviso: resolução máxima é a mais pesada testada; cada tomada vai até 8 s")):
            (aviso,) = planos.avisos_resolucao(mp)
            self.assertTrue(aviso.startswith(comeco), aviso)
            # Um agente local escolheu a maxima sozinho: o aviso manda planejar de novo sem resolucao se o usuario nao pediu
            self.assertIn("planeje de novo sem resolucao", aviso)
        self.assertIn("dobro do tempo de 540p", planos.avisos_resolucao(1.2)[0])

    def test_regras_na_resolucao_maxima(self):
        r = rpc("regras_das_tomadas", {"receita": "fala_camera", "qualidade": "ugc", "resolucao": "maxima"})
        self.assertFalse(r["isError"], r)
        t = r["content"][0]["text"]
        self.assertIn(f"tomada 1 até {planos._br(duracao_maxima(1.2))} s", t)
        self.assertIn("tomada 1 até 8 s", t)
        self.assertIn("máxima (1,2 MP)", t)
        r = rpc("regras_das_tomadas", {"receita": "fala_camera", "resolucao": "4k"})
        self.assertTrue(r["isError"])
        self.assertIn("720p", r["content"][0]["text"])

    def _planejar(self, args):
        preparados, original = [], acoes.preparar_imagem
        with mock.patch.object(acoes, "preparar_imagem", lambda d: preparados.append(original(d)) or preparados[-1]):
            r = rpc("planejar_video", args)
        return r, (preparados[0]["parametros"] if preparados else None)

    def test_planejar_com_720p(self):
        self.personagem()
        r, p = self._planejar({"receita": "fala_camera", "personagem": "ana", "formato": "9:16", "qualidade": "ugc",
                               "resolucao": "720p", "tomadas": [TOMADA]})
        self.assertFalse(r["isError"], r)
        self.assertEqual((p["megapixels"], p["pele"]), (0.88, True))
        t = r["content"][0]["text"]
        self.assertIn("720p (0,88 MP)", t)
        self.assertIn("Aviso: 720p ainda não foi rodada exatamente", t)
        # Resolucao desconhecida recusa antes de tudo
        r = rpc("planejar_video", {"receita": "fala_camera", "personagem": "ana", "formato": "9:16", "resolucao": "4k", "tomadas": [TOMADA]})
        self.assertTrue(r["isError"])
        self.assertIn("maxima", r["content"][0]["text"])

    def test_camera_parada_com_fala_avisa_e_sem_fala_nao(self):
        self.personagem()
        base = {"receita": "fala_camera", "personagem": "ana", "formato": "9:16", "qualidade": "ugc"}
        r = rpc("planejar_video", {**base, "tomadas": [dict(TOMADA, camera="aproximar"), dict(TOMADA, camera="parada")]})
        self.assertFalse(r["isError"], r)
        self.assertIn("Aviso: tomada 2 com câmera parada. Vídeo com fala fica mais natural com a câmera em movimento.", r["content"][0]["text"])
        self.assertEqual(len(planos.planos._itens), 1)
        r = rpc("planejar_video", {**base, "tomadas": [dict(TOMADA, camera="parada", fala="")]})
        self.assertFalse(r["isError"], r)
        self.assertNotIn("Aviso", r["content"][0]["text"])

    def _foto(self, nome="x.png", tamanho=(1024, 576), tipo="foto"):
        _imagem(config.ENTRADA / nome, *tamanho)
        midias.registrar(nome, tipo, "mcp", {})

    def test_foto_desconhecida_ou_de_outro_tipo_recusa(self):
        args = {"receita": "fala_camera", "formato": "9:16", "qualidade": "ugc", "tomadas": [TOMADA]}
        r = rpc("planejar_video", {**args, "foto": "nao_existe.png"})
        self.assertTrue(r["isError"])
        self.assertIn("listar_midias", r["content"][0]["text"])
        self._foto("fala.png", tipo="audio")
        r = rpc("planejar_video", {**args, "foto": "fala.png"})
        self.assertTrue(r["isError"])
        self.assertIn("listar_midias", r["content"][0]["text"])
        self.assertEqual(planos.planos._itens, {})

    def test_resumo_diz_o_papel_da_foto(self):
        self._foto()
        args = {"receita": "fala_camera", "foto": "x.png", "formato": "16:9", "tomadas": [TOMADA]}
        t = rpc("planejar_video", {**args, "qualidade": "ugc"})["content"][0]["text"]
        self.assertIn("Pessoa da foto: x.png", t)
        self.assertNotIn("Primeiro quadro", t)
        t = rpc("planejar_video", {**args, "qualidade": "rapido"})["content"][0]["text"]
        self.assertIn("Primeiro quadro: x.png", t)
        self.assertNotIn("Pessoa da foto", t)
        self.assertNotIn("será cortada", t)  # 16:9 em 16:9

    def test_aviso_de_corte_so_sem_pele_natural(self):
        self._foto()  # 16:9
        args = {"receita": "fala_camera", "foto": "x.png", "formato": "9:16", "tomadas": [TOMADA]}
        t = rpc("planejar_video", {**args, "qualidade": "rapido"})["content"][0]["text"]
        self.assertIn("Aviso: a foto tem outro formato e será cortada pelo centro.", t)
        t = rpc("planejar_video", {**args, "qualidade": "ugc"})["content"][0]["text"]
        self.assertNotIn("será cortada", t)

    def test_avisos_de_corte_na_funcao(self):
        self._foto("x.png", (1024, 576))
        self._foto("quase.png", (1000, 1010))  # a 1:1 a menos de 3%
        (config.ENTRADA / "quebrada.png").write_bytes(b"nao e imagem")
        sem_pele = {"foto": "x.png", "ajustes": {"pele": False, "megapixels": 1.1, "tomadas": []}}
        self.assertEqual(planos.avisos(sem_pele, "1:1"), ["Aviso: a foto tem outro formato e será cortada pelo centro."])
        self.assertEqual(planos.avisos(sem_pele, "16:9"), [])
        self.assertEqual(planos.avisos({**sem_pele, "foto": "quase.png"}, "1:1"), [])
        self.assertEqual(planos.avisos({**sem_pele, "foto": "quebrada.png"}, "1:1"), [])
        self.assertEqual(planos.avisos({**sem_pele, "foto": "sumiu.png"}, "1:1"), [])


def _fala_wav(caminho, blocos, taxa=16000):
    """WAV de teste: [(segundos, com_voz)]; voz = tom de 220 Hz, silencio = ruido muito baixo (como o testar_audio_fala)."""
    partes, rng = [], np.random.default_rng(1)
    for s, tem in blocos:
        n = int(s * taxa)
        t = np.arange(n) / taxa
        partes.append(0.3 * np.sin(2 * np.pi * 220 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 3 * t)) if tem else 0.0005 * rng.standard_normal(n))
    pcm = np.concatenate(partes).astype(np.float32)
    with wave.open(str(caminho), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(taxa)
        w.writeframes((np.clip(pcm, -1, 1) * 32767).astype(np.int16).tobytes())


FALA_12S = [(4.8, True), (0.4, False), (3.8, True), (0.3, False), (2.9, True)]
TOMADA_AUDIO = {"acao": "The character smiles and talks to the camera.", "fala": "", "som": "", "camera": "aproximar"}


def _br(x):
    return f"{x:g}".replace(".", ",")


class AudioDaFala(Base):
    def setUp(self):
        super().setUp()
        self.personagem()
        _fala_wav(config.ENTRADA / "voz.wav", FALA_12S)
        midias.registrar("voz.wav", "audio", "mcp", {})

    def cortes(self, mp):
        return validacao.cortes_do_audio("voz.wav", mp)[1]

    def args(self, n, **k):
        return {"receita": "fala_camera", "personagem": "ana", "formato": "9:16", "audio_fala": "voz.wav",
                "tomadas": [dict(TOMADA_AUDIO) for _ in range(n)], **k}

    def planejar(self, args):
        preparados, original = [], acoes.preparar_imagem
        with mock.patch.object(acoes, "preparar_imagem", lambda d: preparados.append((d, original(d))) or preparados[-1][1]):
            r = rpc("planejar_video", args)
        return r, (preparados[0] if preparados else (None, None))

    def test_planejar_sem_receita_diz_que_falta(self):
        # Um modelo local esqueceu a receita duas vezes seguidas porque a mensagem dizia "desconhecida"
        r = rpc("planejar_video", {"formato": "9:16", "tomadas": [{"acao": "The character waves.", "camera": "aproximar", "duracao": 3}]})
        self.assertTrue(r["isError"], r)
        self.assertIn("Falta a receita", r["content"][0]["text"])
        self.assertIn("fala_camera", r["content"][0]["text"])

    def test_regras_dizem_a_divisao_e_o_exemplo_tem_o_numero_de_tomadas(self):
        r = rpc("regras_das_tomadas", {"receita": "fala_camera", "audio_fala": "voz.wav"})
        self.assertFalse(r["isError"], r)
        t = r["content"][0]["text"]
        cortes = self.cortes(1.1)
        total = sum(b - a for a, b in cortes)
        self.assertIn(f"O áudio tem {_br(round(total, 1))} s e vira {len(cortes)} tomadas nesta resolução: 1) ", t)
        exemplo = exemplo_do_texto(t)
        self.assertEqual(len(exemplo), len(cortes))
        for tom in exemplo:
            self.assertNotIn("duracao", tom)
            self.assertNotEqual(tom["camera"], "parada")
        self.assertIn("Pele natural", t)
        self.assertIn("Não mande a duracao", t)
        self.assertIn("cortes de 2 a 3 s não valem", t)
        # A frase da receita sobre os cortes sai no modo audio (um modelo local repetiu "maximo de 3 s por tomada")
        self.assertNotIn("um corte a cada 2 a 3 s", t)
        self.assertNotIn("tomadas de 3 ou 3,5 s", t)
        self.assertIn("câmera sempre em movimento", t)
        sem_audio = rpc("regras_das_tomadas", {"receita": "fala_camera"})["content"][0]["text"]
        self.assertIn("um corte a cada 2 a 3 s", sem_audio)
        # sem o audio, nada disso
        self.assertNotIn("O áudio tem", rpc("regras_das_tomadas", {"receita": "fala_camera"})["content"][0]["text"])

    def test_regras_com_audio_seguem_a_resolucao(self):
        t = rpc("regras_das_tomadas", {"receita": "fala_camera", "audio_fala": "voz.wav", "qualidade": "rapido"})["content"][0]["text"]
        n = len(self.cortes(0.4746))
        self.assertIn(f"vira {n} {'tomada' if n == 1 else 'tomadas'} nesta resolução", t)
        self.assertEqual(len(exemplo_do_texto(t)), n)
        self.assertIn("pele natural", t)  # no audio ela fica ligada mesmo no rapido

    def test_regras_com_audio_invalido(self):
        for args in ({"audio_fala": "nao_existe.wav"}, {"audio_fala": 3}):
            r = rpc("regras_das_tomadas", {"receita": "fala_camera", **args})
            self.assertTrue(r["isError"], args)
            self.assertIn("listar_midias", r["content"][0]["text"])
        r = rpc("regras_das_tomadas", {"receita": "cena_texto", "audio_fala": "voz.wav"})
        self.assertTrue(r["isError"])
        # Uma redacao so para "audio_fala so em receita com imagem", nas duas ferramentas
        p = rpc("planejar_video", {"receita": "cena_texto", "formato": "16:9", "cena": CENA, "audio_fala": "voz.wav", "tomadas": [dict(TOMADA_AUDIO)]})
        self.assertEqual(r["content"][0]["text"], p["content"][0]["text"])
        self.assertIn("só vale nas receitas com imagem", r["content"][0]["text"])

    def test_planejar_monta_o_audio_e_a_pele_mesmo_no_rapido(self):
        cortes = self.cortes(0.4746)
        r, (d, p) = self.planejar(self.args(len(cortes), qualidade="rapido"))
        self.assertFalse(r["isError"], r)
        self.assertEqual(d["ajustes"]["audio"], "voz.wav")
        self.assertEqual((p["parametros"]["pele"], p["parametros"]["megapixels"]), (True, 0.4746))
        self.assertEqual(len(p["parametros"]["tomadas"]), len(cortes))
        t = r["content"][0]["text"]
        self.assertIn(f"Áudio da fala: voz.wav ({_br(round(sum(b - a for a, b in cortes), 1))} s, {len(cortes)} ", t)
        self.assertNotIn("Lugar (foto)", t)
        self.assertEqual(len(planos.planos._itens), 1)

    def test_planejar_ugc_e_com_resolucao(self):
        r, (d, p) = self.planejar(self.args(len(self.cortes(1.1))))
        self.assertFalse(r["isError"], r)
        self.assertEqual((p["parametros"]["pele"], p["parametros"]["megapixels"]), (True, 1.1))
        r, (d, p) = self.planejar(self.args(len(self.cortes(0.88)), resolucao="720p"))
        self.assertFalse(r["isError"], r)
        self.assertEqual(p["parametros"]["megapixels"], 0.88)

    def test_duracao_de_cada_tomada_vem_da_divisao(self):
        cortes = self.cortes(1.1)
        r, _ = self.planejar(self.args(len(cortes)))
        t = r["content"][0]["text"]
        for i, (a, b) in enumerate(cortes, 1):
            self.assertIn(f"{i}) {_br(round(b - a, 3))} s, câmera aproximar", t)

    def test_numero_de_tomadas_errado(self):
        certo = len(self.cortes(1.1))
        for n in (certo + 1, 1 if certo != 1 else 2):
            r = rpc("planejar_video", self.args(n))
            self.assertTrue(r["isError"])
            t = r["content"][0]["text"]
            self.assertIn(f"vira {certo} tomadas nesta resolução; mande {certo} tomadas", t)
            self.assertIn("regras_das_tomadas", t)
        self.assertEqual(planos.planos._itens, {})

    def test_audio_com_mais_de_30_s(self):
        _fala_wav(config.ENTRADA / "longo.wav", [(31.0, True)])
        midias.registrar("longo.wav", "audio", "mcp", {})
        for chamada, args in (("planejar_video", self.args(3, audio_fala="longo.wav")),
                              ("regras_das_tomadas", {"receita": "fala_camera", "audio_fala": "longo.wav"})):
            r = rpc(chamada, args)
            self.assertTrue(r["isError"])
            t = r["content"][0]["text"]
            self.assertIn("Use até 30 s", t)
            self.assertIn("Encurte o áudio", t)

    def test_audio_que_vira_mais_de_6_tomadas(self):
        with mock.patch.object(validacao, "MAX_TOMADA_AUDIO_POR_MP", ((1.0, 3.0), (1.2, 2.0))):
            for chamada, args in (("planejar_video", self.args(6)), ("regras_das_tomadas", {"receita": "fala_camera", "audio_fala": "voz.wav"})):
                r = rpc(chamada, args)
                self.assertTrue(r["isError"], chamada)
                t = r["content"][0]["text"]
                self.assertIn("Encurte o áudio", t)
                self.assertIn("baixar a resolução", t)
        # Na menor resolucao ela nao ajuda: so resta encurtar
        with mock.patch.object(validacao, "MAX_TOMADAS", 1):
            t = rpc("planejar_video", self.args(1, resolucao="480p"))["content"][0]["text"]
            self.assertIn("Encurte o áudio", t)
            self.assertNotIn("baixar a resolução", t)

    def test_audio_em_cena_texto_e_foto_como_audio(self):
        r = rpc("planejar_video", {"receita": "cena_texto", "formato": "16:9", "cena": CENA, "audio_fala": "voz.wav", "tomadas": [dict(TOMADA_AUDIO)]})
        self.assertTrue(r["isError"])
        self.assertIn("audio_fala", r["content"][0]["text"])
        _imagem(config.ENTRADA / "foto.png", 100, 100)
        midias.registrar("foto.png", "foto", "mcp", {})
        for nome in ("foto.png", "nao_existe.wav"):
            r = rpc("planejar_video", self.args(2, audio_fala=nome))
            self.assertTrue(r["isError"])
            self.assertIn("listar_midias", r["content"][0]["text"])
            self.assertIn("pedir_envio", r["content"][0]["text"])

    def test_resumo_diz_de_onde_vem_o_lugar_e_usa_a_estimativa_do_modo_audio(self):
        # 22/11/2026, teste de verdade: o resumo dizia "um cômodo claro" e o vídeo manteve o café da foto; e o tempo real
        # foi 368 s contra "cerca de 4 min"
        n = len(self.cortes(1.1))
        r, (d, p) = self.planejar(self.args(n))
        t = r["content"][0]["text"]
        self.assertIn("Onde: o fundo da imagem do personagem (para outro lugar, mande cenario)", t)
        self.assertNotIn("cômodo claro", t)
        tomadas = [float(x["duracao"]) for x in p["parametros"]["tomadas"]]
        self.assertIn(planos.estimativas.linha_tempo(planos.estimativas.video_audio(tomadas, 1.1)), t)
        _imagem(config.ENTRADA / "eu.png", 576, 1024)
        midias.registrar("eu.png", "foto", "mcp", {})
        args = {**self.args(n), "foto": "eu.png"}
        args.pop("personagem")
        r, _ = self.planejar(args)
        self.assertFalse(r["isError"], r)
        t = r["content"][0]["text"]
        self.assertIn("Onde: o lugar da foto (para outro lugar, mande cenario)", t)
        self.assertNotIn("cômodo claro", t)

    def test_cenario(self):
        n = len(self.cortes(1.1))
        r = rpc("planejar_video", {**self.args(n), "audio_fala": None, "cenario": "lugar.png"})
        self.assertTrue(r["isError"])
        self.assertIn("A foto do lugar (cenario) só vale junto com audio_fala. Sem áudio, descreva o lugar no campo cena.", r["content"][0]["text"])
        _imagem(config.ENTRADA / "lugar.png", 1024, 576)
        midias.registrar("lugar.png", "foto", "mcp", {})
        r, (d, p) = self.planejar(self.args(n, cenario="lugar.png"))
        self.assertFalse(r["isError"], r)
        self.assertEqual(d["ajustes"]["cenario"], "lugar.png")
        self.assertEqual(p["parametros"]["cenario"], "lugar.png")
        self.assertIn("Lugar (foto): lugar.png", r["content"][0]["text"])
        self.assertNotIn("Onde:", r["content"][0]["text"])
        # O cenario tem que ser foto
        r = rpc("planejar_video", self.args(n, cenario="voz.wav"))
        self.assertTrue(r["isError"])
        self.assertIn("listar_midias", r["content"][0]["text"])

    def test_sem_os_arquivos_da_pele_recusa_antes_de_tudo(self):
        with mock.patch.object(validacao, "faltam_pele", lambda: ["x.safetensors"]):
            for qualidade in ("ugc", "rapido"):
                r = rpc("planejar_video", {**self.args(9, qualidade=qualidade), "audio_fala": "nao_existe.wav"})
                self.assertTrue(r["isError"])
                self.assertIn("x.safetensors", r["content"][0]["text"])
            r = rpc("regras_das_tomadas", {"receita": "fala_camera", "audio_fala": "voz.wav"})
            self.assertTrue(r["isError"])
            self.assertIn("x.safetensors", r["content"][0]["text"])

    def test_modo_audio_aceita_tomadas_sem_duracao_e_sem_fala(self):
        n = len(self.cortes(1.1))
        tomadas = [{"acao": "The character talks.", "camera": "aproximar"} for _ in range(n)]
        r = rpc("planejar_video", self.args(n, tomadas=tomadas))
        self.assertFalse(r["isError"], r)

    def test_modo_normal_sem_duracao_recusa_com_o_numero_da_tomada(self):
        r = rpc("planejar_video", {"receita": "fala_camera", "personagem": "ana", "formato": "9:16",
                                   "tomadas": [TOMADA, {k: v for k, v in TOMADA.items() if k != "duracao"}]})
        self.assertTrue(r["isError"])
        t = r["content"][0]["text"]
        self.assertIn("Falta a duracao na tomada 2", t)
        self.assertIn("regras_das_tomadas", t)

    def test_modo_normal_sem_fala_vale_fala_vazia(self):
        r, (d, p) = self.planejar({"receita": "fala_camera", "personagem": "ana", "formato": "9:16",
                                   "tomadas": [{k: v for k, v in TOMADA.items() if k != "fala"}]})
        self.assertFalse(r["isError"], r)
        self.assertEqual(p["parametros"]["tomadas"][0]["fala"], "")

    def test_camera_parada_no_modo_audio_avisa(self):
        n = len(self.cortes(1.1))
        tomadas = [dict(TOMADA_AUDIO) for _ in range(n)]
        tomadas[-1]["camera"] = "parada"
        r = rpc("planejar_video", self.args(n, tomadas=tomadas))
        self.assertFalse(r["isError"], r)
        self.assertIn(f"Aviso: tomada {n} com câmera parada.", r["content"][0]["text"])
        pedido = {"ajustes": {"audio": "voz.wav", "pele": True, "megapixels": 1.1, "tomadas": [{"camera": "parada", "fala": ""}]}}
        self.assertEqual(len(planos.avisos(pedido, "9:16")), 1)
        pedido["ajustes"]["audio"] = None
        self.assertEqual(planos.avisos(pedido, "9:16"), [])


def _prompt_seis_partes(partes=editar_video.SECOES):
    corpo = {"subject_definitions": "<Subject 1> is the woman from @moca. <Subject 2> is the voice from @voz.",
             "summary": "[reference generation] A 5-second vertical video of <Subject 1> talking.",
             "retention_analysis": "<Subject 1>: fully_preserved - face and outfit stay identical to @moca.",
             "detailed_description": "[Shot 1] <Subject 1> says <d>[Portuguese (Brazil)] Oi, tudo bem?</d>",
             "overall_soundscape": "Her voice, clear and close.", "non_diegetic_music": "N/A"}
    return "\n".join(f"{s}:\n{corpo[s]}" for s in partes)


def _chamada_do_texto(t):
    """O JSON da chamada de planejar_video_livre que regras_do_modo_livre mostra (depois de "Exemplo de chamada")."""
    inicio = t.index("{", t.index("Exemplo de chamada"))
    return json.JSONDecoder().raw_decode(t[inicio:])[0]


class ModoLivre(Base):
    """regras_do_modo_livre, planejar_video_livre e o confirmar_plano por tipo de plano. Nada de ComfyUI: os inicios sao dubles."""

    def setUp(self):
        super().setUp()
        (self.raiz / "envios").mkdir()
        for alvo, nome, valor in ((config, "ENVIOS", self.raiz / "envios"), (video_avancado, "faltam", lambda: [])):
            antigo = getattr(alvo, nome)
            setattr(alvo, nome, valor)
            self.addCleanup(setattr, alvo, nome, antigo)
        self.midia("moca.png", "foto")
        self.midia("voz.wav", "audio")

    def midia(self, nome, tipo):
        (config.ENVIOS if tipo == "video" else config.ENTRADA).joinpath(nome).write_bytes(b"x")
        midias.registrar(nome, tipo, "mcp", {})

    def args(self, **k):
        return {"prompt": _prompt_seis_partes(), "referencias": [{"nome": "moca", "midia": "moca.png"}, {"nome": "voz", "midia": "voz.wav"}],
                "formato": "9:16", "duracao": 5, **k}

    def planejar(self, **k):
        return rpc("planejar_video_livre", self.args(**k))

    def texto(self, r):
        return r["content"][0]["text"]

    def test_as_duas_ferramentas_no_operador_e_no_completo(self):
        for nivel in ("operador", "completo"):
            nomes = {f["name"] for f in mcp_servidor.listar(nivel)}
            self.assertLessEqual({"regras_do_modo_livre", "planejar_video_livre"}, nomes, nivel)
        for f in mcp_servidor.listar("operador"):
            if f["name"] in ("regras_do_modo_livre", "planejar_video_livre"):
                for parte in ("Quando usar", "Quando não usar", "Exemplo"):
                    self.assertIn(parte, f["description"], (f["name"], parte))

    def test_tem_seis_partes(self):
        self.assertTrue(planos.tem_seis_partes(_prompt_seis_partes()))
        self.assertFalse(planos.tem_seis_partes("A woman talks to the camera."))
        self.assertFalse(planos.tem_seis_partes(_prompt_seis_partes(editar_video.SECOES[:5])))
        fora = list(editar_video.SECOES)
        fora[0], fora[1] = fora[1], fora[0]
        self.assertFalse(planos.tem_seis_partes(_prompt_seis_partes(fora)))
        # O nome so vale no comeco da linha
        self.assertFalse(planos.tem_seis_partes(_prompt_seis_partes().replace("\nsummary:", " summary:")))

    def test_regras_na_resolucao_maxima(self):
        r = rpc("regras_do_modo_livre", {"resolucao": "maxima"})
        self.assertFalse(r["isError"], r)
        t = self.texto(r)
        for parte in ("9 fotos", "3 vídeos", "3 áudios", "<d>[Portuguese (Brazil)]", "@"):
            self.assertIn(parte, t)
        for nome in editar_video.SECOES:
            self.assertRegex(t, rf"(?m)^{nome}:")
        # Ate 8 s (a resolucao maxima), nunca 10
        self.assertIn("3, 3,5, 4,25, 5, 6, 7, 8 s", t)
        self.assertNotIn("8, 10", t)
        # O papel de cada tipo
        for parte in ("só o começo", "audio_fala", "NÃO fica preso"):
            self.assertIn(parte, t)

    def test_regras_padrao_e_540p_com_ate_10_s(self):
        t = self.texto(rpc("regras_do_modo_livre", {}))
        self.assertIn("540p", t)
        self.assertIn("8, 10 s", t)
        # Na resolucao padrao o exemplo nao traz resolucao (um modelo local passou a mandar uma sem o usuario pedir)
        self.assertNotIn("resolucao", _chamada_do_texto(t))
        self.assertEqual(_chamada_do_texto(self.texto(rpc("regras_do_modo_livre", {"resolucao": "720p"})))["resolucao"], "720p")

    def test_regras_resolucao_desconhecida(self):
        r = rpc("regras_do_modo_livre", {"resolucao": "4k"})
        self.assertTrue(r["isError"])
        self.assertIn("540p", self.texto(r))

    def test_o_exemplo_das_regras_passa_na_validacao_e_no_planejar(self):
        for resolucao in planos.RESOLUCOES:
            chamada = _chamada_do_texto(self.texto(rpc("regras_do_modo_livre", {"resolucao": resolucao})))
            self.assertTrue(planos.tem_seis_partes(chamada["prompt"]), resolucao)
            # A voz segue a frase testada do prompt_continuacao; nao vira um segundo <Subject>
            self.assertIn("Speaking in the exact same voice as @voz", chamada["prompt"])
            self.assertNotIn("<Subject 2>", chamada["prompt"])
            refs = [{"tipo": "foto" if x["midia"].endswith(".png") else "audio", "nome": x["nome"], "arquivo": x["midia"]}
                    for x in chamada["referencias"]]
            tags = video_avancado.resolver_prompt(chamada["prompt"], refs)
            self.assertIn("<Picture 1>", tags)
            self.assertIn("<Audio 1>", tags)
            self.assertNotIn("@", tags)
            # Com as midias do proprio exemplo registradas, o planejar aceita a chamada como esta
            for x in chamada["referencias"]:
                self.midia(x["midia"], "foto" if x["midia"].endswith(".png") else "audio")
            r = rpc("planejar_video_livre", chamada)
            self.assertFalse(r["isError"], (resolucao, r))
            self.assertNotIn("formato de seis partes", self.texto(r))

    def test_texto_solto_e_recusado(self):
        # Decisao do usuario (22/11/2026): o agente local mandou prompt solto duas vezes e o aviso no resumo nao bastou
        r = self.planejar(prompt="@moca talks to the camera and says <d>[Portuguese (Brazil)] Oi!</d> in the voice of @voz.")
        self.assertTrue(r["isError"], r)
        t = self.texto(r)
        self.assertIn("seis partes", t)
        for nome in editar_video.SECOES:
            self.assertIn(nome, t)
        self.assertIn("regras_do_modo_livre", t)
        self.assertEqual(planos.planos._itens, {})

    def test_so_a_primeira_parte_diz_quais_faltam(self):
        # O prompt que o agente mandou de verdade: so o subject_definitions e o resto em texto corrido
        r = self.planejar(prompt="subject_definitions:\n<Subject 1> is the woman from @moca\n<Subject 1> walks, in the voice of @voz.")
        self.assertTrue(r["isError"], r)
        falta = self.texto(r).split("Falta")[1]
        self.assertNotIn("subject_definitions", falta)
        for nome in editar_video.SECOES[1:]:
            self.assertIn(nome, falta)

    def test_seis_partes_em_ordem_passam_e_fora_de_ordem_sao_recusadas(self):
        self.assertFalse(self.planejar()["isError"])
        fora = list(editar_video.SECOES)
        fora[2], fora[3] = fora[3], fora[2]
        r = self.planejar(prompt=_prompt_seis_partes(fora))
        self.assertTrue(r["isError"], r)
        self.assertIn("nesta ordem", self.texto(r))

    def test_referencia_enviada_e_nao_citada_e_recusada(self):
        sem_voz = _prompt_seis_partes().replace(" <Subject 2> is the voice from @voz.", "")
        r = self.planejar(prompt=sem_voz)
        self.assertTrue(r["isError"], r)
        t = self.texto(r)
        self.assertIn("@voz", t)
        self.assertNotIn("@moca foi", t)
        self.assertIn("Speaking in the exact same voice as @voz", t)
        # Citar pela marca do modelo no lugar do @nome tambem nao vale: o agente usa sempre @nome
        r = self.planejar(prompt=sem_voz.replace("Her voice,", "The voice of <Audio 1>,"))
        self.assertTrue(r["isError"], r)
        self.assertIn("@voz", self.texto(r))
        self.assertEqual(planos.planos._itens, {})

    def test_sem_fala_marcada_o_resumo_avisa(self):
        self.assertNotIn("<d>[", "".join(l for l in self.texto(self.planejar()).splitlines() if l.startswith("Aviso")))
        mudo = _prompt_seis_partes().replace("says <d>[Portuguese (Brazil)] Oi, tudo bem?</d>", "says 'Oi, tudo bem?'")
        r = self.planejar(prompt=mudo)
        self.assertFalse(r["isError"], r)
        self.assertIn("Aviso: o prompt não tem fala marcada", self.texto(r))

    def test_pedido_do_plano_e_o_resumo(self):
        r = self.planejar()
        self.assertFalse(r["isError"], r)
        (codigo,) = planos.planos._itens
        d = planos.planos.usar(codigo)
        self.assertEqual(d["megapixels"], 0.4746)
        self.assertEqual((d["proporcao"], d["duracao"], d["semente"], d["autorizacao"]), ("9:16 (Portrait Widescreen)", 5.0, None, True))
        self.assertEqual(d["referencias"], [{"tipo": "foto", "nome": "moca", "arquivo": "moca.png"},
                                            {"tipo": "audio", "nome": "voz", "arquivo": "voz.wav"}])
        self.assertRegex(d["projeto"], r"^mcp_livre_\d{8}_\d{6}_[0-9a-f]{4}$")
        t = self.texto(r)
        self.assertIn(codigo, t)
        self.assertIn("9:16", t)
        self.assertIn("5 s", t)
        self.assertIn("540p (0,47 MP)", t)
        self.assertIn("@moca: moca.png (foto)", t)
        self.assertIn("@voz: voz.wav (áudio)", t)
        # O prompt inteiro, como escrito (com @nome, nao com as tags)
        self.assertIn(d["prompt"], t)
        self.assertNotIn("<Picture 1>", t)
        self.assertEqual(list((self.raiz / "projetos").iterdir()), [])

    def test_resolucao_e_avisos_no_resumo(self):
        t = self.texto(self.planejar(resolucao="maxima", duracao=8))
        self.assertIn("máxima (1,2 MP)", t)
        self.assertIn("Aviso: resolução máxima", t)

    def test_mencao_sem_referencia_e_recusada(self):
        r = self.planejar(prompt="@fundo behind @moca")
        self.assertTrue(r["isError"])
        self.assertIn("@fundo", self.texto(r))
        self.assertEqual(planos.planos._itens, {})

    def test_midia_inexistente(self):
        r = self.planejar(referencias=[{"nome": "moca", "midia": "nao_existe.png"}])
        self.assertTrue(r["isError"])
        self.assertIn("listar_midias", self.texto(r))

    def test_midia_registrada_cujo_arquivo_foi_apagado(self):
        (config.ENTRADA / "moca.png").unlink()
        r = self.planejar()
        self.assertTrue(r["isError"])
        self.assertIn("listar_midias", self.texto(r))
        self.assertIn("pedir_envio", self.texto(r))
        self.assertEqual(planos.planos._itens, {})

    def test_quantidade_de_referencias(self):
        for i in range(4):
            self.midia(f"v{i}.mp4", "video")
        videos = [{"nome": f"v{i}", "midia": f"v{i}.mp4"} for i in range(4)]
        r = self.planejar(prompt="@v0 @v1 @v2 @v3", referencias=videos)
        self.assertTrue(r["isError"])
        self.assertIn("3 vídeos", self.texto(r))
        self.assertTrue(self.planejar(referencias=[])["isError"])
        tres = _prompt_seis_partes().replace("@moca", "@v0, @v1 and @v2").replace(" <Subject 2> is the voice from @voz.", "")
        self.assertFalse(self.planejar(prompt=tres, referencias=videos[:3])["isError"])

    def test_duracao_fora_da_resolucao_lista_as_aceitas(self):
        r = self.planejar(duracao=10, resolucao="maxima")
        self.assertTrue(r["isError"])
        self.assertIn("3, 3,5, 4,25, 5, 6, 7, 8", self.texto(r))
        self.assertEqual(planos.planos._itens, {})
        self.assertFalse(self.planejar(duracao=10)["isError"])
        self.assertTrue(self.planejar(duracao=4)["isError"])

    def test_formato_e_resolucao_desconhecidos(self):
        for k in ({"formato": "4:3"}, {"resolucao": "4k"}):
            r = self.planejar(**k)
            self.assertTrue(r["isError"], k)

    def test_faltam_arquivos_do_h3(self):
        with mock.patch.object(video_avancado, "faltam", lambda: ["modelo_a.safetensors", "modelo_b.safetensors"]):
            r = self.planejar()
        self.assertTrue(r["isError"])
        self.assertIn("modelo_a.safetensors, modelo_b.safetensors", self.texto(r))
        self.assertEqual(planos.planos._itens, {})

    def test_projeto_existente_ganha_outro_sufixo(self):
        nomes = iter(["aaaa", "bbbb"])
        with mock.patch.object(mcp_planejar.secrets, "token_hex", lambda n: next(nomes) if n == 2 else "abc123"), \
                mock.patch.object(mcp_planejar.time, "strftime", lambda f: "20260101_000000"):
            (self.raiz / "projetos" / "mcp_livre_20260101_000000_aaaa").mkdir()
            self.assertFalse(self.planejar()["isError"])
        (codigo,) = planos.planos._itens
        self.assertEqual(planos.planos.usar(codigo)["projeto"], "mcp_livre_20260101_000000_bbbb")

    def test_confirmar_pelo_tipo_do_plano(self):
        self.planejar()
        (livre,) = planos.planos._itens
        rpc("planejar_video", {"receita": "cena_texto", "formato": "16:9", "qualidade": "ugc", "cena": CENA, "tomadas": [TOMADA_CENA]})
        (receita,) = [c for c in planos.planos._itens if c != livre]
        avancados, imagens = [], []
        with mock.patch.object(acoes, "acao_iniciar_avancado", avancados.append), mock.patch.object(acoes, "acao_iniciar_imagem", imagens.append):
            r = rpc("confirmar_plano", {"codigo_plano": livre})
            self.assertFalse(r["isError"], r)
            self.assertEqual((len(avancados), len(imagens)), (1, 0))
            self.assertIs(avancados[0]["autorizacao"], True)
            self.assertEqual(self.texto(r), f"Começou: {avancados[0]['projeto']}")
            r = rpc("confirmar_plano", {"codigo_plano": receita})
            self.assertFalse(r["isError"], r)
            self.assertEqual((len(avancados), len(imagens)), (1, 1))
            # Gasto: recusa, e nenhum dos dois inicia outra vez
            for codigo in (livre, receita):
                r = rpc("confirmar_plano", {"codigo_plano": codigo})
                self.assertTrue(r["isError"])
                self.assertIn("já foi confirmado", self.texto(r))
            self.assertEqual((len(avancados), len(imagens)), (1, 1))

    def test_resumo_do_modo_livre_traz_tempo_e_fila(self):
        t = self.texto(self.planejar())
        linhas = t.splitlines()
        i = next(n for n, l in enumerate(linhas) if l.startswith("vídeo 9:16"))
        # Depois da linha geral; 5 s a 0,4746 MP (540p) sao 226 s
        self.assertEqual(linhas[i + 1], "Tempo estimado: cerca de 4 min (só a geração; não conta espera na fila).")
        self.assertIn("A placa está livre: começa assim que você confirmar.", t)

    def test_confirmar_livre_que_falha_devolve_o_plano(self):
        self.planejar()
        (codigo,) = planos.planos._itens

        def desligado(d):
            raise Erro("O ComfyUI está desligado.", 409)
        with mock.patch.object(acoes, "acao_iniciar_avancado", desligado):
            r = rpc("confirmar_plano", {"codigo_plano": codigo})
        self.assertTrue(r["isError"])
        self.assertIn("Nada começou", r["content"][0]["text"])
        iniciados = []
        with mock.patch.object(acoes, "acao_iniciar_avancado", iniciados.append):
            self.assertFalse(rpc("confirmar_plano", {"codigo_plano": codigo})["isError"])
        self.assertEqual(len(iniciados), 1)

    def test_tipo_do_plano(self):
        p = planos.Planos()
        a, b = p.criar({}, "r"), p.criar({}, "r", tipo="livre")
        self.assertEqual((p.tipo_de(a), p.tipo_de(b)), ("receita", "livre"))
        p.usar(b)
        self.assertEqual(p.tipo_de(b), "livre")
        with self.assertRaises(Erro):
            p.criar({}, "r", tipo="outro")
        with self.assertRaisesRegex(Erro, "não encontrado"):
            p.tipo_de("naoexiste")

    def test_semente_no_modo_livre(self):
        r = self.planejar(semente=7)
        self.assertFalse(r["isError"], r)
        self.assertEqual(next(iter(planos.planos._itens.values()))["pedido"]["semente"], 7)
        self.assertIn("Semente: 7 (fixa)", self.texto(r))



class Imagem(Base):
    """planejar_imagem e o confirmar_plano do plano de imagem. O ComfyUI nao e chamado: os inicios sao dubles."""

    def setUp(self):
        super().setUp()
        (self.raiz / "envios").mkdir()
        for alvo, nome, valor in ((config, "ENVIOS", self.raiz / "envios"), (validacao, "faltam_texto", lambda modelo: [])):
            antigo = getattr(alvo, nome)
            setattr(alvo, nome, valor)
            self.addCleanup(setattr, alvo, nome, antigo)
        for nome in ("ana.png", "bruno.png", "carro.png", "rua.png", "praia.png"):
            self.midia(nome, "foto")
        self.midia("clip.mp4", "video")

    def midia(self, nome, tipo):
        (config.ENVIOS if tipo == "video" else config.ENTRADA).joinpath(nome).write_bytes(b"x")
        midias.registrar(nome, tipo, "mcp", {})

    def planejar(self, **k):
        r = rpc("planejar_imagem", {"prompt": "um gato astronauta, foto realista", **k})
        return r, (next(iter(planos.planos._itens.values()))["pedido"] if planos.planos._itens else None)

    def texto(self, r):
        return r["content"][0]["text"]

    def test_as_duas_ferramentas_no_operador_e_no_completo(self):
        for nivel in ("operador", "completo"):
            self.assertLessEqual({"planejar_imagem", "usar_resultado"}, {f["name"] for f in mcp_servidor.listar(nivel)}, nivel)
        for f in mcp_servidor.listar("operador"):
            if f["name"] in ("planejar_imagem", "usar_resultado"):
                for parte in ("Quando usar", "Quando não usar", "Exemplo"):
                    self.assertIn(parte, f["description"], (f["name"], parte))
        d = next(f for f in mcp_servidor.listar("operador") if f["name"] == "planejar_imagem")
        # O prompt deixou de ser obrigatorio no esquema em 23/11/2026: com estilo ele e opcional (a conferencia fica no planejar_imagem)
        self.assertEqual(d["inputSchema"]["required"], [])
        # Um exemplo sem campos opcionais, e o agente nunca ve nome de arquivo de modelo
        self.assertIn('{"prompt": "um gato astronauta, foto realista"}', d["description"])
        for arquivo in (".safetensors", "z_image_turbo", "klein_edit", "qwen21_edit"):
            self.assertNotIn(arquivo, d["description"])
        for parte in ("sem imagens", "1 imagem", "2 a 4"):
            self.assertIn(parte, d["description"].lower())

    def test_sem_imagens_gera_do_texto_com_o_z_image_turbo(self):
        r, pedido = self.planejar()
        self.assertFalse(r["isError"], r)
        a = pedido["ajustes"]
        self.assertRegex(pedido["projeto"], r"^mcp_imagem_\d{8}_\d{6}_[0-9a-f]{4}$")
        self.assertEqual((a["modelo"], a["passos"], a["quantidade"], a["proporcao"], a["megapixels"]), ("z_image_turbo", 8, 1, "2:3 (Portrait Photo)", 0.9))
        self.assertEqual((a["prompt"], a["partida"], a["referencia"], a["referencias"]), ("um gato astronauta, foto realista", None, None, []))
        self.assertEqual(set(pedido), {"projeto", "ajustes"})  # o fluxo da pagina nao tem autorizacao
        self.assertEqual(next(iter(planos.planos._itens.values()))["tipo"], "imagem")
        # O pedido passa na validacao da pagina como esta
        self.assertEqual(acoes.preparar_texto(pedido)["modelo"], "z_image_turbo")
        t = self.texto(r)
        self.assertIn(f"Plano {next(iter(planos.planos._itens))} (vale 30 min, projeto {pedido['projeto']})", t)
        self.assertIn("gerar 1 imagem a partir do texto", t)
        self.assertIn("Modelo: Z-Image Turbo", t)
        self.assertIn("Formato: 2:3", t)
        self.assertIn("Tempo estimado: cerca de", t)
        self.assertIn("A placa está livre", t)
        self.assertIn("um gato astronauta, foto realista", t)
        self.assertIn("confirmar_plano", t)
        self.assertNotIn("z_image_turbo", t)

    def test_formato_e_quantidade(self):
        r, pedido = self.planejar(formato="16:9", quantidade=3)
        self.assertFalse(r["isError"], r)
        self.assertEqual((pedido["ajustes"]["proporcao"], pedido["ajustes"]["quantidade"]), ("16:9 (Widescreen)", 3))
        t = self.texto(r)
        self.assertIn("gerar 3 imagens", t)
        self.assertIn("Formato: 16:9", t)
        # Cada formato do enum e uma proporcao da pagina
        for formato, proporcao in planos.FORMATOS_IMAGEM.items():
            self.assertIn(proporcao, validacao.PROPORCOES, formato)

    def test_uma_imagem_edita_com_o_klein(self):
        r, pedido = self.planejar(prompt="change the shirt to red, keep the same face", imagens=["ana.png"], formato="16:9")
        self.assertFalse(r["isError"], r)
        a = pedido["ajustes"]
        self.assertEqual((a["modelo"], a["passos"], a["partida"], a["referencia"], a["referencias"]), ("klein_edit", 4, "ana.png", None, []))
        self.assertEqual(acoes.preparar_texto(pedido)["partida"], "ana.png")
        t = self.texto(r)
        self.assertIn("editar a imagem", t)
        self.assertIn("Modelo: Editar imagem (FLUX.2 Klein", t)
        self.assertIn("image 1: ana.png", t)
        # Na edicao a saida segue a imagem 1: o formato pedido nao aparece
        self.assertIn("o da image 1", t)
        self.assertNotIn("16:9", t)
        self.assertNotIn("klein_edit", t)

    def test_varias_imagens_juntam_com_o_qwen_na_ordem_enviada(self):
        r, pedido = self.planejar(prompt="Put the woman of image 1 next to the car of image 2.", imagens=["ana.png", "carro.png", "rua.png"])
        self.assertFalse(r["isError"], r)
        a = pedido["ajustes"]
        self.assertEqual((a["modelo"], a["passos"], a["partida"], a["referencia"], a["referencias"]), ("qwen21_edit", 8, "ana.png", "carro.png", ["rua.png"]))
        p = acoes.preparar_texto(pedido)
        self.assertEqual((p["partida"], p["referencia"], p["referencias"]), ("ana.png", "carro.png", ["rua.png"]))
        t = self.texto(r)
        self.assertIn("juntar 3 imagens", t)
        for linha in ("image 1: ana.png", "image 2: carro.png", "image 3: rua.png"):
            self.assertIn(linha, t)
        self.assertLess(t.index("image 1: ana.png"), t.index("image 3: rua.png"))
        planos.planos._itens.clear()
        r, pedido = self.planejar(imagens=["ana.png", "bruno.png", "carro.png", "rua.png"])
        self.assertFalse(r["isError"], r)
        a = pedido["ajustes"]
        self.assertEqual((a["partida"], a["referencia"], a["referencias"]), ("ana.png", "bruno.png", ["carro.png", "rua.png"]))

    def test_o_tempo_estimado_cresce_com_a_quantidade_e_a_fila_aparece(self):
        um = self.texto(self.planejar(quantidade=1)[0])
        # A frase da fila vem da tarefa: aqui uma geracao em andamento
        tarefa.tarefa.rodando.return_value = True
        quatro = self.texto(self.planejar(quantidade=4)[0])
        self.assertIn("1 geração em andamento", quatro)
        self.assertNotIn("1 geração em andamento", um)
        self.assertNotEqual(um.split("Tempo estimado:")[1].split("\n")[0], quatro.split("Tempo estimado:")[1].split("\n")[0])

    def test_recusas_dizem_o_proximo_passo_e_nao_criam_plano(self):
        casos = [({"imagens": ["clip.mp4"]}, "listar_midias"), ({"imagens": ["nao_existe.png"]}, "pedir_envio"), ({"imagens": [3]}, "imagens"),
                 ({"imagens": ["ana.png"] * 5}, "0 a 4"), ({"imagens": "ana.png"}, "imagens"),
                 ({"prompt": ""}, "prompt"), ({"prompt": "   "}, "prompt"), ({"prompt": 3}, "prompt"),
                 ({"quantidade": 5}, "1 a 4"), ({"quantidade": 0}, "1 a 4"), ({"quantidade": "2"}, "1 a 4"), ({"quantidade": True}, "1 a 4"),
                 ({"formato": "5:4"}, "21:9")]
        for k, esperado in casos:
            r = rpc("planejar_imagem", {"prompt": "um gato", **k})
            self.assertTrue(r["isError"], k)
            self.assertIn(esperado, self.texto(r), k)
        self.assertTrue(rpc("planejar_imagem", {})["isError"])
        self.assertEqual(planos.planos._itens, {})

    def test_campo_com_o_nome_de_outra_ferramenta_e_recusado_e_manda_usar_imagens(self):
        # O modelo local mandou "foto" (o campo das outras ferramentas) e o plano saiu como GERAR do texto, sem a foto
        for campo, valor in (("foto", "ana.png"), ("fotos", ["ana.png"]), ("imagem", "ana.png"), ("partida", "ana.png"),
                             ("referencia", "bruno.png"), ("referencias", ["bruno.png"])):
            r = rpc("planejar_imagem", {"prompt": "change the shirt to red", campo: valor})
            self.assertTrue(r["isError"], campo)
            self.assertEqual(self.texto(r), "As fotos vão no campo imagens (uma lista de nomes de listar_midias). Chame planejar_imagem de novo com imagens.", campo)
        self.assertEqual(planos.planos._itens, {})
        # Com o campo certo, o mesmo pedido edita a foto
        r, pedido = self.planejar(prompt="change the shirt to red", imagens=["ana.png"])
        self.assertEqual(pedido["ajustes"]["modelo"], "klein_edit")
        d = next(f for f in mcp_servidor.listar("operador") if f["name"] == "planejar_imagem")["description"]
        self.assertNotIn("quantidade ou imagens", d)

    def test_modelo_que_falta_no_comfyui_nao_mostra_nome_de_arquivo(self):
        validacao.faltam_texto = lambda modelo: ["flux2_klein_9b.safetensors"]
        r = rpc("planejar_imagem", {"prompt": "um gato"})
        self.assertTrue(r["isError"])
        self.assertNotIn(".safetensors", self.texto(r))
        self.assertIn("não está instalado", self.texto(r))
        self.assertEqual(planos.planos._itens, {})

    def test_o_erro_da_validacao_da_pagina_vem_com_o_proximo_passo(self):
        r = rpc("planejar_imagem", {"prompt": "<>"})  # a pagina limpa os sinais e fica vazio
        self.assertTrue(r["isError"])
        self.assertIn("Escreva o que deve aparecer", self.texto(r))
        self.assertIn("planejar_imagem", self.texto(r))

    def test_planejar_nao_olha_o_comfyui_nem_cria_pasta(self):
        def ocupado(*a, **k):
            raise Erro("O ComfyUI está ocupado com outra tarefa. Espere terminar.", 409)
        with mock.patch.object(acoes, "exigir_comfy_livre", ocupado):
            r, pedido = self.planejar()
        self.assertFalse(r["isError"], r)
        self.assertEqual(list(config.PROJETOS.iterdir()), [])

    def test_preparar_texto_confere_o_que_a_pagina_confere(self):
        ok = {"projeto": "meu_projeto", "ajustes": {"prompt": "um gato"}}
        self.assertEqual(acoes.preparar_texto(ok)["tipo"], "texto")
        self.assertEqual(list(config.PROJETOS.iterdir()), [])
        (config.PROJETOS / "ja_existe").mkdir()
        with self.assertRaises(Erro) as e:
            acoes.preparar_texto({**ok, "projeto": "ja_existe"})
        self.assertEqual(e.exception.codigo, 409)
        with self.assertRaises(Erro):
            acoes.preparar_texto({**ok, "projeto": "../fora"})
        with self.assertRaises(Erro):
            acoes.preparar_texto({**ok, "ajustes": {"prompt": ""}})

    def test_a_acao_da_pagina_segue_conferindo_o_comfyui_antes_da_validacao(self):
        chamadas = []

        def ocupado(*a, **k):
            chamadas.append("comfy")
            raise Erro("O ComfyUI está ocupado com outra tarefa. Espere terminar.", 409)
        with mock.patch.object(acoes, "exigir_comfy_livre", ocupado), mock.patch.object(tarefa.tarefa, "iniciar_texto", create=True) as iniciar:
            # Pedido invalido com o ComfyUI ocupado: a recusa do ComfyUI vem primeiro, como sempre foi
            with self.assertRaises(Erro) as e:
                acoes.acao_iniciar_texto({"projeto": "novo", "ajustes": {"prompt": ""}})
            self.assertIn("ocupado", e.exception.mensagem)
            # A pasta que ja existe vem antes do ComfyUI
            (config.PROJETOS / "velho").mkdir()
            with self.assertRaises(Erro) as e:
                acoes.acao_iniciar_texto({"projeto": "velho", "ajustes": {"prompt": "x"}})
            self.assertEqual(e.exception.codigo, 409)
            self.assertIn("Já existe", e.exception.mensagem)
        self.assertEqual(chamadas, ["comfy"])
        iniciar.assert_not_called()
        # Livre: grava o projeto e inicia
        with mock.patch.object(acoes, "exigir_comfy_livre", lambda *a, **k: None), mock.patch.object(tarefa.tarefa, "iniciar_texto", create=True) as iniciar:
            acoes.acao_iniciar_texto({"projeto": "novo", "ajustes": {"prompt": "um gato"}})
        iniciar.assert_called_once_with("novo")
        self.assertTrue((config.PROJETOS / "novo" / "interface.json").is_file())

    def confirmar(self, tipo, pedido=None):
        codigo = planos.planos.criar(pedido or {"projeto": f"proj_{tipo}"}, "resumo", tipo=tipo)
        return codigo, rpc("confirmar_plano", {"codigo_plano": codigo})

    def test_confirmar_inicia_cada_tipo_pela_sua_acao(self):
        for tipo, esperada in (("imagem", "acao_iniciar_texto"), ("livre", "acao_iniciar_avancado"), ("receita", "acao_iniciar_imagem")):
            chamadas = {n: [] for n in ("acao_iniciar_texto", "acao_iniciar_avancado", "acao_iniciar_imagem")}
            with mock.patch.multiple(acoes, **{n: v.append for n, v in chamadas.items()}):
                _, r = self.confirmar(tipo)
            self.assertFalse(r["isError"], (tipo, r))
            self.assertEqual(self.texto(r), f"Começou: proj_{tipo}")
            for nome, lista in chamadas.items():
                self.assertEqual(lista, [{"projeto": f"proj_{tipo}"}] if nome == esperada else [], (tipo, nome))

    def test_confirmar_plano_de_imagem_entra_na_fila(self):
        tarefa.tarefa.fila.resumo.return_value = {"pausada": False, "motivo": "", "intervalo": 15, "proxima_em": None,
                                                  "itens": [{"projeto": "outro"}, {"projeto": "proj_imagem"}]}
        with mock.patch.object(acoes, "acao_iniciar_texto", lambda p: None):
            _, r = self.confirmar("imagem")
        self.assertEqual(self.texto(r), "Entrou na fila: proj_imagem (posição 2)")

    def test_confirmar_na_fila_pausada_diz_que_so_comeca_depois_de_retomar(self):
        tarefa.tarefa.rodando.return_value = True
        tarefa.tarefa.fila.resumo.return_value = {"pausada": True, "motivo": "Parado pelo agente (MCP).", "intervalo": 15, "proxima_em": None,
                                                  "itens": [{"projeto": "outro"}, {"projeto": "proj_imagem"}]}
        with mock.patch.object(acoes, "acao_iniciar_texto", lambda p: None):
            _, r = self.confirmar("imagem")
        self.assertFalse(r["isError"], r)
        self.assertEqual(self.texto(r), "Entrou na fila: proj_imagem (posição 2). A fila está pausada: só começa depois de retomar_fila; pergunte ao usuário.")

    def test_plano_de_tipo_desconhecido_e_recusado_sem_chamar_acao_nenhuma(self):
        codigo = planos.planos.criar({"projeto": "proj_futuro"}, "resumo", tipo="imagem")
        planos.planos._itens[codigo]["tipo"] = "futuro"  # um plano gravado por uma versao mais nova do estudio
        with mock.patch.multiple(acoes, acao_iniciar_texto=mock.DEFAULT, acao_iniciar_avancado=mock.DEFAULT, acao_iniciar_imagem=mock.DEFAULT) as acoes_falsas:
            r = rpc("confirmar_plano", {"codigo_plano": codigo})
        self.assertTrue(r["isError"])
        self.assertEqual(self.texto(r), "Este plano é de uma versão diferente do estúdio. Planeje de novo.")
        for nome, falsa in acoes_falsas.items():
            falsa.assert_not_called()

    def test_confirmar_plano_de_imagem_que_falha_diz_que_nada_comecou(self):
        def ocupado(p):
            raise Erro("O ComfyUI está ocupado com outra tarefa. Espere terminar.", 409)
        with mock.patch.object(acoes, "acao_iniciar_texto", ocupado):
            codigo, r = self.confirmar("imagem")
        self.assertTrue(r["isError"])
        t = self.texto(r)
        self.assertIn("Nada começou: a imagem não está sendo gerada", t)
        self.assertNotIn("vídeo", t)
        self.assertIn(f"O plano {codigo} continua valendo", t)
        # O plano nao foi gasto: confirma de novo quando o ComfyUI liberar
        with mock.patch.object(acoes, "acao_iniciar_texto", lambda p: None):
            self.assertFalse(rpc("confirmar_plano", {"codigo_plano": codigo})["isError"])

    def test_o_plano_planejado_confirma_com_o_pedido_do_planejar(self):
        r, pedido = self.planejar(imagens=["ana.png"])
        codigo = next(iter(planos.planos._itens))
        iniciados = []
        with mock.patch.object(acoes, "acao_iniciar_texto", iniciados.append):
            self.assertEqual(self.texto(rpc("confirmar_plano", {"codigo_plano": codigo})), f"Começou: {pedido['projeto']}")
        self.assertEqual(iniciados, [pedido])

    def test_semente_na_imagem(self):
        r, pedido = self.planejar(semente=42)
        self.assertFalse(r["isError"], r)
        self.assertEqual(pedido["ajustes"]["semente"], 42)
        self.assertIn("Semente: 42 (fixa)", self.texto(r))
        planos.planos._itens.clear()
        r, _ = self.planejar(imagens=["ana.png"], estilo="realista", prompt="", semente=5)
        self.assertFalse(r["isError"], r)
        self.assertIn("Semente: 5 (fixa)", self.texto(r))



if __name__ == "__main__":
    unittest.main()
