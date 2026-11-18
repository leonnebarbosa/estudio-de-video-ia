"""Testes do texto para imagem e da escolha da roupa na troca. Nao usam o ComfyUI nem a placa.

Uso: python -I testar_texto.py
"""
import json, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import comunidade  # noqa: F401 (poe os modelos falsos da comunidade)
import config, projetos, validacao
from texto_para_imagem import AMOSTRADOR, grafo
from trocar_personagem import GRAFO, HEAD_SWAP, INSTRUCAO_ROSTO, descricao_do_rosto, montar_grafo

TROCA = {"duracao": 3, "proporcao": "16:9 (Widescreen)", "megapixels": 0.2, "upscale": False, "upscale_mesma": False, "upscale_megapixels": 1.0, "upscaler": "h3_upscaler_lms_v0.1.safetensors",
         "audio_original": True, "modelo": "minimax_h3_ref2va_pruned_int8_convrot.safetensors", "troca": ["minimax_h3_character_swap_v1.1_ref2va_fro.safetensors", 1.0],
         "turbo": ["minimax_h3_dmd_ref2va_8step_turbo_pruned.safetensors", 1.0], "nitidez": None, "pouca_vram": False, "dividir_blocos": False,
         "passos": 8, "agendador": "simple", "sampler": "euler", "semente": 42}
BASE = json.loads(GRAFO.read_text(encoding="utf-8"))


class RoupaNaTroca(unittest.TestCase):
    def grafo(self, **p):
        return montar_grafo(BASE, {**TROCA, **p}, "v.mp4", "f.png", "troca/x", 42, 7)

    def test_roupa_do_video_e_o_padrao_e_usa_a_head_swap(self):
        self.assertEqual(validacao.PADRAO_TROCA["roupa"], "video")
        g = self.grafo()
        self.assertEqual((g["586"]["inputs"]["lora_name"], g["586"]["inputs"]["strength_model"]), (HEAD_SWAP, 1.0))
        # A foto vai inteira, a 1 MP (desde 16/11/2026; antes com borda no tamanho do video), para a troca e para a LLM
        self.assertEqual(g["902"]["inputs"]["image"], ["349", 0])
        self.assertEqual((g["902"]["class_type"], g["902"]["inputs"]["megapixels"]), ("ImageScaleToTotalPixels", 1.0))
        for no, campo in (("400", "ref_images.ref_image_0"), ("587", "ref_images.ref_image_0"), ("826", "image")):
            self.assertEqual(g[no]["inputs"][campo], ["902", 0], no)
        # A LLM descreve so o rosto, sem raciocinio (com ele e 512 tokens devolvia vazio)
        self.assertEqual(g["826"]["inputs"]["prompt"], INSTRUCAO_ROSTO.read_text(encoding="utf-8"))
        self.assertIs(g["826"]["inputs"]["thinking"], False)
        self.assertEqual(g["835"]["inputs"]["source"], ["901", 0])

    def test_prompt_e_o_modelo_do_autor_com_o_rosto_no_meio(self):
        g = self.grafo()
        antes, depois = g["900"]["inputs"]["string_a"], g["901"]["inputs"]["string_b"]
        self.assertTrue(antes.startswith("head_swap:"))
        self.assertTrue(antes.rstrip().endswith("Facial details of <Subject 1>:"))
        self.assertEqual(g["900"]["inputs"]["string_b"], ["826", 0])
        self.assertIn("Replace only the entire head of <Subject 2>", depois)
        prompt = antes + "Male, gray beard" + depois
        self.assertEqual(descricao_do_rosto(prompt), "Male, gray beard")
        self.assertEqual(descricao_do_rosto(antes + depois), "")

    def test_roupa_da_foto_mantem_a_character_swap(self):
        g = self.grafo(roupa="foto")
        self.assertEqual(g["586"]["inputs"]["lora_name"], TROCA["troca"][0])
        self.assertEqual(g["826"]["inputs"]["prompt"], BASE["826"]["inputs"]["prompt"])
        self.assertEqual(g["400"]["inputs"]["ref_images.ref_image_0"], ["866", 0])
        self.assertNotIn("902", g)

    def test_projeto_antigo_sem_a_chave_vai_pela_roupa_do_video(self):
        p = {k: v for k, v in TROCA.items() if k != "roupa"}
        self.assertEqual(montar_grafo(BASE, p, "v.mp4", "f.png", "troca/x", 42, 7)["586"]["inputs"]["lora_name"], HEAD_SWAP)

    def test_validacao_recusa_valor_desconhecido(self):
        with mock.patch.object(validacao.ambiente, "ler_opcoes", return_value={"modelos": [TROCA["modelo"]], "samplers": ["euler"], "agendadores": ["simple"], "upscalers": [TROCA["upscaler"]],
                                                                               "loras_troca": {"troca": [TROCA["troca"][0]], "turbo": [TROCA["turbo"][0]], "nitidez": []}}):
            with self.assertRaises(validacao.Erro):
                validacao.validar_troca({**TROCA, "roupa": "metade"})

    def opcoes(self, estilos):
        return {"modelos": [TROCA["modelo"]], "samplers": ["euler"], "agendadores": ["simple"], "upscalers": [TROCA["upscaler"]],
                "loras_troca": {"troca": [TROCA["troca"][0]], "turbo": [TROCA["turbo"][0]], "nitidez": []}, "loras_estilo": estilos}

    def test_loras_de_estilo_da_lista_aprovada(self):
        felt = "feltStopMotionStyle_H3_v01.safetensors"
        self.assertEqual(validacao.PADRAO_TROCA["loras"], [])
        with mock.patch.object(validacao.ambiente, "ler_opcoes", return_value=self.opcoes([felt])):
            self.assertEqual(validacao.validar_troca(TROCA)["loras"], [])
            self.assertEqual(validacao.validar_troca({**TROCA, "loras": [[felt, "0.8"]]})["loras"], [[felt, 0.8]])
            for ruim in ([["outra.safetensors", 1.0]], [[felt, 2.0]], [[felt, 0]], [[felt, 1.0], [felt, 0.5]], [[felt, 1]] * 3):
                with self.assertRaises(validacao.Erro, msg=ruim):
                    validacao.validar_troca({**TROCA, "loras": ruim})


