"""Testes da aba Imagem para video (Wan). Nao usam o ComfyUI nem a placa.

Uso: python -I testar_wan.py
"""
import json, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import comunidade  # noqa: F401 (poe os modelos falsos da comunidade)
import acoes, config, projetos, validacao
from wan_para_video import MODELOS_WAN, Progresso, grafo, quadros_wan, tamanho_wan


def instalado(modelo):
    return []


class Contas(unittest.TestCase):
    def test_quadros_4k_mais_1(self):
        self.assertEqual([quadros_wan(s) for s in validacao.DURACOES_WAN], [33, 49, 65, 81])

    def test_tamanho_testado_e_multiplos_de_16(self):
        self.assertEqual(tamanho_wan("2:3 (Portrait Photo)", 0.475), (576, 864))
        for prop in validacao.PROPORCOES:
            for mp in validacao.QUALIDADES_WAN:
                w, h = tamanho_wan(prop, mp)
                self.assertEqual((w % 16, h % 16), (0, 0), (prop, mp))


class Grafo(unittest.TestCase):
    P = {"prompt": "a dog runs", "negativo": "blurry", "modelo": "comunidade", "duracao": 5, "proporcao": "2:3 (Portrait Photo)", "megapixels": 0.475}

    def test_modelo_da_comunidade_sem_lora_e_shift_5(self):
        g = grafo(self.P, "foto.png", 42, "wan/x/video")
        m = MODELOS_WAN["comunidade"]
        self.assertEqual((g["10"]["class_type"], g["10"]["inputs"]["unet_name"], g["20"]["inputs"]["unet_name"]), ("UNETLoader", m["alta"], m["baixa"]))
        self.assertNotIn("11", g)
        self.assertNotIn("21", g)
        self.assertEqual((g["12"]["inputs"]["model"], g["12"]["inputs"]["shift"], g["22"]["inputs"]["shift"]), (["10", 0], 5, 5))

    def test_gguf_com_lightx2v_e_shift_8(self):
        g = grafo({**self.P, "modelo": "wan22"}, "foto.png", 42, "wan/x/video")
        self.assertEqual(g["10"]["class_type"], "UnetLoaderGGUF")
        self.assertNotIn("weight_dtype", g["10"]["inputs"])
        self.assertEqual((g["11"]["inputs"]["model"], g["12"]["inputs"]["model"], g["12"]["inputs"]["shift"]), (["10", 0], ["11", 0], 8))
        self.assertIn("high_noise", g["11"]["inputs"]["lora_name"])
        self.assertIn("low_noise", g["21"]["inputs"]["lora_name"])

    def test_imagem_tamanho_quadros_e_passos(self):
        g = grafo({**self.P, "duracao": 3}, "foto.png", 7, "wan/x/video")
        self.assertEqual(g["50"]["inputs"]["image"], "foto.png")
        self.assertEqual((g["51"]["inputs"]["width"], g["51"]["inputs"]["height"], g["51"]["inputs"]["length"]), (576, 864, 49))
        alta, baixa = g["60"]["inputs"], g["61"]["inputs"]
        self.assertEqual((alta["noise_seed"], baixa["noise_seed"], alta["steps"], alta["cfg"]), (7, 7, 4, 1.0))
        self.assertEqual((alta["start_at_step"], alta["end_at_step"], baixa["start_at_step"], baixa["end_at_step"]), (0, 2, 2, 4))
        self.assertEqual((alta["model"], baixa["model"], baixa["latent_image"]), (["12", 0], ["22", 0], ["60", 0]))
        self.assertEqual((g["71"]["inputs"]["fps"], g["72"]["inputs"]["filename_prefix"]), (16, "wan/x/video"))
        self.assertEqual((g["31"]["inputs"]["text"], g["32"]["inputs"]["text"]), ("a dog runs", "blurry"))

    def test_nos_ligados_existem(self):
        for modelo in MODELOS_WAN:
            g = grafo({**self.P, "modelo": modelo}, "f.png", 1, "x")
            for k, no in g.items():
                for v in no["inputs"].values():
                    if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str):
                        self.assertIn(v[0], g, f"{modelo}: no {k} aponta para {v[0]}")


