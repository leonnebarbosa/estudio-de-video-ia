"""Testes da aba Imagem para video. Nao usam o ComfyUI nem a placa.

Uso: python -I testar_imagem.py
"""
import io, json, re, sys, tempfile, types, unittest
from unittest import mock
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import comunidade  # noqa: F401 (poe os modelos falsos da comunidade)
import config
import acoes, envio, projetos, tarefa, validacao
from continuar_video import quadros_por_duracao
from imagem_para_video import (CAMERAS, DURACAO_MAX_SEGUINTES, DURACOES, PELE_LORAS, PELE_MODELO, PELE_TEXTO, TURBO_REF2V, Progresso,duracao_maxima, duracoes_permitidas, SOBREPOSICAO, cor_do_fundo, ganhos_volume, grafo_continuacao, grafo_pele, grafo_primeira, intervalos, limpar, loras_estilo, prompt_continuacao, prompt_primeira, prompt_texto, quadros_novos, tamanho, total_quadros, trecho_de_fala)

P = {"proporcao": "3:2 (Photo)", "megapixels": 0.4746, "semente": 42, "quem": "the purple furry mascot", "voz": "playful, natural cartoon voice"}
T = {"acao": "A sheet of paper lands on its hand", "fala": "Conta de internet agora? Nada disso!", "som": "", "camera": "parada", "olhar": False, "duracao": 3}


class Quadros(unittest.TestCase):
    def test_duracoes_validadas(self):
        # Ate 5 s desde 07/11; 6, 7, 8 e 10 s (tomadas longas) desde 11/11/2026. 10 s = 243 quadros, o take medido
        self.assertEqual([total_quadros(d) for d in DURACOES], [73, 90, 107, 124, 141, 175, 192, 243])

    def test_duracao_cai_na_grade_do_modelo(self):
        for d in DURACOES:
            self.assertEqual((total_quadros(d) - 5) % 17, 0)

    def test_quadros_novos_descontam_a_sobreposicao(self):
        self.assertEqual(quadros_novos(3, True), 73)
        self.assertEqual(quadros_novos(3, False), 68)
        self.assertEqual(quadros_novos(5, False), 119)

    def test_o_fluxo_de_continuacao_mantem_o_mesmo_numero(self):
        for d in DURACOES:
            self.assertEqual(quadros_por_duracao(total_quadros(d) / 24), total_quadros(d))

    def test_tamanho_testado(self):
        self.assertEqual(tamanho("3:2 (Photo)", 0.4746), (864, 576))

    def test_os_15_segundos_aprovados(self):
        novos = [quadros_novos(3, True), quadros_novos(4.25, False), quadros_novos(5, False), quadros_novos(3, False)]
        self.assertEqual(sum(novos), 73 + 102 + 119 + 68)


class DuracaoPorResolucao(unittest.TestCase):
    """Limites medidos em 21/11/2026 (carga ate ~245 quadros x MP): 10 s ate 1 MP; 8 s a 1,1 e 1,2 MP."""

    def test_maximo_da_tomada_1(self):
        for mp in (0.3, 0.4746, 0.6, 0.7, 0.8, "0.8", 1.0, 1):
            self.assertEqual(duracao_maxima(mp), 10, mp)
        self.assertEqual(duracao_maxima(1.1), 8)
        self.assertEqual(duracao_maxima(1.2), 8)

    def test_tomadas_seguintes_ate_5_s(self):
        self.assertEqual(DURACAO_MAX_SEGUINTES, 5)
        for mp in (0.4746, 0.8, 1.0):
            self.assertEqual(duracao_maxima(mp, primeira=False), 5)

    def test_listas_permitidas(self):
        self.assertEqual(duracoes_permitidas(0.4746), list(DURACOES))
        self.assertEqual(duracoes_permitidas(1.2), [3, 3.5, 4.25, 5, 6, 7, 8])
        self.assertEqual(duracoes_permitidas(0.8, primeira=False), [3, 3.5, 4.25, 5])

    def test_validacao_aceita_10_s_ate_0_8_mp(self):
        for mp in (0.4746, 0.8):
            r = validacao.validar_imagem({"megapixels": mp, "tomadas": [{**T, "duracao": 10}]})
            self.assertEqual(r["tomadas"][0]["duracao"], 10)
        self.assertEqual(validacao.validar_imagem({"tomadas": [{**T, "duracao": 7}]})["tomadas"][0]["duracao"], 7)

    def test_validacao_recusa_mais_de_8_s_acima_de_1_mp(self):
        for d in (7, 10):
            validacao.validar_imagem({"megapixels": 1.0, "tomadas": [{**T, "duracao": d}]})
        validacao.validar_imagem({"megapixels": 1.2, "tomadas": [{**T, "duracao": 8}]})
        with self.assertRaises(validacao.Erro) as e:
            validacao.validar_imagem({"megapixels": 1.2, "tomadas": [{**T, "duracao": 10}]})
        self.assertIn("a 1,2 MP", e.exception.mensagem)
        self.assertIn("RAM", e.exception.mensagem)

    def test_validacao_recusa_tomada_seguinte_longa(self):
        validacao.validar_imagem({"tomadas": [{**T, "duracao": 10}, {**T, "duracao": 5}]})
        with self.assertRaises(validacao.Erro) as e:
            validacao.validar_imagem({"tomadas": [dict(T), {**T, "duracao": 6}]})
        self.assertIn("Tomada 2", e.exception.mensagem)
        self.assertIn("só valem na tomada 1", e.exception.mensagem)

    def test_wan_nao_ganha_as_duracoes_longas(self):
        with mock.patch.object(validacao, "arquivos_que_faltam", lambda k: []):
            with self.assertRaises(validacao.Erro):
                validacao.validar_imagem({"modelo": "comunidade", "megapixels": 0.475, "tomadas": [{**T, "duracao": 10}]})

    def test_pagina_recebe_os_limites(self):
        h3 = validacao.modelos_imagem()[0]
        self.assertEqual(h3["duracoes"], list(DURACOES))
        self.assertEqual(h3["duracao_max_por_mp"], [[1.0, 10], [1.2, 8]])
        self.assertEqual(h3["duracao_max_seguintes"], 5)
        json.dumps(h3)


class Prompts(unittest.TestCase):
    def test_primeira_segue_o_guia_oficial(self):
        t = prompt_primeira(P, T)
        self.assertIn("<Picture 1> (from [Shot 1]) is fully referenced", t)
        self.assertIn("(S1) says: <d>[Brazilian Portuguese] Conta de internet agora? Nada disso!</d>", t)
        self.assertIn("integrated_multimodal_description: [Shot 1] The purple furry mascot", t)
        self.assertTrue(t.endswith("non_diegetic_music: N/A"))

    def test_sotaque_brasileiro_na_voz(self):
        # Com so [Portuguese] o H3 trocou o "p" de "roupa" por "b" (teste ap7_idioma, 11/11/2026)
        t = prompt_primeira(P, T)
        self.assertIn(", with a natural Brazilian Portuguese accent (S1) says:", t)
        self.assertIn("with a natural Brazilian Portuguese accent, the character (S1) says:", prompt_continuacao(P, T, False))
        # Quem ja escreveu o sotaque na voz nao ganha outro
        t = prompt_primeira({**P, "voz": "warm Brazilian voice"}, T)
        self.assertIn("The warm Brazilian voice (S1) says:", t)
        self.assertEqual(t.count("Brazilian"), 2)

    def test_nao_prende_o_personagem_no_lugar(self):
        self.assertNotIn("stays in place", prompt_primeira(P, T))
        self.assertIn("where the character is at the start of this shot are the ones in <Picture 2>", prompt_continuacao(P, T, True))

    def test_camera_que_acompanha_libera_o_cenario(self):
        t = {**T, "camera": "acompanhar"}
        self.assertNotIn("place stays the same", prompt_primeira(P, t))
        self.assertIn("background keeps sliding past", prompt_primeira(P, t))
        c = prompt_continuacao(P, t, True)
        self.assertNotIn("Keep the same place", c)
        self.assertNotIn("Locked-off", c)
        self.assertIn("background keeps sliding past", c)
        self.assertIn("place stays the same", prompt_primeira(P, T))
        self.assertIn("Keep the same place", prompt_continuacao(P, T, True))

    def test_sem_fala_nao_ha_marca_de_fala(self):
        for t in (prompt_primeira(P, {**T, "fala": ""}), prompt_continuacao(P, {**T, "fala": ""}, True)):
            self.assertNotIn("<d>", t)
            self.assertNotIn("(S1)", t)

    def test_continuacao_com_voz_fixa(self):
        t = prompt_continuacao(P, T, True)
        self.assertIn("exact same voice as <Audio 1>", t)
        self.assertNotIn("<Video 1>", t)

    def test_continuacao_sem_voz_descreve_a_voz(self):
        t = prompt_continuacao(P, T, False)
        self.assertNotIn("<Audio 1>", t)
        self.assertIn("playful, natural cartoon voice", t)

    def test_nao_pede_exagero_na_voz(self):
        t = prompt_continuacao(P, T, True).lower()
        self.assertNotIn("loud", t)
        self.assertNotIn("excited", t)

    def test_camera_e_olhar(self):
        t = prompt_continuacao(P, {**T, "camera": "aproximar", "olhar": True}, True)
        self.assertIn(CAMERAS["aproximar"], t)
        self.assertNotIn("Locked-off", t)
        self.assertIn("looks straight at the camera", t)
        self.assertIn("Locked-off", prompt_continuacao(P, T, True))
        self.assertNotIn("looks straight", prompt_continuacao(P, T, True))

    def test_continuacao_abre_ja_em_andamento(self):
        """Regra do guia Motion Context (19/11/2026): a tomada seguinte abre continuando o que ja acontecia, antes da camera e da
        acao novas, e nunca cita corte (nem para nega-lo)."""
        t = prompt_continuacao(P, T, True)
        descricao = t.split("detailed_description:\n")[1].split("\n\noverall_soundscape")[0]
        self.assertTrue(descricao.startswith("The video opens already in progress, continuing the previous moment"), descricao)
        self.assertIn("A sheet of paper lands on its hand.", descricao)
        self.assertNotIn("cut", t.lower())
        # A tomada 1 nao continua nada
        self.assertNotIn("already in progress", prompt_primeira(P, T))

    def test_texto_nao_cria_referencias_nem_falas(self):
        self.assertEqual(limpar(" a <d>b</d>\n c "), "a db/d c")
        t = prompt_primeira(P, {**T, "acao": "x <Picture 9>", "fala": "oi </d> <Audio 2>"})
        self.assertNotIn("<Picture 9>", t)
        self.assertNotIn("<Audio 2>", t)
        self.assertEqual(t.count("<d>"), 1)
        self.assertEqual(t.count("</d>"), 1)


