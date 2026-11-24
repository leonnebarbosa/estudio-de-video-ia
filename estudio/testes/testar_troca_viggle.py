"""Testes do motor "viggle" da troca (troca_viggle.py, converter_lora_viggle.py e as regras na validacao).
Nao usam o ComfyUI nem a placa.

Uso: python -I testar_troca_viggle.py
"""
import sys, tempfile, types, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import config, validacao
import converter_lora_viggle as conv
import troca_viggle as tv
import troca_wangp as tw
from testar_troca import P


class Grafo(unittest.TestCase):
    def setUp(self):
        self.g = tv.grafo("v.mp4", [(0, "a.png"), (94, "b.png")], "pedido", 544, 960, 124, 7, "troca/x_viggle")

    def test_video_primeiro_e_fotos_no_no_do_estudio(self):
        no = self.g["20"]
        self.assertEqual(no["class_type"], tv.NO)
        self.assertEqual(no["inputs"]["video"], ["2", 0])
        self.assertEqual((no["inputs"]["foto_1"], no["inputs"]["foto_2"]), (["40", 0], ["41", 0]))
        self.assertEqual((no["inputs"]["width"], no["inputs"]["height"], no["inputs"]["length"]), (544, 960, 124))

    def test_quadros_presos_em_cadeia_no_instante_de_cada_um(self):
        self.assertEqual(self.g["60"]["inputs"]["positive"], ["20", 0])
        self.assertEqual(self.g["61"]["inputs"]["positive"], ["60", 0])
        self.assertEqual([self.g[n]["inputs"]["frame_idx"] for n in ("60", "61")], [0, 94])

    def test_duas_passagens_com_os_presos_so_na_primeira(self):
        # 1a: ruido novo, condicionamento com os quadros presos, sigmas altos; 2a: sem ruido, sem os presos, a partir da 1a
        primeira, segunda = self.g[tv.NO_PRESOS]["inputs"], self.g[tv.NO_SOLTOS]["inputs"]
        self.assertEqual(self.g[primeira["guider"][0]]["inputs"]["conditioning"], ["61", 0])
        self.assertEqual(self.g[segunda["guider"][0]]["inputs"]["conditioning"], ["20", 0])
        self.assertEqual(self.g[primeira["noise"][0]]["class_type"], "RandomNoise")
        self.assertEqual(self.g[segunda["noise"][0]]["class_type"], "DisableNoise")
        self.assertEqual((primeira["sigmas"], segunda["sigmas"]), (["51", 0], ["51", 1]))
        self.assertEqual(segunda["latent_image"], [tv.NO_PRESOS, 0])
        self.assertEqual(self.g["51"]["inputs"]["step"], 4)

    def test_sigmas_do_wangp_e_som_preso(self):
        sigmas = [float(s) for s in self.g["50"]["inputs"]["sigmas"].split(",")]
        self.assertEqual(sigmas, [1.0, 0.990476, 0.965243, 0.923077, 0.8, 0.631579, 0.0])
        # So os 4 primeiros passos comecam com sigma >= 0,9 (WanGP viggle.py)
        self.assertEqual(sum(s >= 0.9 for s in sigmas[:-1]), tv.PASSOS_PRESOS)
        self.assertEqual(self.g["28"]["class_type"], "PixaromaH3AudioSync")
        self.assertEqual(self.g[tv.NO_PRESOS]["inputs"]["latent_image"], ["28", 1])
        self.assertEqual(self.g["25"]["inputs"]["audio"], ["28", 2])
        self.assertEqual(self.g["11"]["inputs"]["lora_name"], tv.LORA)

    def test_todo_no_citado_existe(self):
        for no in self.g.values():
            for valor in no["inputs"].values():
                if isinstance(valor, list) and len(valor) == 2 and isinstance(valor[0], str):
                    self.assertIn(valor[0], self.g)


