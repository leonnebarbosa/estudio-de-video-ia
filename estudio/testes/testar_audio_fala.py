"""Testes do modo audio do Imagem para video (audio_fala.py e o que usa ele). Nao usam o ComfyUI nem a placa.

Uso: python -I testar_audio_fala.py
"""
import json, subprocess, sys, tempfile, unittest, wave
from pathlib import Path
from unittest import mock

import imageio_ffmpeg
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import comunidade  # noqa: F401 (poe os modelos falsos da comunidade)
import acoes, audio_fala, config, envio, validacao
import imagem_para_video as ipv

TAXA = 16000


def falas(blocos, taxa=TAXA):
    """Audio sintetico: [(segundos, com_voz)]. Voz = tom de 220 Hz modulado; silencio = ruido muito baixo."""
    partes, rng = [], np.random.default_rng(1)
    for s, tem in blocos:
        n = int(s * taxa)
        t = np.arange(n) / taxa
        partes.append(0.3 * np.sin(2 * np.pi * 220 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 3 * t)) if tem else 0.0005 * rng.standard_normal(n))
    return np.concatenate(partes).astype(np.float32)


def gravar_wav(caminho, pcm, taxa=TAXA):
    with wave.open(str(caminho), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(taxa)
        w.writeframes((np.clip(pcm, -1, 1) * 32767).astype(np.int16).tobytes())


class Divisao(unittest.TestCase):
    def test_audio_curto_vira_uma_tomada_que_acaba_na_voz(self):
        pcm = falas([(0.2, False), (3.0, True), (1.5, False)])
        cortes = audio_fala.dividir(pcm, 5.875)
        self.assertEqual(len(cortes), 1)
        # O silencio do fim nao entra inteiro: a tomada acaba 0,3 s depois da ultima voz
        self.assertAlmostEqual(cortes[0][1], 3.5, delta=0.05)

    def test_corta_no_meio_da_pausa_e_nunca_passa_do_maximo(self):
        # Voz 0-4,8 s, pausa de 0,4 s, voz 5,2-9 s, pausa de 0,3 s, voz ate 12 s
        pcm = falas([(4.8, True), (0.4, False), (3.8, True), (0.3, False), (2.9, True)])
        cortes = audio_fala.dividir(pcm, 5.875)
        self.assertGreaterEqual(len(cortes), 2)
        self.assertAlmostEqual(cortes[0][1], 5.0, delta=0.05)
        for a, b in cortes:
            self.assertLessEqual(b - a, 5.875 + 1e-6)
        for (_, b), (a, _) in zip(cortes, cortes[1:]):
            self.assertEqual(b, a)  # os cortes encostam: nada do audio se perde

    def test_sem_pausa_corta_no_maximo(self):
        cortes = audio_fala.dividir(falas([(8.0, True)]), 5.875)
        self.assertEqual(cortes[0], (0.0, 5.875))

    def test_onde_ha_voz_dentro_do_corte(self):
        pcm = falas([(0.5, False), (1.0, True), (0.4, False), (1.0, True), (0.5, False)])
        primeira, ultima, pausas = audio_fala.trechos_de_voz(pcm, 0.0, 3.4)
        self.assertAlmostEqual(primeira, 0.5, delta=0.03)
        self.assertAlmostEqual(ultima, 2.9, delta=0.03)
        self.assertEqual(len(pausas), 1)
        self.assertAlmostEqual(pausas[0], 1.7, delta=0.05)
        self.assertIsNone(audio_fala.trechos_de_voz(pcm, 0.0, 0.4))


class Grafo(unittest.TestCase):
    P = {"proporcao": "9:16", "megapixels": 1.0, "quem": "", "loras": [], "pele": True}
    T = {"acao": "Fala com a câmera com empolgação.", "fala": "", "som": "", "camera": "selfie", "olhar": False, "duracao": 5.31}

    def test_quadros_cobrem_o_trecho_na_grade_do_h3(self):
        self.assertEqual(ipv.quadros_para(5.31), 141)
        self.assertEqual(ipv.quadros_para(5.16), 124)  # 124 quadros = 5,1667 s; 5,17 s ja pede 141
        self.assertEqual(ipv.quadros_para(10.0), 243)
        for s in (0.5, 2.0, 4.44, 7.3):
            q = ipv.quadros_para(s)
            self.assertEqual((q - 5) % 17, 0)
            self.assertGreaterEqual(q, s * 24 - 1e-6)

    def test_o_audio_fica_preso_no_latente_com_a_receita_da_pele(self):
        g = ipv.grafo_audio(self.P, self.T, ["foto.png"], "lugar.png", "trecho.wav", 141, (0.02, 5.22, [1.41]), "x/t1", 7)
        tipos = {v["class_type"] for v in g.values()}
        self.assertIn("PixaromaH3AudioSync", tipos)
        self.assertNotIn("MiniMaxH3AddGuide", tipos)  # o AddGuide nao prende o audio (teste de 20/11)
        self.assertEqual(g["21"]["inputs"]["latent_image"], ["28", 1])
        self.assertEqual(g["10"]["inputs"]["unet_name"], ipv.PELE_MODELO)
        self.assertEqual(g["20"]["inputs"]["length"], 141)
        refs = [g[g["20"]["inputs"][f"ref_images.ref_image_{i}"][0]]["inputs"]["image"] for i in range(2)]
        self.assertEqual(refs, ["foto.png", "lugar.png"])  # <Picture 1> a imagem, <Picture 2> o lugar
        self.assertEqual(g["20"]["inputs"]["ref_image_size"], "match")
        self.assertEqual(g["3"]["inputs"]["audio"], "trecho.wav")

    def test_prompt_sem_a_fala_escrita_e_com_a_regra_da_boca(self):
        g = ipv.grafo_audio(self.P, self.T, ["foto.png"], None, "t.wav", 141, (0.02, 5.22, [1.41]), "x/t1", 7)
        prompt = g["20"]["inputs"]["prompt"]
        self.assertNotIn("<d>", prompt)
        self.assertNotIn("<Audio", prompt)
        self.assertIn("lips press fully together on every p, b and m", prompt)
        self.assertIn("from 00:00.020 to 00:05.220", prompt)
        self.assertIn("00:01.410", prompt)
        self.assertIn("Handheld selfie", prompt)
        self.assertNotIn("<Picture 2>", prompt)  # sem foto do lugar
        self.assertEqual(g["20"]["inputs"]["ref_image_size"], "max")

    def test_tomada_sem_voz_fica_de_boca_fechada(self):
        prompt = ipv.prompt_audio(self.P, self.T, None, 1, False)
        self.assertIn("does not speak", prompt)


class Validacao(unittest.TestCase):
    M = {"fala": True, "pele_faltam": []}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.entrada = Path(self.tmp.name)
        gravar_wav(self.entrada / "voz.wav", falas([(4.8, True), (0.4, False), (3.8, True), (0.3, False), (2.9, True)]))
        self.patch = mock.patch.object(config, "ENTRADA", self.entrada)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def r(self, **k):
        return {**validacao.PADRAO_IMAGEM, "proporcao": "9:16", "megapixels": 1.0, "audio": "voz.wav", **k}

    def test_as_tomadas_sao_os_cortes_do_audio(self):
        _, cortes = validacao.cortes_do_audio("voz.wav", 1.0)
        tomadas = [{"acao": "", "camera": "selfie"} for _ in cortes]
        r = validacao.validar_modo_audio(self.r(), {"tomadas": tomadas}, self.M)
        self.assertEqual(r["cortes"], cortes)
        self.assertTrue(r["pele"])
        self.assertEqual([t["duracao"] for t in r["tomadas"]], [round(b - a, 3) for a, b in cortes])
        self.assertEqual({t["fala"] for t in r["tomadas"]}, {""})

    def test_fala_escrita_fica_guardada(self):
        _, cortes = validacao.cortes_do_audio("voz.wav", 1.0)
        tomadas = [{"acao": "", "fala": "Chama no uatizápi!" if i == 0 else "", "camera": "selfie"} for i in range(len(cortes))]
        r = validacao.validar_modo_audio(self.r(), {"tomadas": tomadas}, self.M)
        self.assertEqual(r["tomadas"][0]["fala"], "Chama no uatizápi!")
        self.assertEqual(r["tomadas"][1]["fala"], "")

    def test_numero_de_tomadas_diferente_e_recusado(self):
        with self.assertRaises(validacao.Erro):
            validacao.validar_modo_audio(self.r(), {"tomadas": [{"acao": "", "camera": "selfie"}]}, self.M)

    def test_a_resolucao_muda_a_divisao(self):
        _, a1 = validacao.cortes_do_audio("voz.wav", 1.2)
        _, a8 = validacao.cortes_do_audio("voz.wav", 0.8)
        self.assertGreaterEqual(len(a1), len(a8))
        self.assertTrue(all(b - a <= 8.5 for a, b in a1))
        self.assertTrue(all(b - a <= 10 for a, b in a8))

    def test_refino_e_wan_ficam_de_fora(self):
        tomadas = [{"acao": "", "camera": "selfie"}] * 3
        with self.assertRaises(validacao.Erro):
            validacao.validar_modo_audio(self.r(acabamento="refino"), {"tomadas": tomadas}, self.M)
        with self.assertRaises(validacao.Erro):
            validacao.validar_modo_audio(self.r(), {"tomadas": tomadas}, {"fala": False, "pele_faltam": []})

    def test_foto_do_lugar_precisa_existir(self):
        _, cortes = validacao.cortes_do_audio("voz.wav", 1.0)
        tomadas = [{"acao": "", "camera": "selfie"} for _ in cortes]
        with self.assertRaises(validacao.Erro):
            validacao.validar_modo_audio(self.r(cenario="nao_existe.png"), {"tomadas": tomadas}, self.M)

    def test_rota_da_pagina_devolve_a_mesma_divisao(self):
        r = acoes.acao_audio_tomadas({"audio": "voz.wav", "megapixels": 1.0})
        _, cortes = validacao.cortes_do_audio("voz.wav", 1.0)
        self.assertEqual(r["cortes"], cortes)
        self.assertEqual(len(r["voz"]), len(cortes))
        self.assertEqual(r["maximo"], 10.0)
        json.dumps(r)  # vai para a pagina: nada de numpy


class AcimaDe1MP(unittest.TestCase):
    """Acima de 1 MP (21/11): no modo audio o maior trecho cabe em 209 quadros (8,5 s), a 1,1 e a 1,2 MP."""

    def test_trechos_maximos_na_grade(self):
        self.assertEqual(ipv.quadros_para(validacao.max_tomada_audio(1.0)), 243)
        self.assertEqual(ipv.quadros_para(validacao.max_tomada_audio(1.1)), 209)
        self.assertEqual(ipv.quadros_para(validacao.max_tomada_audio(1.2)), 209)  # 8,5 s em teste desde 20/11 (2 tomadas para a voz da Amanda)

    def test_modo_normal(self):
        self.assertEqual(ipv.duracao_maxima(1.1), 8)
        self.assertEqual(ipv.duracao_maxima(1.2), 8)
        self.assertIn(1.2, validacao.QUALIDADES_IMAGEM)


class DivisaoMinima(unittest.TestCase):
    def test_usa_o_menor_numero_de_tomadas_que_cabe_nas_pausas(self):
        # Voz ate 6,3 s, pausa, voz ate 14,6 s: com maximo de 8,5 s o guloso fazia 3 tomadas; cabem 2 (corte na pausa)
        pcm = falas([(6.3, True), (0.2, False), (3.7, True), (0.3, False), (4.3, True)])
        cortes = audio_fala.dividir(pcm, 8.5)
        self.assertEqual(len(cortes), 2)
        self.assertAlmostEqual(cortes[0][1], 6.4, delta=0.05)


class FalaEscrita(unittest.TestCase):
    """21/11: a fala escrita (como se fala) entra no prompt so para guiar a boca; na selfie, o idioma de influenciadora."""
    P = {"proporcao": "9:16", "megapixels": 1.1, "quem": "", "loras": [], "pele": True}

    def test_fala_escrita_entra_com_o_idioma(self):
        t = {"acao": "", "fala": "Chama no uatizápi!", "som": "", "camera": "selfie", "olhar": False, "duracao": 4.3}
        prompt = ipv.prompt_audio(self.P, t, (0.18, 4.04, []), 1, False)
        self.assertIn("<d>[Brazilian Portuguese, like a real Brazilian influencer talking to her followers] Chama no uatizápi!</d>", prompt)
        self.assertIn("is visibly speaking Brazilian Portuguese, like a real Brazilian influencer", prompt)
        self.assertIn("with the timing of the soundtrack", prompt)

    def test_sem_fala_nao_ha_d_e_fora_da_selfie_o_idioma_simples(self):
        t = {"acao": "", "fala": "", "som": "", "camera": "parada", "olhar": False, "duracao": 4.3}
        prompt = ipv.prompt_audio(self.P, t, (0.18, 4.04, []), 1, False)
        self.assertNotIn("<d>", prompt)
        self.assertNotIn("influencer", prompt)


class Envio(unittest.TestCase):
    def test_audio_e_examinado(self):
        with tempfile.TemporaryDirectory() as d:
            arq = Path(d) / "a.wav"
            gravar_wav(arq, falas([(1.5, True)]))
            self.assertAlmostEqual(envio.examinar_audio(arq)["duracao"], 1.5, delta=0.05)
            ruim = Path(d) / "b.wav"
            ruim.write_bytes(b"nao e audio")
            with self.assertRaises(validacao.Erro):
                envio.examinar_audio(ruim)


class Montagem(unittest.TestCase):
    def test_tomadas_aparadas_e_audio_original_por_cima(self):
        ff = imageio_ffmpeg.get_ffmpeg_exe()
        with tempfile.TemporaryDirectory() as d:
            pasta = Path(d)
            for k, segundos in ((1, 2.0), (2, 2.0)):
                subprocess.run([ff, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c=gray:s=64x96:r=24:d={segundos}",
                                "-f", "lavfi", "-i", f"sine=f=300:d={segundos}", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                                str(pasta / f"tomada{k}_v1.mp4")], check=True)
            gravar_wav(pasta / "audio_fala.wav", falas([(3.0, True)]))
            feitas = [{"arquivo": "tomada1_v1.mp4", "usar": 30}, {"arquivo": "tomada2_v1.mp4", "usar": 36}]
            ipv.juntar_audio(pasta, feitas, pasta / "audio_fala.wav")
            q = ipv.ler_quadros(pasta / "final.mp4")
            self.assertEqual(len(q), 66)
            self.assertTrue(ipv.ler_audio(pasta / "final.mp4").size > 0)


if __name__ == "__main__":
    unittest.main()