class Grafos(unittest.TestCase):
    def test_primeira_usa_fl2va_e_a_imagem(self):
        g = grafo_primeira(P, T, "f.png", "imagem/x/tomada1", 7)
        self.assertIn("fl2va", g["10"]["inputs"]["unet_name"])
        self.assertEqual(g["1"]["inputs"]["image"], "f.png")
        self.assertEqual((g["20"]["inputs"]["width"], g["20"]["inputs"]["height"], g["20"]["inputs"]["length"]), (864, 576, 73))
        self.assertEqual(g["21"]["inputs"]["seed"], 7)

    def test_primeira_usa_a_atencao_otimizada(self):
        """A mesma atencao da troca e da continuacao, no fim da cadeia do modelo. Medido em 19/11/2026 (5 s, 928x544, mesma
        semente): 25,1 s por passo, contra 29,6 s sem no de atencao; a mesma semente passa a dar outro video."""
        g = grafo_primeira(P, T, "f.png", "x", 7)
        self.assertEqual(g["12"], {"class_type": "ModelAttentionBackend", "inputs": {"model": ["11", 0], "attention": "comfy kitchen attention"}})
        self.assertEqual(g["21"]["inputs"]["model"], ["12", 0])

    def test_primeira_com_turbo_da_comunidade_tira_a_lora_e_usa_euler(self):
        turbo = "comunidade_h3_ref2va_v2_pruned_turbo_int8.safetensors"
        g = grafo_primeira({**P, "primeira": turbo, "loras": [["felt.safetensors", 0.8]]}, T, "f.png", "x", 7)
        self.assertEqual(g["10"]["inputs"]["unet_name"], turbo)
        self.assertNotIn("11", g)
        self.assertEqual(g["30"]["inputs"]["model"], ["10", 0])
        self.assertEqual(g["12"]["inputs"]["model"], ["30", 0])
        self.assertEqual(g["21"]["inputs"]["model"], ["12", 0])
        self.assertEqual((g["21"]["inputs"]["steps"], g["21"]["inputs"]["sampler_name"], g["21"]["inputs"]["scheduler"]), (8, "euler", "simple"))
        self.assertEqual(g["20"]["inputs"]["first_frame"], ["2", 0])

    def test_primeira_com_base_da_comunidade_mantem_a_lora(self):
        base = "comunidade_h3_ref2va_v2_pruned_int8.safetensors"
        g = grafo_primeira({**P, "primeira": base}, T, "f.png", "x", 7)
        self.assertEqual(g["10"]["inputs"]["unet_name"], base)
        self.assertEqual(g["12"]["inputs"]["model"], ["11", 0])
        self.assertEqual(g["21"]["inputs"]["sampler_name"], "res_multistep")
        self.assertEqual(grafo_primeira({**P, "primeira": None}, T, "f.png", "x", 7), grafo_primeira(P, T, "f.png", "x", 7))

    def test_primeira_ref2va_da_comunidade_usa_a_lora_turbo_do_ref2v(self):
        """Um ref2va (Singularity, teste de 20/11/2026) leva a LoRA turbo de 8 passos da mesma familia, nao a do fl2v."""
        g = grafo_primeira({**P, "primeira": "Minimax-h3_Singularity_ref2va_v2_pruned_int8.safetensors"}, T, "f.png", "x", 7)
        self.assertEqual(g["11"]["inputs"]["lora_name"], TURBO_REF2V)
        self.assertIn("fl2v", grafo_primeira(P, T, "f.png", "x", 7)["11"]["inputs"]["lora_name"])

    def test_primeira_da_comunidade_tambem_no_texto_para_video(self):
        singularity = "Minimax-h3_Singularity_ref2va_v2_pruned_int8.safetensors"
        g = grafo_primeira({**P, "primeira": singularity, "cena": "a city sidewalk"}, T, None, "x", 7)
        self.assertEqual(g["10"]["inputs"]["unet_name"], singularity)
        self.assertEqual(g["11"]["inputs"]["lora_name"], TURBO_REF2V)
        self.assertNotIn("first_frame", g["20"]["inputs"])

    def test_primeira_sem_imagem_e_texto_para_video(self):
        """Fluxo oficial video_minimax_h3_t2v (testado em 10/11/2026): o mesmo no, sem first_frame nem LoadImage."""
        p = {**P, "cena": "realistic live-action, a bright modern living room"}
        g = grafo_primeira(p, T, None, "imagem/x/tomada1", 7)
        self.assertNotIn("1", g)
        self.assertNotIn("2", g)
        self.assertNotIn("first_frame", g["20"]["inputs"])
        self.assertIn("fl2va", g["10"]["inputs"]["unet_name"])
        self.assertEqual((g["12"]["inputs"]["model"], g["21"]["inputs"]["model"]), (["11", 0], ["12", 0]))
        prompt = g["20"]["inputs"]["prompt"]
        self.assertNotIn("<Picture", prompt)
        self.assertIn("Realistic live-action, a bright modern living room.", prompt)
        self.assertIn("The main character is the purple furry mascot.", prompt)
        self.assertIn("<d>[Brazilian Portuguese] Conta de internet agora? Nada disso!</d>", prompt)

    def test_prompt_de_texto_sem_quem_nem_fala(self):
        t = prompt_texto({**P, "quem": validacao.QUEM_PADRAO, "cena": "an aerial drone shot <Picture 2>"}, {**T, "fala": ""})
        self.assertTrue(t.startswith("integrated_multimodal_description: [Shot 1] An aerial drone shot Picture 2."))
        self.assertNotIn("main character", t)
        self.assertNotIn("<d>", t)
        self.assertNotIn("<Picture", t)

    def base(self, voz, **t):
        return grafo_continuacao(P, {**T, **t}, "v.mp4", 1.04, ["f.png", "r.png"], voz, "imagem/x/tomada2", 42, 2)

    def test_continuacao_usa_sobreposicao_curta(self):
        g = self.base("voz.wav", duracao=4.25)
        self.assertEqual(g["297"]["inputs"]["value"], SOBREPOSICAO)
        self.assertAlmostEqual(g["22:23"]["inputs"]["value"] * 24, 107)
        self.assertIn("ref2va", g["171:4"]["inputs"]["unet_name"])

    def test_voz_entra_como_audio(self):
        m = json.loads(self.base("voz.wav")["416"]["inputs"]["media_state"])
        self.assertEqual([x["kind"] for x in m], ["picture", "picture", "video", "audio"])
        self.assertEqual(m[-1]["file"], "voz.wav")
        self.assertEqual(m[2]["trim"], {"start": 1.04})

    def test_referencias_extras_entram_antes_do_ultimo_quadro(self):
        p = {**P, "referencias": ["a.png", "b.png", "c.png", "d.png"]}
        g = grafo_continuacao(p, T, "v.mp4", 1.0, ["a.png", "b.png", "c.png", "d.png", "r.png"], "voz.wav", "x", 42, 2)
        m = json.loads(g["416"]["inputs"]["media_state"])
        self.assertEqual([x["file"] for x in m if x["kind"] == "picture"], ["a.png", "b.png", "c.png", "d.png", "r.png"])
        self.assertEqual(g["5"]["inputs"]["ref_image_size"], "match")
        t = g["365"]["inputs"]["prompt"]
        self.assertIn("<Picture 1>, <Picture 2>, <Picture 3>, <Picture 4>", t)
        self.assertIn("at the start of this shot are the ones in <Picture 5>", t)
        self.assertIn("from every angle", t)

    def test_sem_extras_mantem_o_que_foi_validado(self):
        g = grafo_continuacao(P, T, "v.mp4", 1.0, ["f.png", "r.png"], "voz.wav", "x", 42, 2)
        self.assertEqual(g["5"]["inputs"]["ref_image_size"], "max")
        t = g["365"]["inputs"]["prompt"]
        self.assertIn("<Subject 1> is the purple furry mascot in <Picture 1>.", t)
        self.assertIn("ones in <Picture 2>", t)

    def test_seguintes_turbo_tira_a_lora_e_usa_8_passos(self):
        turbo = "comunidade_h3_ref2va_v2_pruned_turbo_int8.safetensors"
        g = grafo_continuacao({**P, "seguintes": turbo}, T, "v.mp4", 1.0, ["f.png", "r.png"], None, "x", 42, 2)
        self.assertEqual(g["171:4"]["inputs"]["unet_name"], turbo)
        self.assertEqual(json.loads(g["554"]["inputs"]["LoraLoaderState"])["loras"], [])
        self.assertEqual((g["22:8"]["inputs"]["value"], g["22:6"]["inputs"]["sampler_name"], g["22:7"]["inputs"]["scheduler"]), (8, "euler", "simple"))

    def test_seguintes_base_mantem_a_lora_e_os_passos(self):
        base = "comunidade_h3_ref2va_v2_pruned_int8.safetensors"
        padrao = self.base(None)
        g = grafo_continuacao({**P, "seguintes": base}, T, "v.mp4", 1.04, ["f.png", "r.png"], None, "imagem/x/tomada2", 42, 2)
        self.assertEqual(g["171:4"]["inputs"]["unet_name"], base)
        for no in ("554", "22:8", "22:6", "22:7"):
            self.assertEqual(g[no]["inputs"], padrao[no]["inputs"], no)
        # Sem escolha, fica o ref2va oficial do grafo
        self.assertEqual(padrao["171:4"]["inputs"]["unet_name"], "minimax_h3_ref2va_pruned_int8_convrot.safetensors")

    def test_loras_de_estilo_nas_duas_cadeias(self):
        p = {**P, "loras": [["felt.safetensors", 0.8], ["outro.safetensors", 0.6]]}
        g = grafo_primeira(p, T, "f.png", "x", 7)
        # Tomada 1: depois da aceleracao, em cadeia, e o amostrador usa a ultima
        self.assertEqual((g["30"]["inputs"]["model"], g["30"]["inputs"]["lora_name"], g["31"]["inputs"]["model"], g["12"]["inputs"]["model"], g["21"]["inputs"]["model"]),
                         (["11", 0], "felt.safetensors", ["30", 0], ["31", 0], ["12", 0]))
        self.assertNotIn("30", grafo_primeira(P, T, "f.png", "x", 7))
        # Seguintes: somam-se a LoRA de aceleracao do fluxo
        nomes = [(x["name"], x["sm"]) for x in json.loads(grafo_continuacao(p, T, "v.mp4", 1.0, ["f.png", "r.png"], None, "x", 42, 2)["554"]["inputs"]["LoraLoaderState"])["loras"]]
        self.assertEqual(nomes, [("minimax_h3_DMAD_4step_full_lora_avg_rank_39_bf16.safetensors", 1), ("felt.safetensors", 0.8), ("outro.safetensors", 0.6)])
        # Num modelo Turbo, que vem sem a aceleracao, ficam sozinhas
        turbo = {**p, "seguintes": "comunidade_h3_ref2va_v2_pruned_turbo_int8.safetensors"}
        so = json.loads(grafo_continuacao(turbo, T, "v.mp4", 1.0, ["f.png", "r.png"], None, "x", 42, 2)["554"]["inputs"]["LoraLoaderState"])["loras"]
        self.assertEqual([x["name"] for x in so], ["felt.safetensors", "outro.safetensors"])

    def test_sem_voz_ou_sem_fala_nao_entra_audio(self):
        for g in (self.base(None), self.base("voz.wav", fala="")):
            self.assertNotIn("audio", [x["kind"] for x in json.loads(g["416"]["inputs"]["media_state"])])