class Avisos(unittest.TestCase):
    def evento(self, no, valor, maximo, estado="running"):
        return {"type": "progress_state", "data": {"nodes": {no: {"state": estado, "value": valor, "max": maximo}}}}

    def test_passo_soma_as_duas_passagens(self):
        self.assertEqual(tv.passo_do_evento(self.evento(tv.NO_PRESOS, 3, 4)), 3)
        self.assertEqual(tv.passo_do_evento(self.evento(tv.NO_SOLTOS, 1, 2)), 5)
        self.assertIsNone(tv.passo_do_evento(self.evento("23", 1, 1)))
        self.assertIsNone(tv.passo_do_evento(self.evento(tv.NO_PRESOS, 4, 4, "finished")))
        self.assertIsNone(tv.passo_do_evento({"type": "status"}))

    def test_video_gerado_e_o_do_no_que_salva(self):
        saidas = {"1": {"images": [{"filename": "entrada.mp4", "subfolder": "", "type": "input"}]},
                  tv.NO_VIDEO: {"images": [{"filename": "x_viggle_00001_.mp4", "subfolder": "troca", "type": "output"}]}}
        self.assertEqual(tv.arquivo_gerado(saidas), config.SAIDA / "troca" / "x_viggle_00001_.mp4")
        self.assertIsNone(tv.arquivo_gerado({"1": saidas["1"]}))


class Gerar(unittest.TestCase):
    def test_copia_os_pintados_roda_e_limpa(self):
        with tempfile.TemporaryDirectory() as d:
            entrada = Path(d)
            pintado = entrada / "pintado.png"
            pintado.write_bytes(b"p")
            vistos = {}

            def rodar(g, limite):
                vistos["fotos"] = [g[n]["inputs"]["image"] for n in ("40", "41")]
                vistos["na_entrada"] = all((entrada / f).is_file() for f in vistos["fotos"])
                return {"status": "success", "erro": "", "saidas": {tv.NO_VIDEO: {"images": [{"filename": "v.mp4", "subfolder": "troca"}]}}}

            ouvintes, passos = [], []
            with mock.patch.object(config, "ENTRADA", entrada):
                r, video = tv.gerar("proj", "v.mp4", [(0, pintado), (94, pintado)], "pedido", 544, 960, 124, 7, rodar, ouvintes.append, passos.append)
            # Os pintados vao para os temporarios do projeto (entrada_temp) e saem depois
            self.assertEqual(vistos["fotos"], ["estudio/temp/proj/viggle_proj_000.png", "estudio/temp/proj/viggle_proj_094.png"])
            self.assertTrue(vistos["na_entrada"])
            self.assertEqual([f for f in entrada.rglob("*") if f.is_file()], [pintado])
            self.assertEqual(video, config.SAIDA / "troca" / "v.mp4")
            ouvintes[0].evento({"type": "progress_state", "data": {"nodes": {tv.NO_SOLTOS: {"state": "running", "value": 2, "max": 2}}}})
            self.assertEqual(passos, [6])

    def test_sem_sucesso_nao_ha_video(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "ENTRADA", Path(d)):
            r, video = tv.gerar("proj", "v.mp4", [], "pedido", 544, 960, 124, 7, lambda g, limite: {"status": "error", "erro": "x", "saidas": {}})
        self.assertIsNone(video)


