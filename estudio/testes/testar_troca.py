"""Testes do grafo da troca de personagem. Nao usam o ComfyUI nem a placa.

Uso: python -I testar_troca.py
"""
import json, sys, tempfile, types, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import acabamento, config, validacao
import trocar_personagem
from trocar_personagem import GRAFO, Progresso, ampliar_com_esrgan, montar_grafo, segunda_passagem

P = {"duracao": 3, "proporcao": "16:9 (Widescreen)", "megapixels": 0.2, "upscale": True, "upscale_mesma": False, "upscale_megapixels": 1.0, "upscaler": "h3_upscaler_lms_v0.1.safetensors",
     "audio_original": True, "modelo": "minimax_h3_ref2va_pruned_int8_convrot.safetensors", "troca": ["minimax_h3_character_swap_v1.1_ref2va_fro.safetensors", 1.0],
     "turbo": ["minimax_h3_dmd_ref2va_8step_turbo_pruned.safetensors", 1.0], "nitidez": ["minimax_h3_lms_v1.0_r64.safetensors", 0.7], "pouca_vram": False, "dividir_blocos": False,
     "passos": 8, "agendador": "simple", "sampler": "euler", "semente": 42}
BASE = json.loads(GRAFO.read_text(encoding="utf-8"))


def grafo(**mudancas):
    return montar_grafo(BASE, {**P, **mudancas}, "v.mp4", "f.png", "troca/x", 42, 7)


def ligacoes_validas(g):
    return all(v[0] in g for n in g.values() for v in n["inputs"].values() if isinstance(v, list) and len(v) == 2 and isinstance(v[1], int))