class PeleNatural(unittest.TestCase):
    """A receita de pele testada em 20/11/2026 (testes_troca/pele_2026-11-20, versao C)."""
    EMA, PEOPLE = PELE_LORAS[0][0], PELE_LORAS[1][0]

    def test_loras_da_receita_vem_antes_das_escolhidas(self):
        escolhidas = [["felt.safetensors", 0.6], [self.PEOPLE, 1.0]]
        self.assertEqual(loras_estilo({"loras": escolhidas}), escolhidas)
        # A Realism People escolhida a mao da lugar a da receita (0,8); as outras seguem depois
        self.assertEqual(loras_estilo({"loras": escolhidas, "pele": True}), [[self.EMA, 1.0], [self.PEOPLE, 0.8], ["felt.safetensors", 0.6]])

    def test_tomada_1_usa_a_foto_como_referencia_e_a_receita(self):
        g = grafo_pele({**P, "pele": True}, T, "f.png", "imagem/x/tomada1", 7)
        self.assertEqual(g["10"]["inputs"]["unet_name"], PELE_MODELO)
        self.assertEqual((g["20"]["class_type"], g["20"]["inputs"]["ref_images.ref_image_0"], g["1"]["inputs"]["image"]), ("MiniMaxH3ReferenceToVideo", ["1", 0], "f.png"))
        self.assertNotIn("first_frame", g["20"]["inputs"])
        k = g["21"]["inputs"]
        self.assertEqual((k["steps"], k["sampler_name"], k["scheduler"], k["seed"]), (8, "euler", "beta", 7))
        self.assertEqual((g["11"]["class_type"], g["11"]["inputs"]["shift_video"], g["11"]["inputs"]["shift_audio"]), ("MiniMaxH3SigmaShift", 12.0, 3.0))
        # Em cadeia: desvio de sigma, EMA-600, Realism People, atencao, amostrador
        self.assertEqual([(g[n]["inputs"]["lora_name"], g[n]["inputs"]["strength_model"], g[n]["inputs"]["model"]) for n in ("30", "31")],
                         [(self.EMA, 1.0, ["11", 0]), (self.PEOPLE, 0.8, ["30", 0])])
        self.assertEqual((g["12"]["inputs"]["model"], k["model"]), (["31", 0], ["12", 0]))
        self.assertEqual(g["26"]["inputs"]["filename_prefix"], "imagem/x/tomada1")

    def test_prompt_da_tomada_1(self):
        prompt = grafo_pele({**P, "pele": True}, T, "f.png", "x", 7)["20"]["inputs"]["prompt"]
        # A palavra-chave da Realism People numa linha so, como na receita
        self.assertTrue(prompt.startswith("r34l1sm\n\n"))
        self.assertIn(PELE_TEXTO, prompt)
        self.assertIn("<d>[Brazilian Portuguese] Conta de internet agora? Nada disso!</d>", prompt)
        self.assertIn("<Subject 1> is the purple furry mascot from <Picture 1>", prompt)
        # O enquadramento da foto: sem ele o rosto encheu a tela no primeiro teste pelo estudio
        self.assertIn("a medium close-up from the chest up, <Subject 1>'s whole head and hair in frame", prompt)
        self.assertIn("a 3-second widescreen 3:2 medium close-up of <Subject 1>", prompt)
        # Nada que prenda o quadro ao recorte da foto: com isso quatro sementes sairam em close fechado
        self.assertNotIn("same distance", prompt)
        self.assertNotIn("stay the ones in <Picture 1>", prompt)
        self.assertIn("The camera stays completely steady.", prompt)
        # Palavras que trazem o efeito que citam: nunca no prompt
        for proibida in ("glow", "dewy", "flawless", "plastic", "freckles"):
            self.assertNotIn(proibida, prompt.lower())

    def test_formato_no_resumo(self):
        from imagem_para_video import formato
        self.assertEqual([formato(x) for x in ("9:16 (Portrait Widescreen)", "16:9 (Widescreen)", "1:1 (Square)")], ["vertical 9:16", "widescreen 16:9", "square 1:1"])

    def test_lugar_atras_da_pessoa(self):
        """O lugar foi o que abriu o quadro (teste_pele_lugar1, 21/11): entra no resumo e na descricao; vazio, um comodo generico."""
        from imagem_para_video import PELE_LUGAR_PADRAO
        prompt = lambda p: grafo_pele({**P, "pele": True, **p}, T, "f.png", "x", 7)["20"]["inputs"]["prompt"]
        com = prompt({"cena": "a bright bedroom, white wall and a wooden door behind her"})
        self.assertEqual(com.count("Setting: A bright bedroom, white wall and a wooden door behind her."), 2)
        self.assertEqual(prompt({}).count(f"Setting: {PELE_LUGAR_PADRAO}"), 2)
        self.assertEqual(prompt({"cena": "  "}), prompt({}))
        # Os sinais de referencia nao vem de quem escreve
        self.assertNotIn("<Picture 3>", prompt({"cena": "a room <Picture 3>"}))

    def test_tomadas_seguintes_com_a_receita(self):
        p = {**P, "pele": True, "seguintes": "comunidade_h3_ref2va_v2_pruned_turbo_int8.safetensors"}
        g = grafo_continuacao(p, T, "v.mp4", 1.0, ["f.png", "r.png"], "voz.wav", "x", 42, 2)
        # O modelo da receita vale sobre o escolhido; a LoRA de aceleracao do fluxo sai, porque a EMA-600 ja acelera
        self.assertEqual(g["171:4"]["inputs"]["unet_name"], PELE_MODELO)
        self.assertEqual([(x["name"], x["sm"]) for x in json.loads(g["554"]["inputs"]["LoraLoaderState"])["loras"]], [(self.EMA, 1.0), (self.PEOPLE, 0.8)])
        self.assertEqual((g["22:8"]["inputs"]["value"], g["22:6"]["inputs"]["sampler_name"], g["22:7"]["inputs"]["scheduler"]), (8, "euler", "beta"))
        self.assertEqual((g["560"]["class_type"], g["560"]["inputs"]["model"], g["196"]["inputs"]["model"]), ("MiniMaxH3SigmaShift", ["171:4", 0], ["560", 0]))
        prompt = g["365"]["inputs"]["prompt"]
        self.assertTrue(prompt.startswith("r34l1sm "))
        self.assertIn(PELE_TEXTO, prompt)
        self.assertIn("visible pores for the whole video", prompt)

    def test_sem_pele_nada_muda(self):
        base = grafo_continuacao(P, T, "v.mp4", 1.0, ["f.png", "r.png"], None, "x", 42, 2)
        self.assertEqual(grafo_continuacao({**P, "pele": False}, T, "v.mp4", 1.0, ["f.png", "r.png"], None, "x", 42, 2), base)
        self.assertNotIn("560", base)
        self.assertNotIn(PELE_TEXTO, prompt_continuacao(P, T, False))

    def test_validacao(self):
        ok = lambda **a: validacao.validar_imagem({"tomadas": [dict(T)], **a})
        with mock.patch.object(validacao, "faltam_pele", lambda: []):
            self.assertIs(ok()["pele"], False)
            self.assertIs(ok(pele=True)["pele"], True)
            self.assertIs(ok(pele="sim")["pele"], False)
            # No Wan nao vale
            with mock.patch.object(validacao, "arquivos_que_faltam", lambda k: []):
                self.assertIs(ok(modelo="comunidade", megapixels=0.475, pele=True)["pele"], False)
        with mock.patch.object(validacao, "faltam_pele", lambda: [PELE_MODELO]):
            self.assertIs(ok()["pele"], False)
            with self.assertRaises(validacao.Erro):
                ok(pele=True)
        # A pagina recebe o que falta
        with mock.patch.object(validacao, "faltam_pele", lambda: ["x.safetensors"]):
            self.assertEqual(validacao.modelos_imagem()[0]["pele_faltam"], ["x.safetensors"])