class Pintor(unittest.TestCase):
    def test_pedido_poe_a_pessoa_primeiro_e_o_quadro_por_ultimo(self):
        # No pedido do WanGP "image 1" e o quadro e "image 2" a pessoa; no ComfyUI a pessoa entra primeiro
        texto = tv.pedido_do_pintor(tw.PINTOR["video"])
        self.assertTrue(texto.startswith("Replace the person in <image2> with the person from <image1>:"))
        self.assertIn("same clothes as in <image2>", texto)
        self.assertIn("exactly as in <image2>", texto)
        self.assertNotIn("image 1", texto)
        self.assertNotIn("image 2", texto)
        self.assertIn("with the character from <image1>, including their clothes", tv.pedido_do_pintor(tw.PINTOR["foto"]))

    def test_grafo_do_pintor(self):
        g = tv.grafo_pintor("quadro.png", "pessoa.png", tw.PINTOR["video"], 7, "troca/x_pintado_000")
        self.assertEqual((g["30"]["inputs"]["image"], g["31"]["inputs"]["image"]), ("pessoa.png", "quadro.png"))
        # A pessoa e a imagem 1 e o quadro a imagem 2; o latente vazio vem do quadro sozinho
        self.assertEqual((g["4"]["inputs"]["images.image_1"], g["4"]["inputs"]["images.image_2"]), (["30", 0], ["31", 0]))
        self.assertEqual(g["5"]["inputs"]["images.image_1"], ["31", 0])
        self.assertEqual(g["6"]["inputs"]["latent_image"], ["5", 2])
        self.assertEqual(g["1"]["inputs"]["unet_name"], tv.PINTOR_MODELO)
        self.assertEqual(g["11"]["inputs"]["lora_name"], tv.PINTOR_LORA)
        self.assertEqual(len(g["42"]["inputs"]["sigmas"].split(",")), 7)
        self.assertEqual(g["40"]["inputs"]["cfg"], 1)
        for no in g.values():
            for valor in no["inputs"].values():
                if isinstance(valor, list) and len(valor) == 2 and isinstance(valor[0], str):
                    self.assertIn(valor[0], g)

    def pastas(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        raiz = Path(d.name)
        for nome in ("entrada", "saida/troca", "proj"):
            (raiz / nome).mkdir(parents=True)
        for alvo, valor in (("ENTRADA", raiz / "entrada"), ("SAIDA", raiz / "saida")):
            m = mock.patch.object(config, alvo, valor)
            m.start()
            self.addCleanup(m.stop)
        return raiz

    def test_pinta_cada_quadro_e_pula_o_que_ja_existe(self):
        raiz = self.pastas()
        quadros = []
        for q in (0, 62):
            (raiz / "proj" / f"quadro_{q:03d}.png").write_bytes(b"o")
            quadros.append((q, raiz / "proj" / f"quadro_{q:03d}.png", raiz / "proj" / f"pintado_{q:03d}.png"))
        (raiz / "proj" / "pintado_000.png").write_bytes(b"ja pintado")
        rodados, feitos = [], []

        def rodar(g, limite):
            rodados.append(g["31"]["inputs"]["image"])
            self.assertTrue((raiz / "entrada" / rodados[-1]).is_file())
            (raiz / "saida" / "troca" / "p.png").write_bytes(b"novo")
            return {"status": "success", "erro": "", "pico_vram": 9000, "temp_max": 66, "saidas": {tv.NO_PINTADO: {"images": [{"filename": "p.png", "subfolder": "troca"}]}}}

        r = tv.pintar("proj", quadros, "pessoa.png", tw.PINTOR["video"], 7, rodar, feitos.append)
        self.assertEqual(rodados, ["estudio/temp/proj/viggle_proj_quadro_062.png"])
        self.assertEqual((raiz / "proj" / "pintado_062.png").read_bytes(), b"novo")
        self.assertEqual((raiz / "proj" / "pintado_000.png").read_bytes(), b"ja pintado")
        self.assertEqual(feitos, [1, 2])
        self.assertEqual((r["status"], r["pico_vram"], r["temp_max"]), ("success", 9000, 66))
        # Nada fica para tras na entrada nem na saida do ComfyUI
        self.assertEqual([f for f in (raiz / "entrada").rglob("*") if f.is_file()], [])
        self.assertEqual(list((raiz / "saida" / "troca").iterdir()), [])

    def test_para_no_quadro_que_falha(self):
        raiz = self.pastas()
        quadros = []
        for q in (0, 62):
            (raiz / "proj" / f"quadro_{q:03d}.png").write_bytes(b"o")
            quadros.append((q, raiz / "proj" / f"quadro_{q:03d}.png", raiz / "proj" / f"pintado_{q:03d}.png"))
        chamadas, feitos = [], []

        def rodar(g, limite):
            chamadas.append(1)
            return {"status": "error", "erro": "sem memória", "pico_vram": 0, "temp_max": 0, "saidas": {}}

        r = tv.pintar("proj", quadros, "pessoa.png", "pedido", 7, rodar, feitos.append)
        self.assertEqual((len(chamadas), feitos, r["status"]), (1, [], "error"))
        vazio = tv.pintar("proj", quadros, "pessoa.png", "pedido", 7, lambda g, limite: {"status": "success", "erro": "", "pico_vram": 0, "temp_max": 0, "saidas": {}})
        self.assertEqual(vazio["status"], "sem imagem")

    def test_falta_do_pintor(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "MODELOS", Path(d)), mock.patch.object(tv.loras, "mapa", lambda: {}):
            self.assertEqual(len(tv.falta_do_pintor()), 4)
            for pasta, nome in (("diffusion_models", tv.PINTOR_MODELO), ("text_encoders", tv.PINTOR_CODIFICADOR), ("vae", tv.PINTOR_VAE)):
                (Path(d) / pasta).mkdir()
                (Path(d) / pasta / nome).write_bytes(b"x")
            self.assertEqual(tv.falta_do_pintor(), [f"loras/qwen/{tv.PINTOR_LORA}"])


class Preparar(unittest.TestCase):
    def setUp(self):
        m = mock.patch.object(tv, "falta_do_pintor", lambda: [])
        m.start()
        self.addCleanup(m.stop)

    def test_sem_os_arquivos_do_pintor(self):
        with mock.patch.object(tv, "falta_do_pintor", lambda: ["vae/x.safetensors"]):
            self.assertIn("faltam os arquivos do pintor", tv.preparar())

    def test_sem_a_lora_convertida_nem_a_de_origem(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(tv.loras, "mapa", lambda: {}), mock.patch.object(tv.loras, "pasta", lambda: Path(d)):
            self.assertIn("falta a LoRA", tv.preparar())
            self.assertIn("viggle_remake_edit_bf16", tv.preparar("edit"))

    def test_tudo_no_lugar(self):
        with mock.patch.object(tv.loras, "mapa", lambda: {tv.LORA.lower(): "h3\\" + tv.LORA}), \
             mock.patch.object(tv, "instalar_no", lambda: False), mock.patch.object(tv, "no_carregado", lambda: True):
            self.assertIsNone(tv.preparar())

    def test_no_novo_reinicia_o_comfy(self):
        with mock.patch.object(tv.loras, "mapa", lambda: {tv.LORA.lower(): tv.LORA}), mock.patch.object(tv, "instalar_no", lambda: True), \
             mock.patch.object(tv, "reiniciar_comfy", lambda: False), mock.patch("builtins.print"):
            self.assertIn("Reinicie o estúdio", tv.preparar())

    def test_instalar_no_copia_so_se_mudou(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "RAIZ_COMFY", Path(d)):
            self.assertTrue(tv.instalar_no())
            destino = Path(d) / "ComfyUI" / "custom_nodes" / tv.PASTA_NO / "__init__.py"
            self.assertEqual(destino.read_bytes(), (config.ESTUDIO / "nos_comfy" / tv.PASTA_NO / "__init__.py").read_bytes())
            self.assertFalse(tv.instalar_no())


class Conversor(unittest.TestCase):
    def test_nomes_do_comfyui(self):
        self.assertEqual(conv.nome_no_comfy("transformer_blocks.3.attn.to_q.lora_A.weight"), ("blocks.3.attn.q_proj", "lora_A", False))
        self.assertEqual(conv.nome_no_comfy("transformer_blocks.3.attn.to_out.0.lora_B.weight"), ("blocks.3.attn.out_proj", "lora_B", False))
        self.assertEqual(conv.nome_no_comfy("transformer.transformer_blocks.49.ff.net.0.proj.lora_B.weight"), ("blocks.49.mlp.fc1", "lora_B", True))
        self.assertEqual(conv.nome_no_comfy("transformer_blocks.0.ff.net.2.lora_A.weight"), ("blocks.0.mlp.fc2", "lora_A", False))
        self.assertEqual(conv.nome_no_comfy("proj_in.lora_A.weight"), ("video_patch_proj", "lora_A", False))
        self.assertEqual(conv.nome_no_comfy("proj_out.lora_B.weight"), ("final_layer.video_out", "lora_B", False))
        with self.assertRaises(conv.NaoConverte):
            conv.nome_no_comfy("transformer_blocks.0.attn.to_q.alpha")

    def test_converte_um_bloco_pequeno(self):
        import json, struct
        import torch
        from safetensors.torch import load_file, save_file
        r, d, h = 2, 4, 6  # posto, largura do bloco, largura de cada um de q, k, v
        pesos = {}
        for i, p in enumerate("qkv"):
            pesos[f"transformer_blocks.0.attn.to_{p}.lora_A.weight"] = torch.full((r, d), float(i + 1))
            pesos[f"transformer_blocks.0.attn.to_{p}.lora_B.weight"] = torch.full((h, r), float(i + 1))
        pesos["transformer_blocks.0.ff.net.0.proj.lora_A.weight"] = torch.ones(r, d)
        pesos["transformer_blocks.0.ff.net.0.proj.lora_B.weight"] = torch.cat([torch.zeros(4, r), torch.ones(4, r)])
        with tempfile.TemporaryDirectory() as pasta:
            pasta = Path(pasta)
            save_file(pesos, str(pasta / "lora.safetensors"))
            cab = json.dumps({"diffusion_model.blocks.0.attn.qkv_proj.weight": {"dtype": "F32", "shape": [3 * h, d], "data_offsets": [0, 0]},
                              "diffusion_model.blocks.0.mlp.fc1.weight": {"dtype": "F32", "shape": [8, d], "data_offsets": [0, 0]}}).encode()
            (pasta / "base.safetensors").write_bytes(struct.pack("<Q", len(cab)) + cab)
            self.assertEqual(conv.converter(pasta / "lora.safetensors", pasta / "base.safetensors", pasta / "saida.safetensors"), 2)
            novo = load_file(str(pasta / "saida.safetensors"))
            a, b = novo["blocks.0.attn.qkv_proj.lora_A.weight"], novo["blocks.0.attn.qkv_proj.lora_B.weight"]
            self.assertEqual((tuple(a.shape), tuple(b.shape)), ((3 * r, d), (3 * h, 3 * r)))
            # B em blocos na diagonal: o produto B.A da as linhas de q, depois k, depois v, cada uma com o seu par
            produto = b @ a
            for i in range(3):
                self.assertTrue(torch.all(produto[i * h:(i + 1) * h] == (i + 1) ** 2 * r))
            # As duas metades do fc1 trocadas
            self.assertTrue(torch.equal(novo["blocks.0.mlp.fc1.lora_B.weight"], torch.cat([torch.ones(4, r), torch.zeros(4, r)])))
            with self.assertRaises(conv.NaoConverte):
                conv.converter(pasta / "lora.safetensors", pasta / "base.safetensors", pasta / "saida.safetensors")

    def test_recusa_o_que_nao_bate_com_o_modelo(self):
        import json, struct
        import torch
        from safetensors.torch import save_file
        with tempfile.TemporaryDirectory() as pasta:
            pasta = Path(pasta)
            save_file({"proj_in.lora_A.weight": torch.ones(2, 4), "proj_in.lora_B.weight": torch.ones(6, 2)}, str(pasta / "lora.safetensors"))
            cab = json.dumps({"diffusion_model.video_patch_proj.weight": {"dtype": "F32", "shape": [7, 4], "data_offsets": [0, 0]}}).encode()
            (pasta / "base.safetensors").write_bytes(struct.pack("<Q", len(cab)) + cab)
            with self.assertRaises(conv.NaoConverte):
                conv.converter(pasta / "lora.safetensors", pasta / "base.safetensors", pasta / "saida.safetensors")
            self.assertFalse((pasta / "saida.safetensors").exists())


class Regras(unittest.TestCase):
    def setUp(self):
        opcoes = {"modelos": [P["modelo"]], "samplers": ["euler"], "agendadores": ["beta", "simple"], "upscalers": [P["upscaler"]],
                  "loras_troca": {"troca": [P["troca"][0]], "turbo": [P["turbo"][0]], "nitidez": [P["nitidez"][0]]}, "loras": [], "loras_estilo": []}
        for alvo, nome, valor in ((validacao.ambiente, "ler_opcoes", lambda: opcoes), (validacao, "validar_loras_video", lambda r, x: None)):
            m = mock.patch.object(alvo, nome, valor)
            m.start()
            self.addCleanup(m.stop)

    def test_fala_e_um_ajuste_desligado_por_padrao(self):
        self.assertIs(validacao.validar_troca({"esrgan": False})["fala"], False)
        self.assertIs(validacao.validar_troca({"esrgan": False, "fala": True})["fala"], True)
        self.assertIs(validacao.validar_troca({"esrgan": False, "fala": "sim"})["fala"], False)

    def test_regras_do_viggle(self):
        self.assertEqual(validacao.validar_troca({"motor": "viggle", "esrgan": False})["motor"], "viggle")
        with self.assertRaises(validacao.Erro):
            validacao.validar_troca({"motor": "viggle", "esrgan": False, "upscale": True, "upscale_megapixels": 1.0})
        with self.assertRaises(validacao.Erro):
            validacao.validar_troca({"motor": "viggle", "esrgan": False, "loras": [["x.safetensors", 0.8]]})

    def test_motor_antigo_vira_viggle(self):
        # Um rascunho ou projeto de quando o WanGP rodava esta receita
        self.assertEqual(validacao.validar_troca({"motor": "wangp", "esrgan": False})["motor"], "viggle")
        self.assertEqual(validacao.MOTORES_TROCA, ("estudio", "viggle", "wan"))
        self.assertFalse(hasattr(config, "WANGP"))

class Fala(unittest.TestCase):
    def test_sem_fala_o_pedido_nao_muda(self):
        texto = tw.prompt_viggle([0, 108], "video")
        self.assertEqual(texto, tw.prompt_viggle([0, 108], "video", False))
        self.assertNotIn("(S1)", texto)
        self.assertIn("the face, hair and clothing stay identical in every frame", texto)
        self.assertTrue(texto.split("overall_soundscape:\n")[1].startswith("The soundtrack of <Video 1>, unchanged.\n"))

    def test_com_fala_marca_quem_fala_e_solta_a_boca(self):
        texto = tw.prompt_viggle([0, 108], "video", True)
        # A frase do WanGP, com o instante em que a fala comeca e sem as palavras
        self.assertIn("From 00:00.000, <Subject 1> (S1) is speaking with natural lip movements synchronized, <d>[unclear]</d>.", texto)
        self.assertNotIn("the face, hair and clothing stay identical", texto)
        self.assertIn("the mouth moves with the speech", texto)
        self.assertIn("with the voice of <Subject 1> (S1)", texto)
        self.assertEqual([s.split(":")[0] for s in texto.split("\n\n")],
                         ["subject_definitions", "summary", "retention_analysis", "detailed_description", "overall_soundscape", "non_diegetic_music"])
        self.assertNotIn(" dim", texto.lower())


class Taxa(unittest.TestCase):
    def test_so_converte_o_que_nao_esta_a_24(self):
        import acabamento
        chamadas = []
        with mock.patch.object(acabamento, "fps_de", lambda a: "24"), mock.patch.object(tw, "ffmpeg", lambda *a: chamadas.append(a)):
            self.assertFalse(tw.garantir_24fps(Path("v.mp4")))
        self.assertEqual(chamadas, [])
        with mock.patch.object(acabamento, "fps_de", lambda a: "30"), mock.patch.object(tw, "ffmpeg", lambda *a: chamadas.append(a)), \
             mock.patch.object(tw.os, "replace") as troca:
            self.assertTrue(tw.garantir_24fps(Path("pasta") / "v.mp4"))
        self.assertIn("fps=24", chamadas[0])
        self.assertEqual(troca.call_args.args, (Path("pasta") / "v_24fps.mp4", Path("pasta") / "v.mp4"))


if __name__ == "__main__":
    unittest.main()