class ApagarTroca(unittest.TestCase):
    # Projetos feitos com o metodo antigo (Qwen) deixaram troca_<projeto>_q0.png e _ref.png na entrada do ComfyUI
    def test_apagar_leva_os_temporarios_da_referencia(self):
        with tempfile.TemporaryDirectory() as d:
            raiz = Path(d)
            entrada, proj = raiz / "input", raiz / "projetos"
            (proj / "minha_troca").mkdir(parents=True)
            (proj / "minha_troca" / "estado.json").write_text("{}", encoding="utf-8")
            entrada.mkdir()
            for nome in ("troca_minha_troca.mp4", "troca_minha_troca_q0.png", "troca_minha_troca_ref.png", "troca_outra_ref.png", "foto.png"):
                (entrada / nome).write_bytes(b"x")
            with mock.patch.multiple(config, ENTRADA=entrada, PROJETOS=proj, SAIDA=raiz / "output"):
                _, arquivos = projetos.alvos_apagar("minha_troca")
            self.assertEqual(sorted(f.name for f in arquivos), ["troca_minha_troca.mp4", "troca_minha_troca_q0.png", "troca_minha_troca_ref.png"])


class TextoParaImagem(unittest.TestCase):
    def test_validacao(self):
        r = validacao.validar_texto({"prompt": "  a red <apple>  on a table ", "quantidade": "3", "semente": ""})
        self.assertEqual((r["prompt"], r["quantidade"], r["semente"], r["megapixels"], r["passos"]), ("a red apple on a table", 3, None, 0.9, 8))
        for errado in ({"prompt": ""}, {"prompt": "x", "quantidade": 5}, {"prompt": "x", "megapixels": 2}, {"prompt": "x", "passos": 40}, {"prompt": "x", "proporcao": "7:5"}):
            with self.assertRaises(validacao.Erro, msg=errado):
                validacao.validar_texto(errado)

    def test_grafo_no_tamanho_e_com_a_semente(self):
        p = validacao.validar_texto({"prompt": "a lighthouse at dusk", "proporcao": "2:3 (Portrait Photo)", "passos": 10})
        g = grafo(p, 123, "texto/x/imagem1")
        self.assertEqual((g["6"]["inputs"]["width"], g["6"]["inputs"]["height"]), (800, 1184))
        self.assertEqual((g[AMOSTRADOR]["inputs"]["seed"], g[AMOSTRADOR]["inputs"]["steps"], g[AMOSTRADOR]["inputs"]["cfg"]), (123, 10, 1))
        self.assertEqual(g["4"]["inputs"]["text"], "a lighthouse at dusk")
        self.assertEqual(g["9"]["inputs"]["filename_prefix"], "texto/x/imagem1")

    def test_projeto_lido_pela_pagina(self):
        with tempfile.TemporaryDirectory() as d:
            pasta = Path(d) / "imagem_farol"
            pasta.mkdir()
            (pasta / "interface.json").write_text(json.dumps({"tipo": "texto", "prompt": "a lighthouse", "quantidade": 2}), encoding="utf-8")
            (pasta / "estado.json").write_text(json.dumps({"tipo": "texto", "imagens": [{"n": 1, "arquivo": "imagem_1.png", "semente": 5}, {"n": 2, "arquivo": "sumiu.png"}]}), encoding="utf-8")
            (pasta / "imagem_1.png").write_bytes(b"png")
            p = projetos.ler_projeto(pasta)
            self.assertEqual((p["tipo"], p["total"], p["completo"], [i["arquivo"] for i in p["imagens"]]), ("texto", 2, False, ["imagem_1.png"]))
            self.assertEqual(p["ideia"], "a lighthouse")

    def test_saida_do_comfy_entra_no_apagar(self):
        self.assertIn("texto", projetos.PASTAS_SAIDA)

    def lora_falsa(self, pasta, nome, chaves, meta=None):
        import struct
        cab = {k: {"dtype": "F16", "shape": [1], "data_offsets": [0, 2]} for k in chaves}
        if meta:
            cab["__metadata__"] = meta
        texto = json.dumps(cab).encode()
        (pasta / nome).write_bytes(struct.pack("<Q", len(texto)) + texto + b"\0\0")
        return pasta / nome

    def test_familia_da_lora_pelo_cabecalho(self):
        import texto_para_imagem as t2i
        with tempfile.TemporaryDirectory() as d:
            pasta = Path(d)
            casos = {"krea_meta.safetensors": (["x.weight"], {"ss_base_model_version": "krea2"}, "krea2"),
                     "krea_pesos.safetensors": (["diffusion_model.blocks.0.attn.gate.lora_A.weight"], None, "krea2"),
                     "zit.safetensors": (["diffusion_model.layers.1.adaLN_modulation.0.lora_B.weight"], None, "zimage"),
                     "chroma.safetensors": (["diffusion_model.double_blocks.0.img_attn.qkv.lora_A.weight"], None, "chroma"),
                     "h3.safetensors": (["diffusion_model.blocks.0.attn.qkv_proj.lora_A.weight"], None, None),
                     "wan.safetensors": (["diffusion_model.blocks.0.cross_attn.k.lora_A.weight"], None, None)}
            for nome, (chaves, meta, esperado) in casos.items():
                self.assertEqual(t2i.familia_lora(self.lora_falsa(pasta, nome, chaves, meta)), esperado, nome)
            (pasta / "quebrada.safetensors").write_bytes(b"nada")
            self.assertIsNone(t2i.familia_lora(pasta / "quebrada.safetensors"))

    def test_loras_so_do_modelo_e_no_maximo_duas(self):
        import texto_para_imagem as t2i
        with tempfile.TemporaryDirectory() as d:
            loras = Path(d) / "loras"
            (loras / "sub").mkdir(parents=True)
            self.lora_falsa(loras, "a_krea.safetensors", ["diffusion_model.blocks.0.attn.gate.lora_A.weight"])
            self.lora_falsa(loras / "sub", "b_krea.safetensors", ["diffusion_model.blocks.0.attn.wk.lora_A.weight"])
            self.lora_falsa(loras, "c_zit.safetensors", ["diffusion_model.layers.1.feed_forward.w1.lora_A.weight"])
            with mock.patch.object(config, "MODELOS", Path(d)), mock.patch.object(validacao, "faltam_texto", lambda m: []):
                # Pelo nome do arquivo, mesmo em subpasta: o caminho entra so no envio ao ComfyUI (loras.py)
                self.assertEqual(t2i.loras_compativeis("comunidade_krea2"), ["a_krea.safetensors", "b_krea.safetensors"])
                self.assertEqual(t2i.loras_compativeis("z_image_turbo"), ["c_zit.safetensors"])
                r = validacao.validar_texto({"prompt": "x", "modelo": "comunidade_krea2", "passos": 8, "loras": [["a_krea.safetensors", "1.5"]]})
                self.assertEqual(r["loras"], [["a_krea.safetensors", 1.5]])
                for errado in ([["c_zit.safetensors", 1]], [["a_krea.safetensors", 0]], [["a_krea.safetensors", 3]], [["a_krea.safetensors", 1], ["a_krea.safetensors", 1]],
                               [["a_krea.safetensors", 1], ["sub/b_krea.safetensors", 1], ["a_krea.safetensors", 1]], [["a_krea.safetensors", "muito"]]):
                    with self.assertRaises(validacao.Erro, msg=errado):
                        validacao.validar_texto({"prompt": "x", "modelo": "comunidade_krea2", "loras": errado})

    def test_grafo_por_modelo_com_loras(self):
        import texto_para_imagem as t2i
        base = {**validacao.PADRAO_TEXTO, "prompt": "a cat", "proporcao": "1:1 (Square)", "megapixels": 1.0}
        g = t2i.grafo({**base, "modelo": "comunidade_krea2", "passos": 8, "loras": [["a.safetensors", 1.5], ["b.safetensors", 0.7]]}, 5, "x")
        self.assertEqual((g["1"]["class_type"], g["2"]["inputs"]["type"], g["5"]["class_type"], g["6"]["class_type"]), ("UNETLoader", "krea2", "ConditioningZeroOut", "EmptyLatentImage"))
        self.assertEqual((g["200"]["inputs"]["model"], g["201"]["inputs"]["model"], g[AMOSTRADOR]["inputs"]["model"]), (["1", 0], ["200", 0], ["201", 0]))
        self.assertEqual((g[AMOSTRADOR]["inputs"]["sampler_name"], g[AMOSTRADOR]["inputs"]["scheduler"], g[AMOSTRADOR]["inputs"]["steps"]), ("euler", "linear_quadratic", 8))
        z = t2i.grafo({**base, "modelo": "z_image_turbo", "passos": 8, "loras": [["c.safetensors", 1.0]]}, 5, "x")
        # O AuraFlow (shift 3) vem depois das LoRAs, como no fluxo oficial
        self.assertEqual((z["21"]["inputs"]["model"], z[AMOSTRADOR]["inputs"]["model"], z["2"]["inputs"]["type"]), (["200", 0], ["21", 0], "lumina2"))
        c = t2i.grafo({**base, "modelo": "chroma_flash"}, 5, "x")
        self.assertEqual((c["5"]["class_type"], c[AMOSTRADOR]["inputs"]["model"]), ("CLIPTextEncode", ["1", 0]))
        self.assertNotIn("21", c)

    def test_imagem_de_partida(self):
        import texto_para_imagem as t2i
        with tempfile.TemporaryDirectory() as d:
            entrada = Path(d)
            (entrada / "base.png").write_bytes(b"png")
            with mock.patch.object(config, "ENTRADA", entrada):
                r = validacao.validar_texto({"prompt": "x", "modelo": "z_image_turbo", "passos": 8, "partida": "..\\base.png", "forca_partida": "0.4"})
                self.assertEqual((r["partida"], r["forca_partida"]), ("base.png", 0.4))
                for errado in ({"partida": "sumiu.png"}, {"partida": "base.png", "forca_partida": 0}, {"partida": "base.png", "forca_partida": 1.5}, {"partida": "base.png", "forca_partida": "x"}):
                    with self.assertRaises(validacao.Erro, msg=errado):
                        validacao.validar_texto({"prompt": "x", **errado})
                # Sem imagem, a forca volta ao padrao e o grafo parte do latente vazio
                sem = validacao.validar_texto({"prompt": "x", "forca_partida": 0.2})
                self.assertEqual((sem["partida"], sem["forca_partida"]), (None, 0.6))
        g = t2i.grafo({**r, "proporcao": "1:1 (Square)", "megapixels": 1.0}, 3, "x")
        self.assertEqual((g["30"]["inputs"]["image"], g["31"]["inputs"]["crop"], g["6"]["class_type"], g["6"]["inputs"]["vae"]), ("base.png", "center", "VAEEncode", ["3", 0]))
        self.assertEqual((g["31"]["inputs"]["width"], g[AMOSTRADOR]["inputs"]["denoise"], g[AMOSTRADOR]["inputs"]["latent_image"]), (1024, 0.4, ["6", 0]))
        vazio = t2i.grafo({**sem, "proporcao": "1:1 (Square)", "megapixels": 1.0}, 3, "x")
        self.assertEqual((vazio["6"]["class_type"], vazio[AMOSTRADOR]["inputs"]["denoise"]), ("EmptySD3LatentImage", 1))
        self.assertNotIn("30", vazio)

    def test_editar_imagem_com_qwen(self):
        import texto_para_imagem as t2i
        m = t2i.MODELOS_TEXTO["qwen_edit"]
        with tempfile.TemporaryDirectory() as d:
            entrada = Path(d)
            (entrada / "base.png").write_bytes(b"png")
            with mock.patch.object(config, "ENTRADA", entrada), mock.patch.object(validacao, "faltam_texto", lambda k: []):
                # Editar sem imagem nao tem o que editar
                with self.assertRaises(validacao.Erro):
                    validacao.validar_texto({"prompt": "make it red", "modelo": "qwen_edit", "passos": 4})
                r = validacao.validar_texto({"prompt": "make it red", "modelo": "qwen_edit", "passos": 4, "partida": "base.png", "forca_partida": 0.3})
        g = t2i.grafo(r, 9, "x")
        enc = g["4"]["inputs"]
        self.assertEqual((enc["prompt"], enc["image1"], g["5"]["inputs"]["prompt"], g["30"]["inputs"]["image"]), ("make it red", ["31", 0], "", "base.png"))
        self.assertEqual((g["31"]["class_type"], g["23"]["inputs"]["lora_name"], g["21"]["inputs"]["shift"]), ("FluxKontextImageScale", m["lora_fixa"], 3.1))
        a = g[AMOSTRADOR]["inputs"]
        # Muda so o que a instrucao pede: denoise 1, CFG 1 e o latente da propria imagem; a "forca" do img2img nao vale aqui
        self.assertEqual((a["denoise"], a["cfg"], a["latent_image"], a["positive"], a["negative"], a["model"]), (1, 1, ["6", 0], ["24", 0], ["25", 0], ["23", 0]))
        # LoRA do usuario entra depois da Lightning
        com = t2i.grafo({**r, "loras": [("pose.safetensors", 0.8)]}, 9, "x")
        self.assertEqual((com["200"]["inputs"]["model"], com[AMOSTRADOR]["inputs"]["model"]), (["23", 0], ["200", 0]))
        self.assertTrue([x for x in validacao.modelos_texto() if x["id"] == "qwen_edit"][0]["edicao"])
        self.assertNotIn("32", g)
        self.assertNotIn("image2", enc)

    def test_editar_com_segunda_imagem(self):
        import texto_para_imagem as t2i
        with tempfile.TemporaryDirectory() as d:
            entrada = Path(d)
            for n in ("base.png", "roupa.png"):
                (entrada / n).write_bytes(b"png")
            with mock.patch.object(config, "ENTRADA", entrada), mock.patch.object(validacao, "faltam_texto", lambda k: []):
                base = {"prompt": "put the jacket from image 2 on her", "passos": 4, "partida": "base.png"}
                r = validacao.validar_texto({**base, "modelo": "qwen_edit", "referencia": "..\\roupa.png"})
                self.assertEqual(r["referencia"], "roupa.png")
                with self.assertRaises(validacao.Erro):
                    validacao.validar_texto({**base, "modelo": "qwen_edit", "referencia": "sumiu.png"})
                # Nos outros modelos a segunda imagem nao vale e some
                self.assertIsNone(validacao.validar_texto({**base, "modelo": "z_image_turbo", "passos": 8, "referencia": "roupa.png"})["referencia"])
        g = t2i.grafo(r, 9, "x")
        self.assertEqual((g["32"]["inputs"]["image"], g["4"]["inputs"]["image2"], g["5"]["inputs"]["image2"], g["4"]["inputs"]["image1"]), ("roupa.png", ["32", 0], ["32", 0], ["31", 0]))
        # O latente continua so da primeira: a saida segue o tamanho dela
        self.assertEqual(g["6"]["inputs"]["pixels"], ["31", 0])

    def test_editar_imagem_com_klein(self):
        import texto_para_imagem as t2i
        m = t2i.MODELOS_TEXTO["klein_edit"]
        with tempfile.TemporaryDirectory() as d:
            entrada = Path(d)
            for n in ("base.png", "roupa.png"):
                (entrada / n).write_bytes(b"png")
            with mock.patch.object(config, "ENTRADA", entrada), mock.patch.object(validacao, "faltam_texto", lambda k: []):
                with self.assertRaises(validacao.Erro):
                    validacao.validar_texto({"prompt": "make it red", "modelo": "klein_edit", "passos": 4})
                r = validacao.validar_texto({"prompt": "make it red", "modelo": "klein_edit", "passos": 4, "partida": "base.png"})
                r2 = validacao.validar_texto({**r, "referencia": "roupa.png"})
        g = t2i.grafo(r, 9, "x")
        # A imagem vai a 2 MP, vira o latente de referencia e define o tamanho da saida
        self.assertEqual((g["30"]["inputs"]["image"], g["31"]["class_type"], g["31"]["inputs"]["megapixels"]), ("base.png", "ImageScaleToTotalPixels", 2.0))
        self.assertEqual((g["6"]["class_type"], g["6"]["inputs"]["width"], g["42"]["inputs"]["steps"]), ("EmptyFlux2LatentImage", ["33", 0], 4))
        self.assertEqual((g["24"]["inputs"]["latent"], g["25"]["inputs"]["conditioning"], g["5"]["class_type"]), (["34", 0], ["5", 0], "ConditioningZeroOut"))
        self.assertEqual((g["40"]["inputs"]["cfg"], g["40"]["inputs"]["positive"], g["2"]["inputs"]["type"], g["1"]["inputs"]["unet_name"]),
                         (1, ["24", 0], "flux2", m["unet"]))
        # O progresso da pagina le o no do amostrador
        self.assertEqual((g[AMOSTRADOR]["class_type"], g[AMOSTRADOR]["inputs"]["noise"], g["43"]["inputs"]["noise_seed"]), ("SamplerCustomAdvanced", ["43", 0], 9))
        self.assertNotIn("32", g)
        # Segunda imagem: mais uma referencia em cadeia, no positivo e no negativo
        g2 = t2i.grafo(r2, 9, "x")
        self.assertEqual((g2["32"]["inputs"]["image"], g2["26"]["inputs"]["conditioning"], g2["27"]["inputs"]["latent"]), ("roupa.png", ["24", 0], ["36", 0]))
        self.assertEqual((g2["40"]["inputs"]["positive"], g2["40"]["inputs"]["negative"]), (["26", 0], ["27", 0]))
        self.assertTrue([x for x in validacao.modelos_texto() if x["id"] == "klein_edit"][0]["edicao"])

    def test_descrever_imagem(self):
        import acoes, texto_para_imagem as t2i
        g = t2i.grafo_descrever("foto.png")
        self.assertEqual((g["1"]["inputs"]["image"], g["4"]["inputs"]["image"], g["4"]["inputs"]["clip"], g["5"]["inputs"]["source"]), ("foto.png", ["2", 0], ["3", 0], ["4", 0]))
        # Sem raciocinio: com ele e poucos tokens a LLM devolvia vazio
        self.assertIs(g["4"]["inputs"]["thinking"], False)
        self.assertEqual((g["2"]["inputs"]["megapixels"], g["3"]["inputs"]["clip_name"]), (0.5, t2i.LLM_VISAO))
        resposta = {"status": "success", "saidas": {"5": {"text": ['  "A red bicycle by a blue door."  ']}}, "segundos": 9}
        with mock.patch.object(t2i, "rodar", lambda g, tempo: resposta):
            self.assertEqual(t2i.descrever("foto.png"), "A red bicycle by a blue door.")
        with mock.patch.object(t2i, "rodar", lambda g, tempo: {"status": "error", "erro": "sem memoria", "saidas": {}}), self.assertRaises(RuntimeError):
            t2i.descrever("foto.png")
        with tempfile.TemporaryDirectory() as d:
            entrada = Path(d)
            (entrada / "foto.png").write_bytes(b"png")
            with mock.patch.object(config, "ENTRADA", entrada), mock.patch.object(acoes, "exigir_comfy_livre", lambda: None), \
                    mock.patch.object(acoes.tarefa.tarefa, "rodando", lambda: False), mock.patch.object(t2i, "rodar", lambda g, tempo: resposta):
                self.assertEqual(acoes.acao_descrever_imagem({"arquivo": "foto.png"})["prompt"], "A red bicycle by a blue door.")
                with self.assertRaises(validacao.Erro):
                    acoes.acao_descrever_imagem({"arquivo": "sumiu.png"})
                # Uma descricao por vez
                acoes._descrevendo.acquire()
                try:
                    with self.assertRaises(validacao.Erro) as e:
                        acoes.acao_descrever_imagem({"arquivo": "foto.png"})
                    self.assertEqual(e.exception.codigo, 409)
                finally:
                    acoes._descrevendo.release()
            with mock.patch.object(config, "ENTRADA", entrada), mock.patch.object(acoes.tarefa.tarefa, "rodando", lambda: True), self.assertRaises(validacao.Erro):
                acoes.acao_descrever_imagem({"arquivo": "foto.png"})

    def test_seletor_de_modelo(self):
        from texto_para_imagem import MODELOS_TEXTO
        self.assertEqual(validacao.validar_texto({"prompt": "x"})["modelo"], "z_image_turbo")  # o do pacote inicial
        with self.assertRaises(validacao.Erro):
            validacao.validar_texto({"prompt": "x", "modelo": "outro"})
        with mock.patch.object(validacao, "faltam_texto", lambda m: ["unet.gguf"]), self.assertRaises(validacao.Erro):
            validacao.validar_texto({"prompt": "x"})
        self.assertEqual([m["id"] for m in validacao.modelos_texto()], list(MODELOS_TEXTO))
        # Projeto de antes do seletor, sem a chave, continua no Chroma Flash
        p = {k: v for k, v in validacao.validar_texto({"prompt": "x"}).items() if k != "modelo"}
        self.assertEqual(grafo(p, 1, "x")["1"]["inputs"]["unet_name"], MODELOS_TEXTO["chroma_flash"]["unet"])