class Testes(unittest.TestCase):
    def test_modelo_nao_aponta_para_nenhuma_midia(self):
        self.assertEqual(BASE["320"]["inputs"]["video"], "")
        self.assertEqual(BASE["349"]["inputs"]["image"], "")

    def test_entradas_e_padroes(self):
        g = grafo()
        self.assertEqual(g["320"]["inputs"]["video"], "v.mp4")
        self.assertEqual(g["349"]["inputs"]["image"], "f.png")
        self.assertEqual(g["13"]["inputs"]["noise_seed"], 42)
        self.assertEqual(g["826"]["inputs"]["sampling_mode.seed"], 7)
        self.assertIs(g["595"]["inputs"]["value"], True)
        self.assertIs(g["860"]["inputs"]["value"], False)
        self.assertTrue(ligacoes_validas(g))

    def test_cadeia_padrao_sem_otimizacoes(self):
        g = grafo()
        self.assertNotIn("59", g)
        self.assertNotIn("60", g)
        self.assertEqual(g["64"]["inputs"]["model"], ["58", 0])
        self.assertEqual(g["586"]["inputs"]["model"], ["64", 0])
        self.assertEqual(g["484"]["inputs"]["model"], ["586", 0])
        self.assertEqual(g["534"]["inputs"]["model"], ["484", 0])

    def test_otimizacoes_ligadas(self):
        g = grafo(pouca_vram=True, dividir_blocos=True)
        self.assertEqual(g["59"]["inputs"]["model"], ["58", 0])
        self.assertEqual(g["60"]["inputs"]["model"], ["59", 0])
        self.assertEqual(g["64"]["inputs"]["model"], ["60", 0])

    def test_sem_nitidez_o_upscale_usa_a_lora_de_troca(self):
        g = grafo(nitidez=None)
        self.assertNotIn("484", g)
        self.assertEqual(g["534"]["inputs"]["model"], ["586", 0])
        self.assertTrue(ligacoes_validas(g))

    def test_sem_turbo_a_troca_liga_na_cadeia_anterior(self):
        g = grafo(turbo=None)
        self.assertNotIn("64", g)
        self.assertEqual(g["586"]["inputs"]["model"], ["58", 0])
        self.assertTrue(ligacoes_validas(g))

    def test_upscale_desligado_e_audio_vazio(self):
        g = grafo(upscale=False, audio_original=False)
        self.assertIs(g["595"]["inputs"]["value"], False)
        self.assertIs(g["860"]["inputs"]["value"], True)

    def test_mesma_resolucao(self):
        self.assertIs(grafo(upscale_mesma=True)["597"]["inputs"]["value"], True)

    def test_saidas_ficam_na_pasta_do_projeto(self):
        g = grafo()
        self.assertEqual(g["539"]["inputs"]["filename_prefix"], "troca/x/final")
        self.assertEqual(g["791"]["inputs"]["filename_prefix"], "troca/x/comparativo")
        self.assertNotIn("751", g)

    def test_comparativo_sem_o_prompt_escrito(self):
        g = grafo()
        self.assertNotIn("780", g)
        self.assertEqual(g["791"]["inputs"]["images"], ["810", 0])
        self.assertTrue(ligacoes_validas(g))

    def test_sem_loras_de_estilo_o_grafo_nao_muda(self):
        self.assertEqual(grafo(), grafo(loras=[]))
        self.assertFalse([k for k in grafo() if k.startswith("91")])

    def test_loras_de_estilo_depois_da_troca_nas_duas_passagens(self):
        g = grafo(loras=[["estilo_a.safetensors", 0.8], ["estilo_b.safetensors", 0.5]])
        self.assertEqual(g["910"]["inputs"], {"model": ["586", 0], "lora_name": "estilo_a.safetensors", "strength_model": 0.8})
        self.assertEqual(g["911"]["inputs"], {"model": ["910", 0], "lora_name": "estilo_b.safetensors", "strength_model": 0.5})
        # Primeira passagem (guia e agendador) e a LoRA de nitidez do upscale usam a ultima de estilo
        for no in ("11", "181", "484"):
            self.assertEqual(g[no]["inputs"]["model"], ["911", 0], no)
        self.assertEqual(g["534"]["inputs"]["model"], ["484", 0])
        self.assertTrue(ligacoes_validas(g))

    def test_loras_de_estilo_sem_nitidez_e_com_roupa_da_foto(self):
        g = grafo(loras=[["estilo_a.safetensors", 1.0]], nitidez=None, roupa="foto")
        self.assertEqual(g["534"]["inputs"]["model"], ["910", 0])
        self.assertEqual(g["11"]["inputs"]["model"], ["910", 0])
        self.assertTrue(ligacoes_validas(g))

    def test_nao_altera_o_modelo_em_memoria(self):
        antes = json.dumps(BASE, sort_keys=True)
        grafo(turbo=None, nitidez=None)
        self.assertEqual(json.dumps(BASE, sort_keys=True), antes)


def estado(**nos):
    """Mesmo formato do aviso progress_state do ComfyUI."""
    return {"type": "progress_state", "data": {"prompt_id": "x", "nodes": {k[1:]: {"state": v[0], "value": v[1], "max": v[2]} for k, v in nos.items()}}}