class Andamento(unittest.TestCase):
    def test_passo_somado_das_duas_metades(self):
        with tempfile.TemporaryDirectory() as d:
            pr = Progresso(Path(d) / "progresso.json", mock.Mock(ultimo=None), grafo(Grafo.P, "f.png", 1, "x"))
            pr.evento({"type": "progress_state", "data": {"nodes": {"60": {"state": "running", "value": 1, "max": 2}}}})
            self.assertEqual((pr.valor, pr.metade), (1, "alta"))
            pr.evento({"type": "progress_state", "data": {"nodes": {"61": {"state": "running", "value": 2, "max": 2}}}})
            self.assertEqual((pr.valor, pr.metade), (4, "baixa"))
            dados = json.loads((Path(d) / "progresso.json").read_text(encoding="utf-8"))
            self.assertEqual((dados["valor"], dados["maximo"], dados["fase"]), (4, 4, "amostrar"))


class ProjetoEAcoes(unittest.TestCase):
    def test_projeto_lido_pela_pagina(self):
        with tempfile.TemporaryDirectory() as d:
            pasta = Path(d) / "wan_cachorro"
            pasta.mkdir()
            (pasta / "interface.json").write_text(json.dumps({"tipo": "wan", "prompt": "a dog runs", "modelo": "comunidade"}), encoding="utf-8")
            (pasta / "estado.json").write_text(json.dumps({"tipo": "wan", "personagem": "nao_existe.png"}), encoding="utf-8")
            p = projetos.ler_projeto(pasta)
            self.assertEqual((p["tipo"], p["completo"], p["final"], p["ideia"], p["foto_existe"]), ("wan", False, None, "a dog runs", False))
            (pasta / "final.mp4").write_bytes(b"mp4")
            self.assertTrue(projetos.ler_projeto(pasta)["completo"])

    def test_saida_do_comfy_entra_no_apagar(self):
        self.assertIn("wan", projetos.PASTAS_SAIDA)

    def test_iniciar_pela_aba_imagem_com_o_wan(self):
        """O Wan sai pela aba Imagem para video: o projeto e do tipo imagem, com o modelo escolhido."""
        with tempfile.TemporaryDirectory() as d:
            entrada = Path(d) / "entrada"
            entrada.mkdir()
            (entrada / "f.png").write_bytes(b"png")
            with mock.patch.object(config, "PROJETOS", Path(d)), mock.patch.object(config, "ENTRADA", entrada), mock.patch.object(validacao, "arquivos_que_faltam", instalado), \
                    mock.patch.object(acoes, "exigir_comfy_livre", lambda: None), mock.patch.object(acoes.tarefa.tarefa, "rodando", lambda: False), \
                    mock.patch.object(acoes.tarefa.tarefa, "iniciar_imagem") as iniciar:
                tomada = {"acao": "a dog runs", "fala": "", "som": "", "camera": "parada", "olhar": False, "duracao": 2}
                acoes.acao_iniciar_imagem({"projeto": "wan_x", "foto": "f.png", "autorizacao": True,
                                           "ajustes": {"modelo": "wan22", "megapixels": 0.475, "tomadas": [tomada]}})
            iniciar.assert_called_once_with("wan_x")
            p = json.loads((Path(d) / "wan_x" / "interface.json").read_text(encoding="utf-8"))
            self.assertEqual((p["tipo"], p["modelo"], p["tomadas"][0]["duracao"]), ("imagem", "wan22", 2.0))

    def test_aba_modelos_protege_os_arquivos(self):
        import modelos
        import extras
        trechos = modelos._trechos_do_codigo(config.ESTUDIO)
        for k, m in MODELOS_WAN.items():
            if k != comunidade.WAN:  # o falso dos testes nao esta no codigo nem no arquivo local
                self.assertEqual(modelos._abas_que_usam(Path(m["alta"]), trechos), [modelos.IMAGEM], m["alta"])
        # Um modelo do arquivo local (modelos_locais.json) tambem conta como usado: nao ganha o botao Apagar
        with mock.patch.object(extras, "_lido", {"wan": {"local": {"alta": "Local_Wan_HIGH.safetensors", "baixa": "Local_Wan_LOW.safetensors"}}}):
            trechos = modelos._trechos_do_codigo(config.ESTUDIO)
        self.assertEqual(modelos._abas_que_usam(Path("Local_Wan_HIGH.safetensors"), trechos), [modelos.IMAGEM])