class DescartarImagem(unittest.TestCase):
    """Descartar uma imagem de uma geracao com varias: conta antes, so apaga com confirmar e o projeto segue completo."""
    def setUp(self):
        import acoes
        self.acoes = acoes
        d = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, d, True)
        self.aqui, self.saida = d / "projetos", d / "output"
        self.pasta = self.aqui / "fotos"
        self.pasta.mkdir(parents=True)
        (self.saida / "texto" / "fotos").mkdir(parents=True)
        (self.pasta / "interface.json").write_text(json.dumps({"tipo": "texto", "prompt": "x", "quantidade": 3}), encoding="utf-8")
        (self.pasta / "estado.json").write_text(json.dumps({"tipo": "texto", "imagens": [{"n": n, "arquivo": f"imagem_{n}.png", "semente": n} for n in (1, 2, 3)]}), encoding="utf-8")
        for n in (1, 2, 3):
            (self.pasta / f"imagem_{n}.png").write_bytes(b"p" * 1000)
            (self.saida / "texto" / "fotos" / f"imagem{n}_00001_.png").write_bytes(b"p" * 1000)
        self.rodando = False
        for alvo, nome, valor in ((config, "PROJETOS", self.aqui), (config, "SAIDA", self.saida),
                                  (acoes.tarefa, "tarefa", __import__("types").SimpleNamespace(rodando=lambda: self.rodando, projeto="fotos"))):
            p = mock.patch.object(alvo, nome, valor)
            p.start()
            self.addCleanup(p.stop)

    def test_sem_confirmar_so_conta(self):
        r = self.acoes.acao_apagar_imagem({"projeto": "fotos", "arquivo": "imagem_2.png"})
        self.assertEqual((r["arquivos"], r["arquivo"]), (2, "imagem_2.png"))
        self.assertTrue((self.pasta / "imagem_2.png").exists())
        self.assertNotIn("apagado", r)

    def test_apaga_so_a_imagem_e_a_copia_do_comfy(self):
        quando = projetos.ler_projeto(self.pasta)["quando"]
        self.acoes.acao_apagar_imagem({"projeto": "fotos", "arquivo": "imagem_2.png", "confirmar": True})
        self.assertEqual(sorted(f.name for f in self.pasta.glob("*.png")), ["imagem_1.png", "imagem_3.png"])
        self.assertEqual(sorted(f.name for f in (self.saida / "texto" / "fotos").iterdir()), ["imagem1_00001_.png", "imagem3_00001_.png"])
        p = projetos.ler_projeto(self.pasta)
        # O projeto continua completo (o script nao gera a imagem de novo) e a pagina ve so as duas
        self.assertEqual(([i["arquivo"] for i in p["imagens"]], p["descartadas"], p["completo"], p["total"]), (["imagem_1.png", "imagem_3.png"], 1, True, 3))
        e = json.loads((self.pasta / "estado.json").read_text(encoding="utf-8"))
        self.assertEqual(len(e["imagens"]), 3)
        # A data do projeto nao muda: ele nao pula para o topo de Projetos nem volta ao palco
        self.assertEqual(p["quando"], quando)
        # A mesma imagem nao pode ser descartada duas vezes
        with self.assertRaises(validacao.Erro):
            self.acoes.acao_apagar_imagem({"projeto": "fotos", "arquivo": "imagem_2.png", "confirmar": True})

    def test_recusa_o_que_nao_e_imagem_do_projeto(self):
        (self.pasta / "outra.png").write_bytes(b"p")
        for arquivo in ("estado.json", "outra.png", "../fotos/imagem_1.png", "imagem_9.png", "", None):
            with self.assertRaises(validacao.Erro, msg=arquivo):
                self.acoes.acao_apagar_imagem({"projeto": "fotos", "arquivo": arquivo, "confirmar": True})
        for nome in ("..", "nao_existe", ""):
            with self.assertRaises(validacao.Erro, msg=nome):
                self.acoes.acao_apagar_imagem({"projeto": nome, "arquivo": "imagem_1.png", "confirmar": True})
        self.assertEqual(len(list(self.pasta.glob("*.png"))), 4)

    def test_recusa_o_projeto_que_esta_gerando(self):
        self.rodando = True
        with self.assertRaises(validacao.Erro):
            self.acoes.acao_apagar_imagem({"projeto": "fotos", "arquivo": "imagem_1.png", "confirmar": True})
        self.assertTrue((self.pasta / "imagem_1.png").exists())


if __name__ == "__main__":
    unittest.main()