class TestesProgresso(unittest.TestCase):
    def setUp(self):
        self.pasta = tempfile.TemporaryDirectory()
        self.addCleanup(self.pasta.cleanup)
        self.mon = types.SimpleNamespace(rotulo="")

    def novo(self, upscale):
        self.arq = Path(self.pasta.name) / "progresso.json"
        return Progresso(self.arq, upscale, self.mon)

    def test_etapas_com_upscale(self):
        p = self.novo(True)
        self.assertEqual(p.etapa, "descrever")
        p.evento(estado(n14=("running", 0, 8)))
        self.assertEqual((p.etapa, self.mon.rotulo), ("primeira", "primeira"))
        p.evento(estado(n14=("running", 3, 8)))
        self.assertEqual((p.valor, p.maximo), (3, 8))
        p.evento(estado(n14=("finished", 8, 8), n530=("running", 0, 1)))
        self.assertEqual((p.etapa, p.valor, p.maximo), ("ampliar", 0, 0))
        p.evento(estado(n537=("running", 2, 3)))
        self.assertEqual((p.etapa, p.valor, p.maximo), ("ampliar", 2, 3))
        p.evento(estado(n538=("running", 0, 1)))
        self.assertEqual((p.etapa, p.valor, p.maximo), ("montar", 0, 0))
        dados = json.loads(self.arq.read_text(encoding="utf-8"))
        self.assertEqual(dados["etapa"], "montar")
        self.assertEqual(set(dados["tempos"]), {"descrever", "primeira", "ampliar"})

    def test_etapas_sem_upscale(self):
        p = self.novo(False)
        p.evento(estado(n14=("running", 1, 8)))
        p.evento(estado(n45=("running", 0, 1)))
        self.assertEqual(p.etapa, "montar")

    def test_decodificar_a_primeira_passagem_nao_pula_o_upscale(self):
        p = self.novo(True)
        p.evento(estado(n14=("running", 1, 8)))
        p.evento(estado(n45=("running", 0, 1)))
        self.assertEqual(p.etapa, "primeira")

    def test_nao_volta_de_etapa_e_ignora_outros_avisos(self):
        p = self.novo(True)
        p.evento(estado(n538=("running", 0, 1)))
        p.evento(estado(n14=("running", 1, 8)))
        p.evento({"type": "crystools.monitor", "data": {"cpu_utilization": 1}})
        self.assertEqual(p.etapa, "montar")