class TomadasDoWan(unittest.TestCase):
    """O Wan dentro da aba Imagem para video: varias tomadas, cada uma partindo do ultimo quadro da anterior."""
    TOMADA = {"acao": "the cat jumps into the basket", "fala": "oi", "som": "birds", "camera": "parada", "olhar": False, "duracao": 3}

    def ajustes(self, **x):
        return {"modelo": "comunidade", "proporcao": "2:3 (Portrait Photo)", "megapixels": 0.475, "tomadas": [dict(self.TOMADA), dict(self.TOMADA, duracao=2)], **x}

    @mock.patch.object(validacao, "arquivos_que_faltam", instalado)
    def test_validacao_usa_as_listas_do_modelo(self):
        r = validacao.validar_imagem(self.ajustes(referencias=["x.png"]))
        self.assertEqual((r["modelo"], [t["duracao"] for t in r["tomadas"]], r["referencias"]), ("comunidade", [3.0, 2.0], []))
        # A fala fica guardada (volta se trocar para o H3), mas o Wan exige a acao
        self.assertEqual(r["tomadas"][0]["fala"], "oi")
        for errado in (self.ajustes(megapixels=0.4746), self.ajustes(acabamento="refino"), self.ajustes(tomadas=[dict(self.TOMADA, duracao=4.25)]),
                       self.ajustes(tomadas=[dict(self.TOMADA, acao="")]), self.ajustes(modelo="outro")):
            with self.assertRaises(validacao.Erro):
                validacao.validar_imagem(errado)
        # No H3, so a fala basta e as duracoes sao as dele
        h3 = validacao.validar_imagem({"tomadas": [dict(self.TOMADA, acao="", duracao=4.25)]})
        self.assertEqual(h3["modelo"], "h3")

    def test_modelo_nao_instalado_e_recusado(self):
        with mock.patch.object(validacao, "arquivos_que_faltam", lambda m: ["alta.gguf"]):
            with self.assertRaises(validacao.Erro):
                validacao.validar_imagem(self.ajustes())
            self.assertEqual([m["faltam"] for m in validacao.modelos_imagem()][0], [])

    def test_prompt_e_grafo_da_tomada(self):
        import imagem_para_video as ipv
        t = dict(self.TOMADA, camera="aproximar", olhar=True)
        texto = ipv.prompt_wan(t)
        self.assertIn(ipv.CAMERAS["aproximar"], texto)
        self.assertIn("looks straight at the camera", texto)
        self.assertNotIn("oi", texto)
        self.assertNotIn("birds", texto)
        g = ipv.grafo_wan({"modelo": "wan22", "proporcao": "2:3 (Portrait Photo)", "megapixels": 0.3, "negativo": "blurry"}, t, "ref2.png", "imagem/x/tomada2", 9)
        self.assertEqual((g["50"]["inputs"]["image"], g["51"]["inputs"]["length"], g["10"]["class_type"], g["32"]["inputs"]["text"]), ("ref2.png", 49, "UnetLoaderGGUF", "blurry"))
        self.assertTrue(ipv.eh_wan({"modelo": "comunidade"}))
        self.assertFalse(ipv.eh_wan({}))

    def test_juntar_tira_o_quadro_repetido_e_sai_sem_som(self):
        import imageio_ffmpeg, imagem_para_video as ipv
        from continuar_video import ler_quadros, tem_audio
        with tempfile.TemporaryDirectory() as d:
            pasta = Path(d)
            for nome, n in (("t1.mp4", 17), ("t2.mp4", 13)):
                import subprocess
                subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc=size=64x96:rate=16", "-frames:v", str(n),
                                "-pix_fmt", "yuv420p", str(pasta / nome)], check=True)
            ipv.juntar_sem_audio(pasta, [{"arquivo": "t1.mp4", "pular": 0, "total": 17}, {"arquivo": "t2.mp4", "pular": 1, "total": 13}], 16)
            self.assertEqual(len(ler_quadros(pasta / "final.mp4")), 29)
            self.assertFalse(tem_audio(pasta / "final.mp4"))

    def test_andamento_soma_os_passos(self):
        import imagem_para_video as ipv
        with tempfile.TemporaryDirectory() as d:
            pr = ipv.Progresso(Path(d) / "p.json", 1, mock.Mock(ultimo=None))
            pr.grafo(grafo(Grafo.P, "f.png", 1, "x"))
            pr.evento({"type": "progress_state", "data": {"nodes": {"61": {"state": "running", "value": 1, "max": 2}}}})
            self.assertEqual((pr.valor, pr.maximo), (3, 4))

    @mock.patch.object(validacao, "arquivos_que_faltam", instalado)
    def test_fluidez_ligada_por_padrao_so_no_wan(self):
        self.assertIs(validacao.validar_imagem(self.ajustes())["fluidez"], True)
        self.assertIs(validacao.validar_imagem(self.ajustes(fluidez=False))["fluidez"], False)
        self.assertIs(validacao.validar_imagem(self.ajustes(fluidez="sim"))["fluidez"], False)
        # O H3 nao passa pelo RIFE, mesmo se a pagina mandar
        self.assertIs(validacao.validar_imagem({"fluidez": True, "tomadas": [dict(self.TOMADA)]})["fluidez"], False)

    def test_suavizar_so_falta_no_wan_com_a_chave(self):
        import imagem_para_video as ipv
        self.assertTrue(ipv.falta_suavizar({"modelo": "comunidade", "fluidez": True}, {}))
        self.assertFalse(ipv.falta_suavizar({"modelo": "comunidade", "fluidez": True}, {"suavizado": True}))
        self.assertFalse(ipv.falta_suavizar({"modelo": "comunidade", "fluidez": False}, {}))
        self.assertFalse(ipv.falta_suavizar({"fluidez": True}, {}))
        g = ipv.grafo_suave("x.mp4", "imagem/p/suave")
        self.assertEqual((g["1"]["inputs"]["file"], g["3"]["inputs"]["ckpt_name"], g["3"]["inputs"]["multiplier"], g["4"]["inputs"]["fps"]), ("x.mp4", "rife49.pth", 2, 32))
        self.assertEqual(g["3"]["inputs"]["frames"], ["2", 0])

    def test_apagar_leva_o_temporario_do_rife(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            (base / "projetos" / "wan_p").mkdir(parents=True)
            (base / "projetos" / "wan_p" / "estado.json").write_text("{}", encoding="utf-8")
            (base / "entrada").mkdir()
            (base / "entrada" / "imagem_wan_p_1794240000_suave.mp4").write_bytes(b"x")
            (base / "saida").mkdir()
            with mock.patch.object(config, "PROJETOS", base / "projetos"), mock.patch.object(config, "ENTRADA", base / "entrada"), mock.patch.object(config, "SAIDA", base / "saida"):
                _, arquivos = projetos.alvos_apagar("wan_p")
            self.assertEqual([f.name for f in arquivos], ["imagem_wan_p_1794240000_suave.mp4"])

    def test_refazer_e_acabar_seguem_o_modelo_do_projeto(self):
        self.assertEqual(acoes.modelo_do_projeto({})["id"], "h3")
        with mock.patch.object(validacao, "arquivos_que_faltam", instalado):
            m = acoes.modelo_do_projeto({"modelo": "comunidade"})
        self.assertEqual((m["fala"], m["fps"], "refino" in m["acabamentos"]), (False, 16, False))


class LorasDeEstilo(unittest.TestCase):
    """Pares HIGH/LOW de LoRAs de estilo do Wan: achados pelo nome, um em cada modelo, validados contra a lista do ComfyUI."""
    LISTA = ["wan/estilo-22-H-e8.safetensors", "wan/estilo-22-L-e8.safetensors", "wan/wan_2.2_i2v_zoom_high_v2.0.safetensors",
             "wan/wan_2.2_i2v_zoom_low_v2.0.safetensors", "wan/wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors",
             "wan/wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors", "wan/so_high.safetensors", "Wan22_Estilo_HighNoise.safetensors",
             "Wan22_Estilo_LowNoise.safetensors", "h3/algo_high.safetensors", "h3/algo_low.safetensors"]

    def test_pares_pelo_nome(self):
        import loras
        pares = loras.pares_wan(self.LISTA)
        self.assertEqual([(x["alta"], x["baixa"], x["nome"]) for x in pares], [
            ("estilo-22-H-e8.safetensors", "estilo-22-L-e8.safetensors", "estilo-22-e8"),
            ("Wan22_Estilo_HighNoise.safetensors", "Wan22_Estilo_LowNoise.safetensors", "Wan22_Estilo"),
            ("wan_2.2_i2v_zoom_high_v2.0.safetensors", "wan_2.2_i2v_zoom_low_v2.0.safetensors", "wan_2.2_i2v_zoom_v2.0")])
        # A aceleracao (lightx2v), a LoRA sem a outra metade e as do H3 ficam de fora

    def test_grafo_poe_cada_metade_no_seu_modelo(self):
        p = dict(Grafo.P, modelo="wan22", loras=[("a_high.safetensors", "a_low.safetensors", 0.8), ("b_H.safetensors", "b_L.safetensors", 0.5)])
        g = grafo(p, "foto.png", 1, "x")
        # Depois da aceleracao (11 e 21) e antes do shift (12 e 22)
        self.assertEqual((g["130"]["inputs"]["model"], g["130"]["inputs"]["lora_name"], g["130"]["inputs"]["strength_model"]), (["11", 0], "a_high.safetensors", 0.8))
        self.assertEqual((g["131"]["inputs"]["model"], g["131"]["inputs"]["lora_name"]), (["130", 0], "b_H.safetensors"))
        self.assertEqual((g["230"]["inputs"]["model"], g["230"]["inputs"]["lora_name"]), (["21", 0], "a_low.safetensors"))
        self.assertEqual((g["231"]["inputs"]["lora_name"], g["231"]["inputs"]["strength_model"]), ("b_L.safetensors", 0.5))
        self.assertEqual((g["12"]["inputs"]["model"], g["22"]["inputs"]["model"]), (["131", 0], ["231", 0]))
        # No modelo da comunidade, com a aceleracao embutida, a LoRA sai direto do carregador
        g = grafo(dict(p, modelo="comunidade"), "foto.png", 1, "x")
        self.assertEqual((g["130"]["inputs"]["model"], g["230"]["inputs"]["model"]), (["10", 0], ["20", 0]))

    def test_grafo_da_tomada_acha_a_metade_low(self):
        import imagem_para_video as ipv, loras
        with mock.patch.object(loras, "mapa", lambda: {n.lower(): n for n in self.LISTA}):
            g = ipv.grafo_wan({"modelo": "comunidade", "proporcao": "2:3 (Portrait Photo)", "megapixels": 0.475, "loras": [["estilo-22-H-e8.safetensors", 0.7]]},
                              TomadasDoWan.TOMADA, "f.png", "x", 1)
        self.assertEqual((g["130"]["inputs"]["lora_name"], g["230"]["inputs"]["lora_name"], g["230"]["inputs"]["strength_model"]),
                         ("estilo-22-H-e8.safetensors", "estilo-22-L-e8.safetensors", 0.7))

    @mock.patch.object(validacao, "arquivos_que_faltam", instalado)
    def test_validacao_aceita_so_os_pares(self):
        import loras
        opcoes = {"modelos": [], "loras_estilo": ["feltStopMotionStyle_H3_v01.safetensors"], "loras_wan": loras.pares_wan(self.LISTA)}
        base = TomadasDoWan().ajustes
        with mock.patch.object(validacao.ambiente, "ler_opcoes", lambda: opcoes):
            r = validacao.validar_imagem(base(loras=[["estilo-22-H-e8.safetensors", "0.6"]]))
            self.assertEqual(r["loras"], [["estilo-22-H-e8.safetensors", 0.6]])
            # A metade LOW, a LoRA do H3 e a aceleracao nao valem no Wan
            for errada in ("estilo-22-L-e8.safetensors", "feltStopMotionStyle_H3_v01.safetensors", "wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors"):
                with self.assertRaises(validacao.Erro):
                    validacao.validar_imagem(base(loras=[[errada, 1]]))
            with self.assertRaises(validacao.Erro):
                validacao.validar_imagem(base(loras=[["estilo-22-H-e8.safetensors", 2]]))


if __name__ == "__main__":
    unittest.main()
