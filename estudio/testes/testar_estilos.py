"""Testes do estilo pronto de foto (estilos.py; Editar imagem com estilo). Nao usam o ComfyUI nem a placa.

Uso: python -I testar_estilos.py
"""
import sys, tempfile, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import comunidade  # noqa: F401 (poe os modelos falsos da comunidade)
import config, estilos, planos, validacao
import texto_para_imagem as t2i


class Pedido(unittest.TestCase):
    def test_estilo_com_cores_travadas_e_detalhe(self):
        p = estilos.pedido("anime", "dark brown hair, light olive skin.", "golden hour light")
        self.assertTrue(p.startswith("Redraw this exact image as a Japanese anime illustration"))
        self.assertIn("Keep these colors exactly as in the original: dark brown hair, light olive skin. Do not lighten", p)
        self.assertTrue(p.endswith(" golden hour light"))

    def test_lapis_sem_trava_e_realista_com_pedido_proprio(self):
        self.assertNotIn("Keep these colors", estilos.pedido("lapis", "navy t-shirt"))
        r = estilos.pedido("realista", "jet black bob")
        self.assertTrue(r.startswith("Turn this illustration into a real candid photograph"))
        self.assertIn("jet black bob", r)
        # Sem a descricao das cores (falhou ou estilo sem cor) o pedido sai sem a trava
        self.assertNotIn("Keep these colors", estilos.pedido("oleo", None))

    def test_motor(self):
        self.assertEqual(estilos.motor("anime", False), "klein_edit")
        self.assertEqual(estilos.motor("anime", True), "klein9b_edit")
        self.assertEqual(estilos.motor("realista", True), "klein9b_edit")
        self.assertEqual(estilos.motor("realista", False), "qwen21_edit")
        self.assertEqual([e["id"] for e in estilos.lista()][-1], "realista")