class AmpliarComEsrgan(unittest.TestCase):
    """A segunda passagem derrubou a placa 3 vezes em 11/11/2026; o ESRGAN depois da troca nunca caiu."""

    def test_esrgan_desliga_a_segunda_passagem_no_grafo(self):
        self.assertIs(grafo(esrgan=True)["595"]["inputs"]["value"], False)
        self.assertIs(grafo(esrgan=False)["595"]["inputs"]["value"], True)
        # Projeto antigo, sem a chave: segue como foi pedido
        self.assertIs(grafo()["595"]["inputs"]["value"], True)
        self.assertFalse(segunda_passagem({"upscale": True, "esrgan": True}))
        self.assertFalse(segunda_passagem({"upscale": False}))
        self.assertTrue(segunda_passagem({"upscale": True}))

    def test_padrao_e_o_esrgan_sem_segunda_passagem(self):
        self.assertIs(validacao.PADRAO_TROCA["esrgan"], True)
        self.assertIs(validacao.PADRAO_TROCA["upscale"], False)

    def opcoes(self):
        return {"modelos": [P["modelo"]], "samplers": ["euler"], "agendadores": ["simple"], "upscalers": [P["upscaler"]],
                "loras_troca": {"troca": [P["troca"][0]], "turbo": [P["turbo"][0]], "nitidez": [P["nitidez"][0]]}, "loras_estilo": []}

    def test_validacao_com_esrgan_tira_o_upscale(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(validacao.ambiente, "ler_opcoes", return_value=self.opcoes()):
            modelo = Path(d) / "RealESRGAN_x2plus.pth"
            modelo.write_bytes(b"x")
            with mock.patch.object(validacao, "MODELO_ESRGAN", modelo):
                r = validacao.validar_troca({**P, "esrgan": True, "upscale": True})
                self.assertEqual((r["esrgan"], r["upscale"]), (True, False))
                r = validacao.validar_troca({**P, "esrgan": False, "upscale": True})
                self.assertEqual((r["esrgan"], r["upscale"]), (False, True))
                self.assertIs(validacao.validar_troca({**P, "esrgan": "sim"})["esrgan"], False)
            with mock.patch.object(validacao, "MODELO_ESRGAN", Path(d) / "nao_existe.pth"):
                with self.assertRaises(validacao.Erro):
                    validacao.validar_troca({**P, "esrgan": True})
                validacao.validar_troca({**P, "esrgan": False})

    def test_duracao_maxima_por_resolucao(self):
        self.assertEqual([validacao.duracao_max_troca(mp) for mp in validacao.QUALIDADES_TROCA], [5, 5, 5, 3.5])

    def test_ampliar_guarda_a_primeira_passagem_e_troca_o_final(self):
        with tempfile.TemporaryDirectory() as d:
            pasta = Path(d)
            (pasta / "final.mp4").write_bytes(b"primeira")
            chamadas = []

            def esrgan(quadros, total, audio, saida, proporcao, avisar, fps):
                chamadas.append((total, Path(audio).name, proporcao, fps))
                avisar(12, total)
                Path(saida).write_bytes(b"ampliado")
            progresso = types.SimpleNamespace(esrgan=lambda v, m: chamadas.append(("passo", v, m)))
            with mock.patch.multiple(acabamento, contar_quadros=lambda a: 73, quadros_de=lambda a: iter(()), liberar_comfy=lambda: None, esrgan=esrgan, fps_de=lambda a: "24"):
                segundos = ampliar_com_esrgan(pasta, {**P, "esrgan": True}, progresso)
            self.assertIsNotNone(segundos)
            self.assertEqual((pasta / "final.mp4").read_bytes(), b"ampliado")
            self.assertEqual((pasta / "primeira_passagem.mp4").read_bytes(), b"primeira")
            self.assertIn((73, "primeira_passagem.mp4", P["proporcao"], "24"), chamadas)
            self.assertIn(("passo", 12, 73), chamadas)
            self.assertFalse((pasta / "final_parte.mp4").exists())

    def test_se_o_esrgan_falhar_fica_a_primeira_passagem(self):
        with tempfile.TemporaryDirectory() as d:
            pasta = Path(d)
            (pasta / "final.mp4").write_bytes(b"primeira")

            def esrgan(quadros, total, audio, saida, *a, **k):
                Path(saida).write_bytes(b"pela metade")
                raise RuntimeError("ffmpeg falhou")
            with mock.patch.multiple(acabamento, contar_quadros=lambda a: 73, quadros_de=lambda a: iter(()), liberar_comfy=lambda: None, esrgan=esrgan, fps_de=lambda a: "24"):
                self.assertIsNone(ampliar_com_esrgan(pasta, P, types.SimpleNamespace(esrgan=lambda v, m: None)))
            self.assertEqual((pasta / "final.mp4").read_bytes(), b"primeira")
            self.assertFalse((pasta / "final_parte.mp4").exists())

    def test_progresso_tem_a_etapa_do_esrgan(self):
        with tempfile.TemporaryDirectory() as d:
            mon = types.SimpleNamespace(rotulo="")
            arq = Path(d) / "progresso.json"
            p = Progresso(arq, False, mon)
            p.evento(estado(n14=("running", 1, 8)))
            p.evento(estado(n45=("running", 0, 1)))
            p.esrgan(24, 73)
            dados = json.loads(arq.read_text(encoding="utf-8"))
            self.assertEqual((dados["etapa"], dados["valor"], dados["maximo"], mon.rotulo), ("esrgan", 24, 73, "esrgan"))
            self.assertIn("montar", dados["tempos"])
            # Um aviso atrasado do ComfyUI nao volta a etapa
            p.evento(estado(n45=("running", 0, 1)))
            self.assertEqual(p.etapa, "esrgan")


class IniciarTroca(unittest.TestCase):
    """A 0,8 MP, uma troca de 5 s caiu na primeira passagem em 11/11/2026: o limite ali e 3,5 s."""

    def setUp(self):
        import acoes, tarefa
        self.acoes = acoes
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        raiz = Path(d.name)
        for nome in ("projetos", "envios", "entrada"):
            (raiz / nome).mkdir()
        (raiz / "envios" / "v.mp4").write_bytes(b"x")
        (raiz / "entrada" / "f.png").write_bytes(b"x")
        self.lancados = []
        for alvo, nome, valor in ((config, "PROJETOS", raiz / "projetos"), (config, "ENVIOS", raiz / "envios"), (config, "ENTRADA", raiz / "entrada"),
                                  (acoes, "exigir_comfy_livre", lambda: None), (acoes, "examinar_video", lambda v: {"quadros": 240, "duracao": 10.0, "audio": True}),
                                  (acoes, "validar_troca", lambda a: {**P, **a}),
                                  (tarefa, "tarefa", types.SimpleNamespace(rodando=lambda: False, iniciar_troca=self.lancados.append, projeto=None))):
            m = mock.patch.object(alvo, nome, valor)
            m.start()
            self.addCleanup(m.stop)

    def iniciar(self, nome, duracao, megapixels, **ajustes):
        self.acoes.acao_iniciar_troca({"projeto": nome, "video": "v.mp4", "foto": "f.png", "duracao": duracao, "autorizacao": True, "ajustes": {"megapixels": megapixels, **ajustes}})

    def test_limite_pela_resolucao(self):
        # P tem a segunda passagem ligada: sem janelas, vale o limite de uma passada
        self.iniciar("a", 5, 0.5)
        self.iniciar("b", 3.5, 0.8)
        with self.assertRaises(validacao.Erro) as e:
            self.iniciar("c", 5, 0.8)
        self.assertIn("3,5 s a 0,8 MP", e.exception.mensagem)
        self.assertEqual(self.lancados, ["a", "b"])

    def test_sem_upscale_passa_em_janelas_ate_o_tamanho_do_video(self):
        self.iniciar("a", 10, 0.8, upscale=False)
        self.iniciar("b", 7.5, 0.2, upscale=False)
        # O video tem 240 quadros (10 s)
        with self.assertRaises(validacao.Erro):
            self.iniciar("c", 10.5, 0.2, upscale=False)
        with self.assertRaises(validacao.Erro):
            self.iniciar("d", 15.5, 0.2, upscale=False)
        self.assertEqual(self.lancados, ["a", "b"])

    def test_inicio_do_trecho(self):
        # Video de 10 s: 6 s a partir de 4 s cabem; 6 s a partir de 4,5 s nao
        self.acoes.acao_iniciar_troca({"projeto": "a", "video": "v.mp4", "foto": "f.png", "duracao": 6, "inicio": 4, "autorizacao": True, "ajustes": {"megapixels": 0.2, "upscale": False}})
        self.assertEqual(json.loads((config.PROJETOS / "a" / validacao.PARAMETROS).read_text(encoding="utf-8"))["inicio"], 4)
        for inicio in (4.5, -1, 10, "x"):
            with self.assertRaises(validacao.Erro):
                self.acoes.acao_iniciar_troca({"projeto": f"b{inicio}".replace(".", "_").replace("-", "m"), "video": "v.mp4", "foto": "f.png", "duracao": 6, "inicio": inicio, "autorizacao": True, "ajustes": {"megapixels": 0.2, "upscale": False}})
        self.assertEqual(self.lancados, ["a"])

    def test_marca_da_pessoa(self):
        self.acoes.acao_iniciar_troca({"projeto": "m", "video": "v.mp4", "foto": "f.png", "duracao": 3, "marca": {"x": 0.25, "y": 0.5}, "autorizacao": True, "ajustes": {"megapixels": 0.2, "upscale": False}})
        self.assertEqual(json.loads((config.PROJETOS / "m" / validacao.PARAMETROS).read_text(encoding="utf-8"))["marca"], {"x": 0.25, "y": 0.5})
        for i, marca in enumerate(({"x": 2, "y": 0.5}, {"x": "a"}, [1, 2])):
            with self.assertRaises(validacao.Erro):
                self.acoes.acao_iniciar_troca({"projeto": f"n{i}", "video": "v.mp4", "foto": "f.png", "duracao": 3, "marca": marca, "autorizacao": True, "ajustes": {"megapixels": 0.2, "upscale": False}})
        # Com a segunda passagem nao ha janelas, entao nao ha mascara
        with self.assertRaises(validacao.Erro):
            self.acoes.acao_iniciar_troca({"projeto": "u", "video": "v.mp4", "foto": "f.png", "duracao": 3, "marca": {"x": 0.5, "y": 0.5}, "autorizacao": True, "ajustes": {"megapixels": 0.2}})
        self.assertEqual(self.lancados, ["m"])


class Janelas(unittest.TestCase):
    """A troca em janelas com emenda (16/11/2026)."""

    def test_plano_de_5_s_em_janelas_de_3_s_e_o_do_teste(self):
        self.assertEqual(trocar_personagem.janelas(120, 73), [
            {"i": 1, "start": 0, "length": 73, "held": 0, "first": 0, "last": 72, "fim": 120},
            {"i": 2, "start": 55, "length": 73, "held": 18, "first": 73, "last": 119, "fim": 120}])

    def test_corte_recomeca_a_janela_limpa(self):
        plano = trocar_personagem.janelas(120, 124, cortes=[72])
        self.assertEqual([(j["start"], j["held"], j["first"], j["last"], j["fim"]) for j in plano], [(0, 0, 0, 71, 72), (72, 0, 72, 119, 120)])
        # Um plano de menos de 5 quadros fica junto do anterior
        self.assertEqual(len(trocar_personagem.janelas(120, 124, cortes=[118])), 1)
        self.assertEqual(len(trocar_personagem.janelas(120, 124, cortes=[2])), 1)
        # Corte e janelas longas juntos: dentro de cada plano as janelas emendam como antes
        plano = trocar_personagem.janelas(300, 124, cortes=[200])
        entregues = [s for j in plano for s in range(j["first"], j["last"] + 1)]
        self.assertEqual(entregues, list(range(300)))
        self.assertEqual([j["held"] for j in plano], [0, 18, 0])

    def test_janela_depois_do_corte_usa_prompt_e_referencia_sem_emenda(self):
        j = trocar_personagem.janelas(120, 124, cortes=[72])[1]
        g = trocar_personagem.grafo_janela(BASE, {**P, "upscale": False}, j, "c.mp4", "f.png", "troca/x/j2", 42, 7, "PROMPT", "ref.png")
        self.assertNotIn("826", g)
        self.assertEqual(g["400"]["inputs"]["ref_images.ref_image_1"], ["960", 0])
        self.assertNotIn("950", g)
        self.assertEqual(g["14"]["inputs"]["latent_image"], ["289", 0])
        self.assertTrue(ligacoes_validas(g))

    def test_refazer_leva_as_seguintes_do_mesmo_plano(self):
        plano = trocar_personagem.janelas(300, 124, cortes=[200])  # janelas 1 e 2 no primeiro plano, 3 depois do corte
        self.assertEqual(trocar_personagem.janelas_a_refazer(plano, 2), {2})
        self.assertEqual(trocar_personagem.janelas_a_refazer(plano, 3), {3})
        self.assertEqual(trocar_personagem.janelas_a_refazer(plano, 1), {1, 2, 3})
        plano = trocar_personagem.janelas(360, 124)
        self.assertEqual(trocar_personagem.janelas_a_refazer(plano, 2), {2, 3, 4})

    def test_refazer_janela_pede_as_janelas_guardadas(self):
        import acoes, tarefa
        with tempfile.TemporaryDirectory() as d:
            raiz = Path(d)
            pasta = raiz / "x"
            (pasta / "janelas_feitas").mkdir(parents=True)
            (pasta / "estado.json").write_text(json.dumps({"tipo": "troca", "janelas": [{"i": 1}, {"i": 2}]}), encoding="utf-8")
            lancados = []
            with mock.patch.object(config, "PROJETOS", raiz), mock.patch.object(acoes, "exigir_comfy_livre", lambda: None), \
                    mock.patch.object(tarefa, "tarefa", types.SimpleNamespace(iniciar_troca=lambda nome, extras=(): lancados.append((nome, list(extras))))):
                with self.assertRaises(validacao.Erro):
                    acoes.acao_refazer_janela({"projeto": "x", "janela": 2})  # sem janelas.json
                (pasta / "janelas_feitas" / "janelas.json").write_text("{}", encoding="utf-8")
                for n in (0, 3, "2", True):
                    with self.assertRaises(validacao.Erro):
                        acoes.acao_refazer_janela({"projeto": "x", "janela": n})
                acoes.acao_refazer_janela({"projeto": "x", "janela": 2})
            self.assertEqual(lancados, [("x", ["--refazer", "2"])])

    def test_spans_do_latente(self):
        spans = trocar_personagem.spans_latentes(73)
        self.assertEqual(len(spans), trocar_personagem.latentes(73))
        self.assertEqual(spans[:3], [(0, 0), (1, 4), (5, 8)])
        self.assertEqual(spans[-1], (69, 72))
        self.assertEqual(spans[5], (17, 17))
        # Os 18 quadros da emenda enchem os 6 primeiros latentes inteiros
        self.assertEqual(spans[trocar_personagem.latentes_presos(18) - 1][1], 17)

    def test_mascara_cortada_como_o_grafo(self):
        from PIL import Image
        m = Image.new("L", (400, 300))
        self.assertEqual(trocar_personagem.mascara_no_quadro(m, 16 / 9).size, (400, 225))
        self.assertEqual(trocar_personagem.mascara_no_quadro(m, 1.0).size, (300, 300))
        self.assertAlmostEqual(trocar_personagem.proporcao_numero("9:16 (Portrait Widescreen)"), 9 / 16)

    def test_fundo_segue_o_movimento_da_camera(self):
        import numpy as np, fundo
        rng = np.random.default_rng(1)
        base = (rng.uniform(0, 255, (260, 400)) > 200).astype(np.uint8) * 255  # pontos para seguir
        import cv2
        base = cv2.GaussianBlur(base, (5, 5), 0)
        # A camera anda 3 px por quadro para a esquerda: o cenario anda para a direita
        cinzas = [np.ascontiguousarray(base[30:230, 50 - 3 * k:350 - 3 * k]) for k in range(6)]
        alfas = [np.zeros((200, 300), np.float32)] * 6
        mov = fundo.movimentos(cinzas, alfas)
        self.assertAlmostEqual(mov[5][0, 2], 15, delta=1.5)
        self.assertAlmostEqual(mov[5][1, 2], 0, delta=1.5)
        # Num corte, recomeca
        self.assertTrue(np.allclose(fundo.movimentos(cinzas, alfas, cortes=[3])[3], np.eye(3)))

    def test_detector_de_cortes(self):
        import numpy as np, cortes
        y, x = np.mgrid[0:90, 0:160].astype(np.float32)
        # Imagens lisas (como uma cena), para um passo de 1 pixel ser um movimento pequeno
        a, b = 128 + 100 * np.sin(x / 15) * np.cos(y / 20), 128 + 100 * np.cos(x / 9 + 1) * np.sin(y / 7)
        # Dois planos com um pouco de movimento cada; o segundo comeca no quadro 30
        quadros = np.stack([np.roll(a, k, axis=1) for k in range(30)] + [np.roll(b, k, axis=1) for k in range(30)])
        self.assertEqual(cortes.achar(quadros, 24), [{"quadro": 30, "segundos": 1.25}])
        self.assertEqual(cortes.achar(quadros[:30], 24), [])

    def test_janelas_cobrem_tudo_no_grid_do_h3(self):
        for total in (125, 200, 240, 360):
            for tam in (90, 124):
                plano = trocar_personagem.janelas(total, tam)
                entregues = [s for j in plano for s in range(j["first"], j["last"] + 1)]
                self.assertEqual(entregues, list(range(total)), (total, tam))
                for j in plano:
                    self.assertLessEqual(j["length"], tam)
                    self.assertEqual((j["length"] - 5) % 17, 0)
                    if j["i"] > 1:
                        anterior = plano[j["i"] - 2]
                        self.assertEqual(j["start"] + j["held"] - 1, anterior["last"])

    def test_tamanho_da_janela_e_o_de_uma_passada(self):
        self.assertEqual(trocar_personagem.quadros_janela(0.2), 124)
        self.assertEqual(trocar_personagem.quadros_janela(0.8), 90)
        # Numa passada arredonda para cima; em janelas usa os quadros pedidos
        self.assertEqual(trocar_personagem.quadros_usados(3, 0.2), 73)
        self.assertEqual(trocar_personagem.quadros_usados(5, 0.2), 124)
        self.assertEqual(trocar_personagem.quadros_usados(5, 0.8), 120)
        self.assertEqual(trocar_personagem.quadros_usados(10, 0.2), 240)

    def test_latentes_da_emenda(self):
        self.assertEqual(trocar_personagem.latentes(73), 22)
        self.assertEqual(trocar_personagem.latentes_presos(18), 6)

    def test_primeira_janela_e_a_troca_normal_sem_video_no_comfy(self):
        j = trocar_personagem.janelas(240, 124)[0]
        g = trocar_personagem.grafo_janela(BASE, {**P, "upscale": False}, j, "c.mp4", "f.png", "troca/x/j1", 42, 7)
        self.assertNotIn("539", g)
        self.assertNotIn("791", g)
        self.assertEqual(g["970"]["inputs"]["images"], ["538", 0])
        self.assertIn("826", g)
        self.assertEqual(g["14"]["inputs"]["latent_image"], ["289", 0])
        self.assertTrue(ligacoes_validas(g))

    def test_janela_seguinte_parte_da_emenda_com_a_referencia(self):
        j = trocar_personagem.janelas(240, 124)[1]
        g = trocar_personagem.grafo_janela(BASE, {**P, "upscale": False}, j, "c.mp4", "f.png", "troca/x/j2", 42, 7, "PROMPT", "ref.png", "pix.mp4", "m.mp4")
        for no in ("826", "835", "827", "900", "901", "85"):
            self.assertNotIn(no, g)
        self.assertTrue(g["400"]["inputs"]["prompt"].startswith("PROMPT"))
        self.assertIn("<Picture 2>", g["400"]["inputs"]["prompt"])
        for no in ("400", "587"):
            self.assertEqual(g[no]["inputs"]["ref_images.ref_image_1"], ["960", 0])
        self.assertEqual(g["960"]["inputs"]["image"], "ref.png")
        self.assertEqual((g["950"]["inputs"]["video"], g["953"]["inputs"]["video"]), ("pix.mp4", "m.mp4"))
        self.assertEqual(g["955"]["class_type"], "SetLatentNoiseMask")
        self.assertEqual(g["14"]["inputs"]["latent_image"], ["957", 0])
        self.assertEqual(g["81"]["inputs"]["latent"], ["957", 0])
        self.assertEqual(round(g["5"]["inputs"]["value"] * 24), j["length"])
        self.assertTrue(ligacoes_validas(g))

    def test_progresso_por_janela(self):
        with tempfile.TemporaryDirectory() as d:
            arq = Path(d) / "progresso.json"
            mon = types.SimpleNamespace(rotulo="")
            pr = Progresso(arq, False, mon)
            pr.nova_janela(1, 3, {})
            self.assertEqual(json.loads(arq.read_text())["janela"], [1, 3])
            self.assertEqual(pr.etapa, "descrever")
            pr.etapa = "montar"
            pr.nova_janela(2, 3, {})
            dados = json.loads(arq.read_text())
            self.assertEqual((dados["etapa"], dados["janela"]), ("primeira", [2, 3]))
            self.assertIn("janelas_anteriores", dados["tempos"])
            self.assertEqual(pr.mapa, {"14": "primeira", "538": "montar"})


class ReferenciaMax(unittest.TestCase):
    def test_foto_vai_no_tamanho_dela_nos_dois_modos(self):
        for roupa in ("video", "foto"):
            g = grafo(roupa=roupa)
            for no in ("400", "587"):
                self.assertEqual(g[no]["inputs"]["ref_image_size"], "max", (roupa, no))

    def test_agendador_padrao_e_o_beta(self):
        self.assertEqual(validacao.PADRAO_TROCA["agendador"], "beta")


if __name__ == "__main__":
    unittest.main()