class Audio(unittest.TestCase):
    def test_ganhos_igualam_a_fala_baixa(self):
        g = ganhos_volume([0.235, 0.151, 0.225, 0.213])
        self.assertGreater(g[1], 1.3)
        self.assertLess(abs(g[2] - 1), 0.1)

    def test_ganhos_tem_limite(self):
        self.assertEqual(ganhos_volume([0.5, 0.01, 0.5])[1], 2.0)

    def test_tomada_muda_fica_de_fora(self):
        self.assertEqual(ganhos_volume([0.2, 0.0, 0.1])[1], 1.0)

    def test_uma_fala_so_nao_muda(self):
        self.assertEqual(ganhos_volume([0.2, 0.0]), [1.0, 1.0])

    def test_intervalos_seguem_o_juntar(self):
        r = [{"pular": 0, "total": 73, "sobreposicao": 5}, {"pular": 43, "total": 150, "sobreposicao": 5}]
        self.assertEqual(intervalos(r), [(0.0, 68 / 24), (68 / 24, 175 / 24)])

    def test_trecho_de_fala(self):
        pcm = np.zeros(16000 * 5, dtype=np.float32)
        pcm[16000:48000] = 0.2
        a, b = trecho_de_fala(pcm)
        self.assertAlmostEqual(a, 0.95, places=2)
        self.assertAlmostEqual(b, 3.05, places=2)

    def test_trecho_ignora_a_tomada_anterior(self):
        pcm = np.zeros(16000 * 5, dtype=np.float32)
        pcm[:16000] = 0.2
        pcm[48000:72000] = 0.2
        self.assertGreaterEqual(trecho_de_fala(pcm, 2.0)[0], 2.0)

    def test_fala_curta_ganha_o_minimo(self):
        pcm = np.zeros(16000 * 5, dtype=np.float32)
        pcm[16000:20000] = 0.2
        a, b = trecho_de_fala(pcm)
        self.assertGreaterEqual(b - a, 2.0)

    def test_sem_som(self):
        self.assertIsNone(trecho_de_fala(np.zeros(16000, dtype=np.float32)))


class ProgressoTeste(unittest.TestCase):
    def test_passos_das_duas_cadeias(self):
        with tempfile.TemporaryDirectory() as d:
            arq = Path(d) / "progresso.json"
            mon = types.SimpleNamespace(rotulo="")
            p = Progresso(arq, 4, mon)
            p.tomada(2)
            self.assertEqual(mon.rotulo, "tomada 2")
            p.evento({"type": "progress_state", "data": {"nodes": {"125:12": {"state": "running", "value": 3, "max": 6}}}})
            dados = json.loads(arq.read_text(encoding="utf-8"))
            self.assertEqual((dados["tomada"], dados["total"], dados["valor"], dados["maximo"]), (2, 4, 3, 6))
            p.evento({"type": "crystools.monitor", "data": {}})
            p.montando()
            self.assertEqual(json.loads(arq.read_text(encoding="utf-8"))["etapa"], "montar")


class Validacao(unittest.TestCase):
    def ok(self, **a):
        return validacao.validar_imagem({"tomadas": [dict(T)], **a})

    def recusa(self, **a):
        with self.assertRaises(validacao.Erro):
            self.ok(**a)

    def test_padrao_aceito(self):
        r = self.ok()
        self.assertEqual((r["proporcao"], r["megapixels"]), ("3:2 (Photo)", 0.4746))
        self.assertEqual(r["tomadas"][0]["duracao"], 3)
        self.assertIs(r["tomadas"][0]["olhar"], False)

    def test_modelo_das_tomadas_seguintes(self):
        turbo = "comunidade_h3_ref2va_v2_pruned_turbo_int8.safetensors"
        with mock.patch.object(validacao.ambiente, "ler_opcoes", lambda: {"modelos": ["minimax_h3_ref2va_pruned_int8_convrot.safetensors", turbo]}):
            self.assertIsNone(self.ok()["seguintes"])
            self.assertIsNone(self.ok(seguintes="")["seguintes"])
            self.assertEqual(self.ok(seguintes=turbo)["seguintes"], turbo)
            self.recusa(seguintes="nao_instalado_ref2va.safetensors")
            self.recusa(seguintes="../../models/x.safetensors")

    def test_modelo_da_tomada_1(self):
        oficial, turbo = "minimax_h3_ref2va_pruned_int8_convrot.safetensors", "comunidade_h3_ref2va_v2_pruned_turbo_int8.safetensors"
        with mock.patch.object(validacao.ambiente, "ler_opcoes", lambda: {"modelos": [oficial, turbo]}):
            self.assertIsNone(self.ok()["primeira"])
            self.assertIsNone(self.ok(primeira="")["primeira"])
            self.assertEqual(self.ok(primeira=turbo)["primeira"], turbo)
            self.recusa(primeira="nao_instalado_ref2va.safetensors")
            # O ref2va oficial nao foi testado partindo da imagem: a tomada 1 oficial e o fl2va
            self.recusa(primeira=oficial)

    def test_loras_de_estilo(self):
        felt = "feltStopMotionStyle_H3_v01.safetensors"
        with mock.patch.object(validacao.ambiente, "ler_opcoes", lambda: {"modelos": [], "loras_estilo": [felt]}):
            self.assertEqual(self.ok()["loras"], [])
            self.assertEqual(self.ok(loras=[[felt, "0.7"]])["loras"], [[felt, 0.7]])
            # Fora da lista fechada (mesmo instalada), repetida, demais ou com forca fora do limite: recusa
            self.recusa(loras=[["Estilo_MMH3-V5-ref2va.safetensors", 1]])
            self.recusa(loras=[[felt, 1], [felt, 0.5]])
            self.recusa(loras=[[felt, 1]] * 3)
            self.recusa(loras=[[felt, 0]])
            self.recusa(loras=[[felt, 2]])
            self.recusa(loras=[[felt, "x"]])
            self.recusa(loras="felt")
            # No Wan, uma LoRA do H3 e recusada: la valem so os pares HIGH/LOW (testar_wan.LorasDeEstilo)
            with mock.patch.object(validacao, "arquivos_que_faltam", lambda k: []):
                self.assertEqual(self.ok(modelo="comunidade", megapixels=0.475)["loras"], [])
                self.recusa(modelo="comunidade", megapixels=0.475, loras=[[felt, 1]])

    def test_recusa_valores_fora_da_lista(self):
        self.recusa(megapixels=2)
        self.recusa(proporcao="5:5")
        self.recusa(semente=-1)
        self.recusa(tomadas=[])
        self.recusa(tomadas="x")
        self.recusa(tomadas=[dict(T)] * (validacao.MAX_TOMADAS + 1))
        self.recusa(tomadas=[{**T, "camera": "voando"}])
        # Acao ate 2000 caracteres (eram 1000); fala e sons seguem em 300
        self.assertEqual(len(self.ok(tomadas=[{**T, "acao": "a" * 2000}])["tomadas"][0]["acao"]), 2000)
        self.recusa(tomadas=[{**T, "acao": "a" * 2001}])
        self.recusa(tomadas=[{**T, "fala": "a" * 301}])
        self.recusa(tomadas=[{**T, "som": "a" * 301}])
        self.recusa(tomadas=[{**T, "duracao": 9}])
        self.recusa(tomadas=[{**T, "acao": "", "fala": ""}])
        self.recusa(tomadas=[{**T, "fala": "x" * 400}])

    def test_referencias_extras(self):
        with tempfile.TemporaryDirectory() as d:
            antigo = config.ENTRADA
            config.ENTRADA = Path(d)
            self.addCleanup(setattr, config, "ENTRADA", antigo)
            for n in "abcde":
                (Path(d) / f"{n}.png").write_bytes(b"x")
            self.assertEqual(self.ok(referencias=["a.png", "b.png"])["referencias"], ["a.png", "b.png"])
            self.assertEqual(self.ok()["referencias"], [])
            self.recusa(referencias=["a.png", "a.png"])
            self.recusa(referencias=["nao_existe.png"])
            self.recusa(referencias=[f"{n}.png" for n in "abcde"])
            self.recusa(referencias="a.png")
            # O caminho nao sai da pasta de entrada
            self.assertEqual(self.ok(referencias=["..\\..\\a.png"])["referencias"], ["a.png"])

    def test_tomada_so_com_fala_ou_so_com_acao(self):
        self.ok(tomadas=[{**T, "acao": ""}])
        self.ok(tomadas=[{**T, "fala": ""}])

    def test_campos_desconhecidos_nao_passam(self):
        # O modelo agora e escolhido na aba (H3 ou Wan), mas so os da lista; LoRA so da lista fechada de estilos
        with mock.patch.object(validacao.ambiente, "ler_opcoes", lambda: {"modelos": [], "loras_estilo": []}), self.assertRaises(validacao.Erro):
            self.ok(loras=[["x", 1]])
        r = self.ok()
        self.assertEqual((r["modelo"], r["loras"]), ("h3", []))
        with self.assertRaises(validacao.Erro):
            self.ok(modelo="outro")
        self.assertNotIn("extra", self.ok(tomadas=[{**T, "extra": 1}])["tomadas"][0])

    def test_resolucoes_maiores(self):
        for mp in (0.7, 0.8, 1, 1.0, "1"):
            self.ok(megapixels=mp)
        self.assertEqual(tamanho("9:16 (Portrait Widescreen)", 0.7), (640, 1152))
        self.assertEqual(tamanho("9:16 (Portrait Widescreen)", 1.0), (768, 1376))
        self.recusa(megapixels=0.9)

    def test_acabamento(self):
        self.assertEqual(self.ok()["acabamento"], "nenhum")
        self.assertEqual(self.ok(acabamento="esrgan", megapixels=1.0)["acabamento"], "esrgan")
        self.assertEqual(self.ok(acabamento="refino", megapixels=0.7)["acabamento"], "refino")
        self.recusa(acabamento="refino", megapixels=0.8)
        self.recusa(acabamento="outro")

    def test_acabamento_sem_o_modelo_do_esrgan(self):
        antigo = validacao.MODELO_ESRGAN
        validacao.MODELO_ESRGAN = Path("nao_existe.pth")
        self.addCleanup(setattr, validacao, "MODELO_ESRGAN", antigo)
        self.recusa(acabamento="esrgan")
        self.ok(acabamento="nenhum")