class Grafo(unittest.TestCase):
    P = {"partida": "base.png", "prompt": "", "cores": "dark brown hair"}

    def test_estilo_rapido_no_klein_4b_a_2_mp(self):
        g = t2i.grafo({**self.P, "estilo": "aquarela", "qualidade_alta": False, "passos": 8}, 3, "x")
        self.assertEqual((g["1"]["inputs"]["unet_name"], g["31"]["inputs"]["megapixels"], g["42"]["inputs"]["steps"]),
                         (t2i.MODELOS_TEXTO["klein_edit"]["unet"], 2.0, 4))
        self.assertIn("watercolor", g["4"]["inputs"]["text"])
        self.assertIn("Keep these colors exactly as in the original: dark brown hair", g["4"]["inputs"]["text"])
        self.assertNotIn("60", g)

    def test_qualidade_alta_no_klein_9b(self):
        m = t2i.MODELOS_TEXTO["klein9b_edit"]
        g = t2i.grafo({**self.P, "estilo": "anime", "qualidade_alta": True}, 3, "x")
        self.assertEqual((g["1"]["inputs"]["unet_name"], g["2"]["inputs"]["clip_name"], g["31"]["inputs"]["megapixels"]),
                         (m["unet"], "qwen_3_8b_fp8mixed.safetensors", 1.5))
        self.assertTrue(m.get("oculto"))

    def test_realista_9b_com_lora_e_prefixo_do_arquivo_local(self):
        local = {**t2i.MODELOS_TEXTO["klein9b_edit"], "lora_realista": ["realismo.safetensors", 2.0], "prefixo_realista": "photo. "}
        with mock.patch.dict(t2i.MODELOS_TEXTO, {"klein9b_edit": local}):
            g = t2i.grafo({**self.P, "estilo": "realista", "qualidade_alta": True}, 3, "x")
            # A LoRA so entra no realista
            g2 = t2i.grafo({**self.P, "estilo": "anime", "qualidade_alta": True}, 3, "x")
        self.assertEqual((g["60"]["inputs"]["lora_name"], g["60"]["inputs"]["strength_model"], g["40"]["inputs"]["model"]),
                         ("realismo.safetensors", 2.0, ["60", 0]))
        self.assertTrue(g["4"]["inputs"]["text"].startswith("photo. Turn this illustration"))
        self.assertNotIn("60", g2)

    def test_realista_sem_9b_no_qwen_e_refino_configurado(self):
        g = t2i.grafo({**self.P, "estilo": "realista", "qualidade_alta": False}, 3, "x")
        self.assertEqual(g["4"]["class_type"], "TextEncodeQwenImage21")
        self.assertIsNone(t2i.refino_do_estilo({"estilo": "realista", "qualidade_alta": False}))
        cfg = {"modelo": "z_image_turbo", "lora": "foto.safetensors", "forca_lora": 1.5, "forca": 0.3}
        qwen = {**t2i.MODELOS_TEXTO["qwen21_edit"], "refino_realista": cfg}
        with mock.patch.dict(t2i.MODELOS_TEXTO, {"qwen21_edit": qwen}):
            self.assertEqual(t2i.refino_do_estilo({"estilo": "realista", "qualidade_alta": False}), cfg)
            self.assertIsNone(t2i.refino_do_estilo({"estilo": "realista", "qualidade_alta": True}))
            self.assertIsNone(t2i.refino_do_estilo({"estilo": "anime", "qualidade_alta": False}))
        r = t2i.grafo_refino("q.png", cfg, 5, "y")
        self.assertEqual((r["30"]["inputs"]["image"], r["7"]["inputs"]["denoise"], r["7"]["inputs"]["model"], r["10"]["inputs"]["lora_name"]),
                         ("q.png", 0.3, ["21", 0], "foto.safetensors"))
        self.assertEqual(r["9"]["class_type"], "SaveImage")

    def test_cores_da_foto_usa_a_instrucao_das_cores(self):
        capturado = {}

        def falso(g, tempo):
            capturado.update(g)
            return {"status": "success", "saidas": {"5": {"text": ["dark brown hair, hazel eyes"]}}}
        with mock.patch.object(t2i, "rodar", falso):
            self.assertEqual(t2i.cores_da_foto("base.png"), "dark brown hair, hazel eyes")
        self.assertEqual(capturado["4"]["inputs"]["prompt"], estilos.INSTRUCAO_CORES)


class LorasDoKlein(unittest.TestCase):
    def cabecalho(self, pasta, nome, meta=None, chave="diffusion_model.double_blocks.0.img_attn.proj.lora_A.weight", largura=3072):
        import json, struct
        pasta.mkdir(parents=True, exist_ok=True)
        cab = {chave: {"dtype": "F16", "shape": [8, largura], "data_offsets": [0, 0]}}
        if meta:
            cab["__metadata__"] = {"ss_base_model_version": meta}
        dados = json.dumps(cab).encode()
        (pasta / nome).write_bytes(struct.pack("<Q", len(dados)) + dados)
        return pasta / nome

    def test_familia_pelo_metadado_pasta_e_largura(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            self.assertEqual(t2i.familia_lora(self.cabecalho(d / "x", "a.safetensors", "flux2_klein_4b")), "flux2_klein")
            self.assertEqual(t2i.familia_lora(self.cabecalho(d / "x", "b.safetensors", "FLUX_KLEIN_9B")), "flux2_klein9b")
            # Sem metadado: a pasta decide (os nomes dos pesos parecem os do Chroma)
            self.assertEqual(t2i.familia_lora(self.cabecalho(d / "klein9b", "c.safetensors")), "flux2_klein9b")
            self.assertEqual(t2i.familia_lora(self.cabecalho(d / "outra", "d.safetensors")), "chroma")
            # Formato do Flux2 (to_qkv_mlp_proj): a largura separa 4B e 9B
            k = "transformer.single_transformer_blocks.0.attn.to_qkv_mlp_proj.lora_A.weight"
            self.assertEqual(t2i.familia_lora(self.cabecalho(d / "outra", "e.safetensors", chave=k, largura=4096)), "flux2_klein9b")

    def test_loras_no_editar_e_no_gerar(self):
        p = {"partida": "base.png", "prompt": "x", "passos": 4, "loras": [["minha.safetensors", 0.8]]}
        g = t2i.grafo_edicao_klein(p, t2i.MODELOS_TEXTO["klein_edit"], 1, "x")
        self.assertEqual((g["200"]["inputs"]["lora_name"], g["40"]["inputs"]["model"]), ("minha.safetensors", ["200", 0]))
        # Qualidade alta sem estilo: o 9B no lugar do 4B
        g9 = t2i.grafo({**p, "modelo": "klein_edit", "qualidade_alta": True, "proporcao": "2:3 (Portrait Photo)", "megapixels": 0.9}, 1, "x")
        self.assertEqual(g9["1"]["inputs"]["unet_name"], t2i.MODELOS_TEXTO["klein9b_edit"]["unet"])
        gt = t2i.grafo_texto_klein(p, t2i.MODELOS_TEXTO["klein_t2i"], 1, "x", 832, 1216)
        self.assertEqual(gt["40"]["inputs"]["model"], ["200", 0])

    def test_qualidade_alta_no_gerar(self):
        p = {"modelo": "klein_t2i", "prompt": "a cat", "passos": 4, "proporcao": "2:3 (Portrait Photo)", "megapixels": 0.9, "loras": []}
        alto = t2i.MODELOS_TEXTO["klein9b_edit"]
        g = t2i.grafo({**p, "qualidade_alta": True}, 1, "x")
        # O grafo de texto (latente vazio) com o modelo e o codificador do 9B
        self.assertEqual((g["1"]["inputs"]["unet_name"], g["2"]["inputs"]["clip_name"], g["6"]["class_type"]),
                         (alto["unet"], alto["encoder"], "EmptyFlux2LatentImage"))
        g4 = t2i.grafo({**p, "qualidade_alta": False}, 1, "x")
        self.assertEqual(g4["1"]["inputs"]["unet_name"], t2i.MODELOS_TEXTO["klein_t2i"]["unet"])


class Validacao(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        entrada = Path(self.tmp.name)
        for n in ("base.png", "roupa.png"):
            (entrada / n).write_bytes(b"png")
        self.patches = [mock.patch.object(config, "ENTRADA", entrada), mock.patch.object(validacao, "faltam_texto", lambda k: [])]
        for p in self.patches:
            p.start()
        self.base = {"modelo": "klein_edit", "prompt": "", "partida": "base.png", "passos": 4, "estilo": "oleo"}

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_estilo_deixa_o_prompt_opcional(self):
        r = validacao.validar_texto({**self.base, "qualidade_alta": "sim"})
        self.assertEqual((r["estilo"], r["prompt"], r["qualidade_alta"]), ("oleo", "", False))
        with self.assertRaises(validacao.Erro):
            validacao.validar_texto({**self.base, "estilo": None})

    def test_regras_do_estilo(self):
        for caso, msg in [({"estilo": "nada"}, "Estilo desconhecido"), ({"modelo": "qwen21_edit"}, "só funciona no Editar"),
                          ({"referencia": "roupa.png"}, "só a imagem de partida"), ({"estilo": ["anime"]}, "Estilo desconhecido")]:
            with self.subTest(caso=caso), self.assertRaisesRegex(validacao.Erro, msg):
                validacao.validar_texto({**self.base, **caso})

    def test_falta_o_9b_ou_o_qwen(self):
        with mock.patch.object(validacao, "faltam_texto", lambda k: ["9b.safetensors"] if k == "klein9b_edit" else []):
            with self.assertRaisesRegex(validacao.Erro, "Klein 9B: faltam 9b.safetensors"):
                validacao.validar_texto({**self.base, "qualidade_alta": True})
            self.assertTrue(validacao.validar_texto({**self.base, "estilo": "realista"})["estilo"] == "realista")
        with mock.patch.object(validacao, "faltam_texto", lambda k: ["qwen.safetensors"] if k == "qwen21_edit" else []):
            with self.assertRaisesRegex(validacao.Erro, "Qwen 2.1"):
                validacao.validar_texto({**self.base, "estilo": "realista"})

    def test_sem_estilo_a_chave_vale_no_editar(self):
        r = validacao.validar_texto({**self.base, "estilo": "", "prompt": "make it red", "qualidade_alta": True})
        self.assertEqual((r["estilo"], r["qualidade_alta"]), (None, True))
        gerar = {"modelo": "klein_t2i", "prompt": "a cat", "passos": 4, "proporcao": "2:3 (Portrait Photo)", "megapixels": 0.9, "qualidade_alta": True}
        self.assertTrue(validacao.validar_texto(gerar)["qualidade_alta"])
        self.assertFalse(validacao.validar_texto({**gerar, "modelo": "z_image_turbo", "passos": 8})["qualidade_alta"])
        self.assertIn("loras_alta", next(m for m in validacao.modelos_texto() if m["id"] == "klein_t2i"))

    def test_9b_fora_do_seletor_e_dados_da_pagina(self):
        self.assertNotIn("klein9b_edit", [m["id"] for m in validacao.modelos_texto()])
        s = validacao.situacao_estilos()
        self.assertEqual((s["modelo"], len(s["lista"]), s["faltam_9b"]), ("klein_edit", len(estilos.ESTILOS), []))


class Plano(unittest.TestCase):
    def plano(self, a, faltam=()):
        import mcp_planejar
        with mock.patch.object(mcp_planejar, "_achar_midia", lambda n, tipo, erro: n), \
             mock.patch.object(mcp_planejar.acoes, "preparar_texto", lambda d: d), \
             mock.patch.object(validacao, "faltam_texto", lambda k: list(faltam) if k == "klein9b_edit" else []):
            return mcp_planejar._plano_de_imagem(a)

    def test_estilo_sem_prompt_e_resumo(self):
        d, resumo = self.plano({"imagens": ["selfie.png"], "estilo": "anime"})
        a = d["ajustes"]
        self.assertEqual((a["modelo"], a["estilo"], a["qualidade_alta"], a["prompt"]), ("klein_edit", "anime", False, ""))
        self.assertIn("mudar o estilo da imagem para Anime", resumo)
        self.assertIn("image 1: selfie.png", resumo)
        self.assertNotIn("Detalhe a mais", resumo)

    def test_realista_liga_a_qualidade_alta_se_o_9b_existe(self):
        self.assertTrue(self.plano({"imagens": ["d.png"], "estilo": "realista"})[0]["ajustes"]["qualidade_alta"])
        self.assertFalse(self.plano({"imagens": ["d.png"], "estilo": "realista"}, faltam=["9b"])[0]["ajustes"]["qualidade_alta"])
        d, resumo = self.plano({"imagens": ["d.png"], "estilo": "realista", "qualidade_alta": True, "prompt": "soft light"})
        self.assertIn("(qualidade alta)", resumo)
        self.assertIn("Detalhe a mais:\nsoft light", resumo)

    def test_erros_do_estilo_no_plano(self):
        for a, msg in [({"imagens": [], "estilo": "anime"}, "exatamente uma foto"), ({"imagens": ["a", "b"], "estilo": "anime"}, "exatamente uma foto"),
                       ({"imagens": ["a"], "estilo": "xx"}, "Estilo desconhecido"), ({"imagens": ["a"], "estilo": "anime", "qualidade_alta": "sim"}, "true ou false"),
                       ({"imagens": ["a"]}, "campo prompt")]:
            with self.subTest(a=a), self.assertRaisesRegex(validacao.Erro, msg):
                self.plano(a)

    def test_resumo_estilo_direto(self):
        r = planos.resumo_estilo({"quantidade": 2, "estilo": "lapis", "qualidade_alta": False, "prompt": ""}, "f.png")
        self.assertIn("2 resultados", r)
        self.assertIn("Tempo estimado", r)


if __name__ == "__main__":
    unittest.main()