class Envio(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        antigo = config.ENTRADA
        config.ENTRADA = Path(d.name)
        self.addCleanup(setattr, config, "ENTRADA", antigo)
        # As fotos enviadas vao para input/estudio/envios
        self.pasta = Path(d.name) / "estudio" / "envios"
        self.pasta.mkdir(parents=True)

    def png(self, cor="red"):
        b = io.BytesIO()
        Image.new("RGB", (30, 20), cor).save(b, "PNG")
        return b.getvalue()

    def enviar(self, dados, nome="a.png"):
        return envio.receber_arquivo(io.BytesIO(dados), len(dados), "foto", nome)

    def test_informa_o_tamanho_da_imagem(self):
        r = self.enviar(self.png())
        self.assertEqual((r["arquivo"], r["largura"], r["altura"]), ("a.png", 30, 20))

    def test_mesma_imagem_em_uso_nao_falha(self):
        """No Windows, gravar por cima de um arquivo aberto da erro; a miniatura da pagina pode estar lendo."""
        dados = self.png()
        self.enviar(dados)
        with (self.pasta / "a.png").open("rb"):
            r = self.enviar(dados)
        self.assertEqual(r["arquivo"], "a.png")
        self.assertEqual([p.name for p in self.pasta.iterdir()], ["a.png"])

    def test_imagem_diferente_nao_substitui(self):
        self.enviar(self.png("red"))
        self.assertEqual(self.enviar(self.png("blue"))["arquivo"], "a_2.png")
        self.assertEqual((self.pasta / "a.png").read_bytes(), self.png("red"))

    def test_arquivo_invalido_nao_deixa_sobra(self):
        with self.assertRaises(validacao.Erro):
            self.enviar(b"nao e imagem")
        self.assertEqual(list(self.pasta.iterdir()), [])

    def test_envio_interrompido_nao_deixa_sobra(self):
        with self.assertRaises(validacao.Erro):
            envio.receber_arquivo(io.BytesIO(b"abc"), 100, "foto", "a.png")
        self.assertEqual(list(self.pasta.iterdir()), [])

    def test_falha_ao_gravar_vira_mensagem(self):
        original = envio.os.replace
        def nega(*a):
            raise PermissionError(5, "Acesso negado")
        envio.os.replace = nega
        self.addCleanup(setattr, envio.os, "replace", original)
        with self.assertRaises(validacao.Erro):
            self.enviar(self.png())
        self.assertEqual(list(self.pasta.iterdir()), [])


class Refazer(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.pasta = Path(d.name) / "p"
        self.pasta.mkdir()
        self.p = {"tipo": "imagem", **P, "tomadas": [{**T, "fala": f"fala {i}"} for i in range(3)]}
        self.e = {"tipo": "imagem", "personagem": "f.png", "voz": "v.wav", "voz_tomada": 1, "tomadas": [{"n": 1}, {"n": 2}, {"n": 3}]}
        (self.pasta / "interface.json").write_text(json.dumps(self.p), encoding="utf-8")
        (self.pasta / "estado.json").write_text(json.dumps(self.e), encoding="utf-8")
        (self.pasta / "final.mp4").write_bytes(b"antes")
        self.lancados = []
        trocas = {"PROJETOS": Path(d.name), "exigir_comfy_livre": lambda: None, "tarefa": types.SimpleNamespace(rodando=lambda: False, iniciar_imagem=self.lancados.append, projeto=None)}
        for nome, valor in trocas.items():
            alvo = config if nome in ("PROJETOS", "ENTRADA", "SAIDA", "ENVIOS") else {"exigir_comfy_livre": acoes, "tarefa": tarefa}[nome]
            antigo = getattr(alvo, nome)
            setattr(alvo, nome, valor)
            self.addCleanup(setattr, alvo, nome, antigo)

    def refazer(self, desde, tomadas=None):
        tomadas = tomadas or [{**T, "fala": f"nova {i}"} for i in range(3)]
        acoes.acao_refazer_imagem({"projeto": "p", "desde": desde, "tomadas": tomadas})
        return json.loads((self.pasta / "interface.json").read_text(encoding="utf-8")), json.loads((self.pasta / "estado.json").read_text(encoding="utf-8"))

    def test_mantem_as_anteriores_e_troca_as_seguintes(self):
        p, e = self.refazer(2)
        self.assertEqual([t["fala"] for t in p["tomadas"]], ["fala 0", "nova 1", "nova 2"])
        self.assertEqual([r["n"] for r in e["tomadas"]], [1])
        self.assertEqual(e["voz"], "v.wav")
        self.assertEqual(self.lancados, ["p"])

    def test_refazer_a_tomada_da_voz_tira_a_referencia(self):
        _, e = self.refazer(1)
        self.assertEqual(e["tomadas"], [])
        self.assertNotIn("voz", e)
        self.assertNotIn("voz_tomada", e)

    def test_guarda_o_video_anterior(self):
        self.refazer(3)
        self.assertEqual((self.pasta / "final_anterior.mp4").read_bytes(), b"antes")

    def test_refazer_respeita_a_duracao_por_resolucao(self):
        # Tomada 1 pode ir a 10 s a 0,4746 MP; a tomada 2, nao
        p, _ = self.refazer(1, [{**T, "duracao": 10}, dict(T), dict(T)])
        self.assertEqual(p["tomadas"][0]["duracao"], 10)
        with self.assertRaises(validacao.Erro):
            self.refazer(2, [dict(T), {**T, "duracao": 10}, dict(T)])
        # A 1,2 MP, nem a tomada 1 passa de 8 s
        self.p["megapixels"] = 1.2
        (self.pasta / "interface.json").write_text(json.dumps(self.p), encoding="utf-8")
        with self.assertRaises(validacao.Erro):
            self.refazer(1, [{**T, "duracao": 10}, dict(T), dict(T)])

    def test_recusa_outro_numero_de_tomadas_ou_tomada_desconhecida(self):
        with self.assertRaises(validacao.Erro):
            self.refazer(1, [dict(T)])
        with self.assertRaises(validacao.Erro):
            self.refazer(4)
        self.assertEqual(self.lancados, [])


class IniciarSemImagem(unittest.TestCase):
    """Imagem opcional: sem ela, o H3 faz a tomada 1 so pelo texto."""
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.raiz = Path(d.name)
        (self.raiz / "entrada").mkdir()
        self.lancados = []
        for alvo, nome, valor in ((config, "PROJETOS", self.raiz), (config, "ENTRADA", self.raiz / "entrada"), (acoes, "exigir_comfy_livre", lambda: None),
                                  (tarefa, "tarefa", types.SimpleNamespace(rodando=lambda: False, iniciar_imagem=self.lancados.append, projeto=None))):
            antigo = getattr(alvo, nome)
            setattr(alvo, nome, valor)
            self.addCleanup(setattr, alvo, nome, antigo)

    def iniciar(self, projeto="t2v", **ajustes):
        acoes.acao_iniciar_imagem({"projeto": projeto, "foto": None, "ajustes": {"tomadas": [dict(T)], **ajustes}})
        pasta = self.raiz / projeto
        return json.loads((pasta / "interface.json").read_text(encoding="utf-8")), json.loads((pasta / "estado.json").read_text(encoding="utf-8"))

    def test_sem_imagem_nem_autorizacao_com_a_cena(self):
        p, e = self.iniciar(cena="realistic live-action, a bright living room")
        self.assertEqual((e["personagem"], e["sem_imagem"]), (None, True))
        self.assertEqual(p["cena"], "realistic live-action, a bright living room")
        self.assertNotIn("autorizado_em", p)
        self.assertEqual(self.lancados, ["t2v"])

    def test_sem_imagem_exige_a_cena(self):
        with self.assertRaises(validacao.Erro):
            self.iniciar(cena="  ")
        self.assertFalse((self.raiz / "t2v").exists())

    def test_preparar_imagem_nao_cria_nada(self):
        # A validacao roda sem criar a pasta, sem gravar e sem olhar o ComfyUI
        def ocupado():
            raise AssertionError("preparar_imagem nao pode chamar exigir_comfy_livre")
        antigo = acoes.exigir_comfy_livre
        acoes.exigir_comfy_livre = ocupado
        self.addCleanup(setattr, acoes, "exigir_comfy_livre", antigo)
        p = acoes.preparar_imagem({"projeto": "t2v", "foto": None, "ajustes": {"tomadas": [dict(T)], "cena": "a bright living room"}})
        self.assertEqual(p["parametros"]["tipo"], "imagem")
        self.assertEqual((p["projeto"], p["pasta"], p["foto"], p["pers"]), ("t2v", self.raiz / "t2v", None, None))
        self.assertFalse((self.raiz / "t2v").exists())
        with self.assertRaisesRegex(validacao.Erro, "Sem imagem, descreva a cena"):
            acoes.preparar_imagem({"projeto": "t2v", "foto": None, "ajustes": {"tomadas": [dict(T)], "cena": ""}})
        self.assertEqual(list(self.raiz.iterdir()), [self.raiz / "entrada"])

    def test_wan_exige_a_imagem(self):
        with self.assertRaises(validacao.Erro):
            self.iniciar(modelo="comunidade", megapixels=0.475, cena="a city")
        self.assertEqual(self.lancados, [])

    def test_com_imagem_nao_pede_autorizacao(self):
        # A confirmacao de autorizacao saiu em 23/11/2026 (uso pessoal, decisao do usuario)
        (self.raiz / "entrada" / "f.png").write_bytes(b"png")
        acoes.acao_iniciar_imagem({"projeto": "x", "foto": "f.png", "ajustes": {"tomadas": [dict(T)]}})
        e = json.loads((self.raiz / "x" / "estado.json").read_text(encoding="utf-8"))
        self.assertEqual((e["personagem"], e["sem_imagem"]), ("f.png", False))

    def test_usar_de_novo_nao_traz_o_quadro_como_imagem(self):
        self.iniciar(cena="a city")
        arq = self.raiz / "t2v" / "estado.json"
        e = json.loads(arq.read_text(encoding="utf-8"))
        e["personagem"] = "imagem_t2v_1_personagem.png"
        (self.raiz / "entrada" / e["personagem"]).write_bytes(b"png")
        arq.write_text(json.dumps(e), encoding="utf-8")
        r = acoes.acao_reusar({"projeto": "t2v"})
        self.assertIsNone(r["foto"])
        self.assertEqual(r["config"]["cena"], "a city")
        # A página abre o projeto na aba Texto para vídeo, e o histórico separa os dois modos
        self.assertIs(r["sem_imagem"], True)
        self.assertIs(projetos.ler_projeto(self.raiz / "t2v")["sem_imagem"], True)


class Acabar(unittest.TestCase):
    """Botao Ampliar de um projeto pronto."""
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.pasta = Path(d.name) / "p"
        self.pasta.mkdir()
        self.p = {"tipo": "imagem", **P, "tomadas": [dict(T), dict(T)]}
        self.e = {"tipo": "imagem", "personagem": "f.png", "tomadas": [{"n": 1}, {"n": 2}]}
        self.gravar()
        (self.pasta / "final.mp4").write_bytes(b"video")
        self.lancados = []
        trocas = {"PROJETOS": Path(d.name), "exigir_comfy_livre": lambda: None,
                  "tarefa": types.SimpleNamespace(rodando=lambda: False, iniciar_imagem=lambda nome, extras=(): self.lancados.append((nome, list(extras))), projeto=None)}
        for nome, valor in trocas.items():
            alvo = config if nome in ("PROJETOS", "ENTRADA", "SAIDA", "ENVIOS") else {"exigir_comfy_livre": acoes, "tarefa": tarefa}[nome]
            antigo = getattr(alvo, nome)
            setattr(alvo, nome, valor)
            self.addCleanup(setattr, alvo, nome, antigo)

    def gravar(self):
        (self.pasta / "interface.json").write_text(json.dumps(self.p), encoding="utf-8")
        (self.pasta / "estado.json").write_text(json.dumps(self.e), encoding="utf-8")

    def test_amplia_sem_gerar_de_novo(self):
        acoes.acao_acabar_imagem({"projeto": "p", "acabamento": "esrgan"})
        self.assertEqual(self.lancados, [("p", ["--so-acabar"])])
        self.assertEqual(json.loads((self.pasta / "interface.json").read_text(encoding="utf-8"))["acabamento"], "esrgan")

    def test_recusa_video_incompleto_ou_refino_acima_do_limite(self):
        self.e["tomadas"] = [{"n": 1}]
        self.gravar()
        with self.assertRaises(validacao.Erro):
            acoes.acao_acabar_imagem({"projeto": "p", "acabamento": "esrgan"})
        self.e["tomadas"] = [{"n": 1}, {"n": 2}]
        self.p["megapixels"] = 0.8
        self.gravar()
        with self.assertRaises(validacao.Erro):
            acoes.acao_acabar_imagem({"projeto": "p", "acabamento": "refino"})
        with self.assertRaises(validacao.Erro):
            acoes.acao_acabar_imagem({"projeto": "p", "acabamento": "nenhum"})
        self.assertEqual(self.lancados, [])

    def test_versao_hd_antiga_nao_aparece(self):
        import os
        hd = self.pasta / "final_hd.mp4"
        hd.write_bytes(b"hd")
        final = self.pasta / "final.mp4"
        os.utime(hd, (final.stat().st_mtime - 60,) * 2)
        self.assertIsNone(projetos.ler_imagem(self.pasta, self.e, self.p)["hd"])
        os.utime(hd, (final.stat().st_mtime + 60,) * 2)
        self.assertIsNotNone(projetos.ler_imagem(self.pasta, self.e, self.p)["hd"])

    def test_pagina_recebe_o_prompt_de_cada_tomada(self):
        e = {**self.e, "tomadas": [{"n": 1, "segundos": 200, "semente": 7, "prompt": "texto montado"}]}
        self.assertEqual(projetos.ler_imagem(self.pasta, e, self.p)["feitas"][0]["prompt"], "texto montado")


class Apagar(unittest.TestCase):
    """Tudo em pastas temporarias: nada dos projetos reais e tocado."""
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        base = Path(d.name)
        self.aqui, self.entrada, self.saida = base / "continuacao", base / "input", base / "output"
        for p in (self.aqui, self.entrada, self.saida / "imagem", self.saida / "troca"):
            p.mkdir(parents=True)
        for nome in ("barata", "barata_t1", "barata_1794152480", "outro"):
            (self.aqui / nome).mkdir()
            (self.aqui / nome / "estado.json").write_text(json.dumps({"tipo": "imagem"}), encoding="utf-8")
        (self.aqui / "barata" / "final.mp4").write_bytes(b"x" * 1000)
        (self.aqui / "outro" / "estado.json").write_text(json.dumps({"voz": "imagem_barata_1794152480_voz.wav"}), encoding="utf-8")
        (self.saida / "imagem" / "barata").mkdir()
        (self.saida / "imagem" / "barata" / "tomada1_00001.mp4").write_bytes(b"y")
        (self.saida / "imagem" / "barata_t1").mkdir()
        self.temporarios = ["imagem_barata_1794152480_t1.mp4", "imagem_barata_1794152480_ref2.png", "imagem_barata_1794152481_acab00.mp4", "troca_barata.mp4", "cont_barata_r01.png"]
        self.ficam = ["barata_cena.png", "imagem_barata_t1_1794152480_t1.mp4", "imagem_barata_1794152480_1794152499_t1.mp4", "cont_barata_r01_r02.mp4",
                      "imagem_barata_1794152480_voz.wav"]  # a voz e usada pelo projeto outro
        for f in self.temporarios + self.ficam:
            (self.entrada / f).write_bytes(b"z")
        self.rodando = False
        trocas = {"PROJETOS": self.aqui, "ENTRADA": self.entrada, "SAIDA": self.saida,
                  "tarefa": types.SimpleNamespace(rodando=lambda: self.rodando, projeto="barata")}
        for nome, valor in trocas.items():
            alvo = config if nome in ("PROJETOS", "ENTRADA", "SAIDA", "ENVIOS") else {"exigir_comfy_livre": acoes, "tarefa": tarefa}[nome]
            antigo = getattr(alvo, nome)
            setattr(alvo, nome, valor)
            self.addCleanup(setattr, alvo, nome, antigo)

    def test_sem_confirmar_so_conta(self):
        r = acoes.acao_apagar({"projeto": "barata"})
        self.assertEqual(r["arquivos"], 2 + 1 + len(self.temporarios))
        self.assertTrue((self.aqui / "barata" / "final.mp4").exists())

    def test_apaga_so_o_que_e_do_projeto(self):
        acoes.acao_apagar({"projeto": "barata", "confirmar": True})
        self.assertFalse((self.aqui / "barata").exists())
        self.assertFalse((self.saida / "imagem" / "barata").exists())
        self.assertTrue((self.saida / "imagem" / "barata_t1").exists())
        for nome in ("barata_t1", "barata_1794152480", "outro"):
            self.assertTrue((self.aqui / nome / "estado.json").exists(), nome)
        self.assertEqual(sorted(f.name for f in self.entrada.iterdir()), sorted(self.ficam))

    def test_recusa_o_que_nao_e_projeto(self):
        for nome in ("..", "../input", "barata/..", "", "nao_existe"):
            with self.assertRaises(validacao.Erro):
                acoes.acao_apagar({"projeto": nome, "confirmar": True})
        (self.aqui / "sem_estado").mkdir()
        with self.assertRaises(validacao.Erro):
            acoes.acao_apagar({"projeto": "sem_estado", "confirmar": True})
        self.assertTrue((self.aqui / "sem_estado").exists())

    def test_recusa_o_projeto_que_esta_gerando(self):
        self.rodando = True
        with self.assertRaises(validacao.Erro):
            acoes.acao_apagar({"projeto": "barata", "confirmar": True})
        self.assertTrue((self.aqui / "barata" / "final.mp4").exists())

    def test_nao_segue_atalho_para_fora(self):
        import _winapi
        fora = self.aqui.parent / "importante"
        fora.mkdir()
        (fora / "estado.json").write_text("{}", encoding="utf-8")
        (fora / "modelo.bin").write_bytes(b"m")
        _winapi.CreateJunction(str(fora), str(self.aqui / "atalho"))
        with self.assertRaises(validacao.Erro):
            acoes.acao_apagar({"projeto": "atalho", "confirmar": True})
        # Juncao na saida do ComfyUI tambem nao e seguida
        _winapi.CreateJunction(str(fora), str(self.saida / "troca" / "barata"))
        acoes.acao_apagar({"projeto": "barata", "confirmar": True})
        self.assertTrue((fora / "modelo.bin").exists())


    def test_varios_sem_confirmar_so_soma(self):
        r = acoes.acao_apagar_varios({"projetos": ["barata", "outro", "barata"]})
        self.assertEqual(r["projetos"], ["barata", "outro"])
        # barata (2 + 1 da saida + temporarios), outro (estado.json) e a voz que so o outro usava
        self.assertEqual(r["arquivos"], 2 + 1 + len(self.temporarios) + 1 + 1)
        self.assertTrue((self.aqui / "barata").exists() and (self.aqui / "outro").exists())

    def test_varios_apaga_todos_e_o_temporario_dividido(self):
        acoes.acao_apagar_varios({"projetos": ["barata", "outro"], "confirmar": True})
        self.assertFalse((self.aqui / "barata").exists())
        self.assertFalse((self.aqui / "outro").exists())
        self.assertTrue((self.aqui / "barata_t1" / "estado.json").exists())
        # A voz era usada so pelo outro, que tambem foi apagado: sai junto
        self.assertFalse((self.entrada / "imagem_barata_1794152480_voz.wav").exists())

    def test_varios_nao_apaga_nada_se_um_for_invalido(self):
        for lista in (["barata", "nao_existe"], ["barata", "../input"], [], "barata", ["barata", 3]):
            with self.assertRaises(validacao.Erro):
                acoes.acao_apagar_varios({"projetos": lista, "confirmar": True})
        self.rodando = True
        with self.assertRaises(validacao.Erro):
            acoes.acao_apagar_varios({"projetos": ["outro", "barata"], "confirmar": True})
        self.assertTrue((self.aqui / "barata" / "final.mp4").exists())
        self.assertTrue((self.aqui / "outro" / "estado.json").exists())

class Acabamento(unittest.TestCase):
    def test_tamanhos(self):
        import acabamento as ac
        self.assertEqual(ac.tamanho_hd("9:16 (Portrait Widescreen)"), (1080, 1920))
        self.assertEqual(ac.tamanho_hd("16:9 (Widescreen)"), (1920, 1080))
        self.assertEqual(ac.tamanho_hd("3:2 (Photo)"), (1620, 1080))
        # O tamanho do teste de 08/11/2026, e no maximo 1 MP para videos maiores
        self.assertEqual(ac.tamanho_refino(544, 928), (768, 1312))
        w, h = ac.tamanho_refino(640, 1152)
        self.assertLessEqual(w * h, 1.0 * 1024 * 1024 * 1.03)

    def test_pedacos_cobrem_o_video_com_mistura(self):
        import acabamento as ac
        for total in (73, 107, 209, 515):
            tam, inicios = ac.plano_refino(total)
            self.assertEqual((tam - 5) % 17, 0)
            self.assertEqual(inicios[0], 0)
            self.assertEqual(inicios[-1] + tam, total)
            for a, b in zip(inicios, inicios[1:]):
                self.assertGreaterEqual(a + tam - b, ac.MISTURA)
        tam, inicios = ac.plano_refino(60)
        self.assertEqual((tam, inicios), (56, [0, 4]))
        self.assertEqual(len(ac.plano_refino(515)[1]), 8)

    def test_mistura_sem_salto_e_com_a_cor_do_original(self):
        import acabamento as ac
        total, tam = 140, 73
        _, inicios = ac.plano_refino(total)
        original = [np.full((4, 4, 3), 100, np.uint8) for _ in range(total)]
        # Cada pedaco refinado vem 10% mais claro e com um valor proprio: a cor volta e a emenda vira rampa
        pedacos = {f"p{k}": [np.full((4, 4, 3), 110 + 0 * k, np.uint8) for _ in range(tam)] for k in range(len(inicios))}
        antigo = ac.ler
        ac.ler = lambda arq: pedacos[arq]
        self.addCleanup(setattr, ac, "ler", antigo)
        saida = list(ac.misturar(original, tam, [(ini, f"p{k}") for k, ini in enumerate(inicios)]))
        self.assertEqual(len(saida), total)
        self.assertTrue(all(abs(int(q[0, 0, 0]) - 100) <= 1 for q in saida))

    def test_mistura_gradual_na_emenda(self):
        import acabamento as ac
        total, tam = 140, 73
        _, inicios = ac.plano_refino(total)
        original = [np.full((2, 2, 3), 128, np.uint8) for _ in range(total)]
        antigo_cor = ac.igualar_cor
        ac.igualar_cor = lambda a, b: np.ones(3, np.float32)
        antigo = ac.ler
        ac.ler = lambda arq: [np.full((2, 2, 3), 50 if arq == "p0" else 200, np.uint8) for _ in range(tam)]
        self.addCleanup(setattr, ac, "ler", antigo)
        self.addCleanup(setattr, ac, "igualar_cor", antigo_cor)
        v = [int(q[0, 0, 0]) for q in ac.misturar(original, tam, [(ini, f"p{k}") for k, ini in enumerate(inicios)])]
        self.assertEqual(v[0], 50)
        self.assertEqual(v[-1], 200)
        self.assertEqual(v, sorted(v))
        # Nenhum salto maior que um quarto da diferenca de um quadro para o outro
        self.assertLess(max(b - a for a, b in zip(v, v[1:])), 150 / 4)

    def test_grafo_e_prompt_do_refino(self):
        import acabamento as ac
        t = ac.prompt_refino("the cockroach girl", {"acao": "She waves.", "fala": "Oi <b>tudo</b>"}, 3)
        self.assertIn("<Picture 1>, <Picture 2>, <Picture 3>", t)
        self.assertIn("<d>[Brazilian Portuguese] Oi btudo/b</d>", t)
        g = ac.grafo_refino("v.mp4", 73, 768, 1312, t, ["a.png", "b.png"], "x", 7)
        self.assertEqual(g["30"]["inputs"]["ref_images.ref_image_1"], ["21", 0])
        self.assertNotIn("ref_images.ref_image_2", g["30"]["inputs"])
        self.assertEqual(g["53"]["inputs"]["sigmas"], "0.6316, 0.3158, 0.0")
        self.assertEqual((g["42"]["inputs"]["mode.width"], g["42"]["inputs"]["mode.height"]), (768, 1312))
        self.assertEqual(g["40"]["inputs"]["frame_load_cap"], 73)


class CorDoFundo(unittest.TestCase):
    @staticmethod
    def quadro(altura, largura):
        """Parede clara, personagem escuro no terco esquerdo e um fio escuro no alto."""
        f = np.full((altura, largura, 3), 200, dtype=np.uint8)
        f[altura // 5:, :largura // 3] = 40
        f[:, largura // 2] = 10
        return f

    def test_video_vertical_mede_a_parede_da_faixa_de_cima(self):
        self.assertEqual(cor_do_fundo([self.quadro(928, 544)]).tolist(), [200, 200, 200])

    def test_video_horizontal_continua_medindo_o_terco_esquerdo(self):
        self.assertLess(cor_do_fundo([self.quadro(576, 864)]).mean(), 100)


class CorDaEmenda(unittest.TestCase):
    """A cor da tomada seguinte e acertada pelos mesmos instantes da anterior (os quadros de sobreposicao), nao por um canto do
    quadro. Em 19/11/2026 (projeto teste_rapidas_1911) a mulher fechou o notebook, o terco esquerdo clareou e a rampa antiga
    escureceu a tomada inteira; o arquivo corrigido ainda saia sem a marca BT.709 e mudava de cor na montagem."""
    BASE, LADO = (150, 120, 100), (120, 130, 140)

    def quadro(self, fator=1.0, lado=None):
        f = np.zeros((64, 96, 3), dtype=np.float32)
        f[:] = self.BASE
        f[:, :32] = lado or self.LADO
        return np.clip(f * fator, 0, 255).astype(np.uint8)

    def gravar(self, quadros, destino):
        import subprocess, imageio_ffmpeg
        cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "96x64", "-r", "24", "-i", "-",
               "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100", "-map", "0:v", "-map", "1:a", "-shortest",
               "-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
               "-color_range", "tv", "-c:v", "libx264", "-crf", "8", "-c:a", "aac", str(destino)]
        subprocess.run(cmd, input=b"".join(q.tobytes() for q in quadros), check=True)

    def info(self, arquivo):
        import subprocess, imageio_ffmpeg
        return subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-i", str(arquivo)], capture_output=True, text=True).stderr

    def cena(self, pasta):
        """Anterior: 10 quadros. Bruto da nova: 6 de contexto iguais, 5 de sobreposicao 10% mais escuros e 3 novos em que o
        terco esquerdo fica claro (o notebook fechou)."""
        from continuar_video import ler_quadros
        self.gravar([self.quadro()] * 10, pasta / "anterior.mp4")
        self.gravar([self.quadro()] * 6 + [self.quadro(0.9)] * 5 + [self.quadro(0.9, (255, 255, 255))] * 3, pasta / "bruto.mp4")
        return ler_quadros(pasta / "anterior.mp4"), ler_quadros(pasta / "bruto.mp4")

    def test_ganho_vem_dos_mesmos_instantes(self):
        from continuar_video import ganho_na_emenda
        claro, escuro = [self.quadro()] * 5, [self.quadro(0.9)] * 5
        self.assertAlmostEqual(ganho_na_emenda(claro, escuro), 1 / 0.9, delta=0.01)
        # Limitado, como a correcao antiga: um quadro preto nao estoura o ganho
        self.assertEqual(ganho_na_emenda(claro, [self.quadro(0.1)] * 5), 1.2)
        self.assertEqual(ganho_na_emenda([self.quadro(0.5)] * 5, claro), 0.85)

    def test_tomada_corrigida_emenda_sem_degrau_e_nao_escurece_com_a_cena(self):
        from continuar_video import ler_quadros, tem_audio
        from imagem_para_video import corrigir_tomada
        media = lambda qs: np.mean([q.reshape(-1, 3).mean(axis=0) for q in qs], axis=0)
        with tempfile.TemporaryDirectory() as d:
            pasta = Path(d)
            anterior, bruto = self.cena(pasta)
            ganho = corrigir_tomada(pasta / "bruto.mp4", bruto, 6, anterior, pasta / "saida.mp4")
            saida = ler_quadros(pasta / "saida.mp4")
            self.assertEqual(len(saida), 14)
            self.assertAlmostEqual(ganho, 1 / 0.9, delta=0.03)
            # O contexto (copia da tomada anterior) nao muda: o ganho e aplicado no proprio video, sem passar por RGB (essa
            # ida e volta custava cerca de 1 nivel de brilho a cada vez, medido em 19/11/2026)
            np.testing.assert_allclose(media(saida[:6]), media(bruto[:6]), atol=0.6)
            # Os mesmos instantes ficam com a cor da tomada anterior: a emenda nao tem degrau
            np.testing.assert_allclose(media(saida[6:11]), media(anterior[-5:]), atol=1.5)
            # A cena mudou (o terco esquerdo clareou): isso nao e desvio de cor, e a tomada nao pode escurecer
            self.assertGreater(float(saida[-1].mean()), float(bruto[-1].mean()))
            self.assertTrue(tem_audio(pasta / "saida.mp4"))

    def test_tomada_corrigida_sai_com_a_marca_bt709(self):
        from imagem_para_video import corrigir_tomada
        with tempfile.TemporaryDirectory() as d:
            pasta = Path(d)
            anterior, bruto = self.cena(pasta)
            self.assertIn("bt709", self.info(pasta / "bruto.mp4"))
            corrigir_tomada(pasta / "bruto.mp4", bruto, 6, anterior, pasta / "saida.mp4")
            self.assertIn("bt709", self.info(pasta / "saida.mp4"))

    def test_a_rampa_da_continuacao_tambem_sai_com_a_marca_bt709(self):
        """O corrigir_cor (continuacao do Seed Hunter) gravava a partir do RGB sem marca de cor: o arquivo saia BT.601 sem etiqueta
        (visto em 19/11/2026 no tomada2_v1.mp4 do projeto teste_rapidas_1911) e mudava de cor ao ser montado com os BT.709."""
        from continuar_video import corrigir_cor
        with tempfile.TemporaryDirectory() as d:
            pasta = Path(d)
            _, bruto = self.cena(pasta)
            corrigir_cor(pasta / "bruto.mp4", bruto, 6, np.array([150.0, 120.0, 100.0]), pasta / "saida.mp4")
            self.assertIn("bt709", self.info(pasta / "saida.mp4"))


class LorasDeEstilo(unittest.TestCase):
    def test_h3_da_pasta_ou_do_nome_menos_as_tecnicas(self):
        from ambiente import lora_de_estilo
        sep = "\\"
        for c in ("h3" + sep + "feltStopMotionStyle_H3_v01.safetensors", "h3/estilo_qualquer.safetensors", "Estilo_MMH3-V5-ref2va.safetensors",
                  "Minimax_H3_Cinema_V2.1.safetensors", "h3_Better_Camera_Motion_V1.safetensors"):
            self.assertTrue(lora_de_estilo(c), c)
        for c in ("h3" + sep + "minimax_h3_dmd_ref2va_8step_turbo_pruned.safetensors", "h3/minimax_h3_DMAD_4step_full_lora_avg_rank_39_bf16.safetensors",
                  "h3/minimax_h3_lms_v1.0_r64.safetensors", "h3/minimax_h3_character_swap_v1.1_ref2va_fro.safetensors", "h3/h3_character_swap_v1.5.safetensors",
                  "h3/minimax_h3_head_swap_v1.0_r32.safetensors", "h3/minimax_h3_fl2v_turbo_8step_v1.0_768p_comfyui_bf16.safetensors",
                  "zimage" + sep + "Retrato-ZIT-V7.safetensors", "wan/estilo-22-H-e8.safetensors", "chroma_instagramreality_v2.safetensors"):
            self.assertFalse(lora_de_estilo(c), c)


class ModelosDeReferencia(unittest.TestCase):
    def test_lista_os_h3_de_referencia_e_deixa_o_fl2va_de_fora(self):
        from ambiente import modelo_de_referencia
        for nome in ("minimax_h3_ref2va_pruned_int8_convrot.safetensors", "comunidade_h3_ref2va_v2_pruned_turbo_int8.safetensors",
                     "Outro_Max_h3_8stepTURBO_beta7_fix1-native_int8.safetensors"):
            self.assertTrue(modelo_de_referencia(nome), nome)
        for nome in ("minimax_h3_fl2va_pruned_int8_convrot.safetensors", "Comunidade_Wan22_I2V_14B_v1_HIGH_int8.safetensors",
                     "z_image_turbo_int8_convrot.safetensors", "Wan2.2-I2V-A14B-LowNoise-Q4_K_M.gguf"):
            self.assertFalse(modelo_de_referencia(nome), nome)


if __name__ == "__main__":
    unittest.main()
