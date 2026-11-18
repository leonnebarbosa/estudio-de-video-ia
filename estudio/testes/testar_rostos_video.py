"""Testes da extração de rostos de um vídeo (rostos_video.py). Usam um detector falso no lugar do YuNet e um MP4 sintético.

Uso: python -I testar_rostos_video.py
"""
import json, os, shutil, sys, tempfile, time, unittest
from pathlib import Path
from unittest import mock

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config, rostos_video


def linha_yunet(x, y, w, h, giro, conf=0.9):
    """Uma linha no formato do YuNet: caixa, olho direito, olho esquerdo, nariz, cantos da boca, confiança."""
    oy, d = y + h * 0.35, w * 0.4  # abertura 0,4: passa no limite da frente (> 0,35)
    olho_d, olho_e = (x + w / 2 - d / 2, oy), (x + w / 2 + d / 2, oy)
    nariz = (x + w / 2 + giro * d, y + h * 0.55)
    return np.array([[x, y, w, h, *olho_d, *olho_e, *nariz, x + w * 0.4, y + h * 0.75, x + w * 0.6, y + h * 0.75, conf]], np.float32)


class DetectorFalso:
    def __init__(self, faces):
        self.faces = faces  # None ou a linha devolvida em todo quadro

    def setInputSize(self, tamanho):
        pass

    def detect(self, img):
        return (1, self.faces)


class DetectorComTamanho(DetectorFalso):
    """Guarda o tamanho pedido e quantas vezes detectou; devolve várias faces (coordenadas da imagem que recebeu)."""
    def __init__(self, faces):
        super().__init__(None if faces is None else np.array(faces, np.float32))
        self.tamanho, self.chamadas = None, 0

    def setInputSize(self, tamanho):
        self.tamanho = tamanho

    def detect(self, img):
        self.chamadas += 1
        return (1, self.faces)


class ComEnvios(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.raiz = Path(d.name)
        (self.raiz / "envios").mkdir()
        m = mock.patch.object(config, "ENVIOS", self.raiz / "envios")
        m.start()
        self.addCleanup(m.stop)

    def video(self, segundos=3):
        caminho = config.ENVIOS / "v.mp4"
        w = cv2.VideoWriter(str(caminho), cv2.VideoWriter_fourcc(*"mp4v"), 24, (320, 240))
        rng = np.random.default_rng(1)
        for _ in range(24 * segundos):
            w.write(rng.integers(0, 200, (240, 320, 3), dtype=np.uint8))
        w.release()
        return caminho


class Regras(unittest.TestCase):
    def test_classificar(self):
        base = {"conf": 0.9, "caixa": [0, 0, 200, 200], "legenda": 0, "giro": 0.05, "abertura": 0.4}
        c = rostos_video.classificar
        self.assertEqual(c(base), "frente")
        self.assertEqual(c({**base, "giro": -0.3}), "tres_quartos")
        self.assertEqual(c({**base, "giro": 0.7}), "perfil")
        self.assertIsNone(c({**base, "giro": 0.2, "abertura": 0.3}))
        self.assertIsNone(c({**base, "conf": 0.7}))
        self.assertIsNone(c({**base, "caixa": [0, 0, 100, 200]}))
        self.assertIsNone(c({**base, "legenda": 0.004}))

    def test_mascara_legenda(self):
        quadros = []
        for i in range(10):
            q = np.zeros((100, 100), np.uint8)
            q[10:20, 10:60] = 255
            q[80, i * 5] = 255
            quadros.append(q)
        m = rostos_video.mascara_legenda(quadros)
        self.assertEqual(m.shape, (100, 100))
        self.assertEqual(m[15, 30], 1)
        self.assertEqual(m[80, 90], 0)

    def test_escolher_respeita_distancia_e_limite(self):
        linhas = [{"t": i * 0.25, "conf": 0.9, "caixa": [0, 0, 300, 300], "legenda": 0, "giro": 0.7, "abertura": 0.3, "nitidez": 10 + i} for i in range(20)]
        r = rostos_video.escolher(linhas)
        self.assertEqual(set(r), {"frente", "tres_quartos", "perfil"})
        p = r["perfil"]
        self.assertLessEqual(len(p), 6)
        self.assertTrue(all(abs(a["t"] - b["t"]) >= 1.0 for i, a in enumerate(p) for b in p[i + 1:]))
        self.assertEqual(p[0]["t"], 19 * 0.25)
        self.assertEqual(r["frente"], [])


class Extracao(ComEnvios):
    def test_extrair_grava_recortes_e_json(self):
        video = self.video()
        pasta = rostos_video.pasta_do_video(video)
        self.assertEqual(pasta, config.ENVIOS / "rostos_v")
        r = rostos_video.extrair(video, pasta, det=DetectorFalso(linha_yunet(80, 40, 150, 150, 0.7)))
        self.assertTrue(r["perfil"])
        self.assertEqual(r["frente"], [])
        self.assertFalse(r["legenda"])
        self.assertTrue((pasta / "perfil_0.png").is_file())
        self.assertEqual(json.loads((pasta / "candidatos.json").read_text(encoding="utf-8")), r)

    def test_extrair_frente_guarda_o_quadro(self):
        video = self.video()
        r = rostos_video.extrair(video, rostos_video.pasta_do_video(video), det=DetectorFalso(linha_yunet(80, 40, 150, 150, 0.0)))
        self.assertTrue(r["frente"])
        self.assertEqual(r["frente"][0]["quadro"], "frente_0_quadro.png")
        self.assertTrue((config.ENVIOS / "rostos_v" / "frente_0_quadro.png").is_file())

    def test_video_sem_rosto(self):
        video = self.video()
        r = rostos_video.extrair(video, rostos_video.pasta_do_video(video), det=DetectorFalso(None))
        self.assertEqual((r["frente"], r["tres_quartos"], r["perfil"]), ([], [], []))

    def test_caminho_candidato_recusa_forjado(self):
        (config.ENVIOS / "rostos_a").mkdir()
        (config.ENVIOS / "rostos_a" / "perfil_0.png").write_bytes(b"x")
        for pasta, arquivo in (("../x", "perfil_0.png"), ("rostos_a", "..\\perfil_0.png"), ("rostos_a", "perfil_0.exe"), ("outra", "perfil_0.png"), ("rostos_a", "perfil_1.png")):
            with self.assertRaises(ValueError, msg=(pasta, arquivo)):
                rostos_video.caminho_candidato(pasta, arquivo)
        self.assertEqual(rostos_video.caminho_candidato("rostos_a", "perfil_0.png"), config.ENVIOS / "rostos_a" / "perfil_0.png")

    def test_limpar_antigas_so_apaga_rostos_velhos(self):
        velho = time.time() - 2 * 86400
        for nome in ("rostos_velho", "rostos_novo", "outra"):
            (config.ENVIOS / nome).mkdir()
            (config.ENVIOS / nome / "a.png").write_bytes(b"x")
        for nome in ("rostos_velho", "outra"):
            os.utime(config.ENVIOS / nome, (velho, velho))
        rostos_video.limpar_antigas()
        self.assertEqual(sorted(p.name for p in config.ENVIOS.iterdir()), ["outra", "rostos_novo"])

    def test_maior_rosto_ignora_deteccao_fraca_e_reduz_a_imagem(self):
        # Revisão de 18/11: num recorte real, uma detecção falsa um pouco maior (conf 0,67) venceu o rosto (0,85)
        det = DetectorComTamanho([linha_yunet(10, 10, 200, 200, -0.4, conf=0.67)[0], linha_yunet(300, 60, 150, 150, 0.5, conf=0.9)[0]])
        f = rostos_video.maior_rosto(det, np.zeros((1080, 1920, 3), np.uint8))
        self.assertLessEqual(max(det.tamanho), 640)
        self.assertAlmostEqual(float(f[14]), 0.9, places=4)
        self.assertAlmostEqual(float(f[0]), 300 * 3, delta=1)   # caixa de volta ao tamanho do quadro (1920 / 640 = 3)
        self.assertIsNone(rostos_video.maior_rosto(DetectorComTamanho([linha_yunet(10, 10, 200, 200, 0.0, conf=0.6)[0]]), np.zeros((480, 640, 3), np.uint8)))

    def test_olha_para_direita_usa_o_rosto_mais_confiante(self):
        img = np.zeros((480, 640, 3), np.uint8)
        det = DetectorComTamanho([linha_yunet(10, 10, 300, 300, -0.5, conf=0.8)[0], linha_yunet(350, 60, 150, 150, 0.5, conf=0.95)[0]])
        self.assertTrue(rostos_video.olha_para_direita(img, det))
        self.assertIsNone(rostos_video.olha_para_direita(img, DetectorComTamanho([linha_yunet(10, 10, 300, 300, 0.5, conf=0.6)[0]])))

    def test_extrair_limita_os_quadros_lidos(self):
        # Vídeo longo (podcast de 10 min) não pode prender o processador por minutos: o passo cresce
        video, det = self.video(), DetectorComTamanho(None)
        rostos_video.extrair(video, rostos_video.pasta_do_video(video), det=det, max_quadros=5)
        self.assertLessEqual(det.chamadas, 6)

    def test_extrair_recusa_o_mesmo_video_ao_mesmo_tempo(self):
        video = self.video()
        pasta = rostos_video.pasta_do_video(video)
        rostos_video._extraindo.add(str(pasta))
        self.addCleanup(rostos_video._extraindo.discard, str(pasta))
        with self.assertRaises(rostos_video.Ocupado):
            rostos_video.extrair(video, pasta, det=DetectorFalso(None))

    def test_extrair_em_pasta_com_acento(self):
        # Num PC novo instalado numa pasta de usuário com acento, o cv2 não lê nem grava (revisão de 18/11)
        video = self.video()
        acento = self.raiz / "envios ção"
        acento.mkdir()
        shutil.move(str(video), str(acento / "v.mp4"))
        with mock.patch.object(config, "ENVIOS", acento):
            r = rostos_video.extrair(acento / "v.mp4", rostos_video.pasta_do_video(acento / "v.mp4"), det=DetectorFalso(linha_yunet(80, 40, 150, 150, 0.7)))
            self.assertTrue(r["perfil"])
            self.assertTrue((acento / "rostos_v" / "perfil_0.png").is_file())
            self.assertGreater((acento / "rostos_v" / "perfil_0.png").stat().st_size, 0)

    def test_video_cortado_no_meio_nao_quebra(self):
        video = self.video()
        dados = video.read_bytes()
        video.write_bytes(dados[:len(dados) // 2])
        try:
            rostos_video.extrair(video, rostos_video.pasta_do_video(video), det=DetectorFalso(linha_yunet(80, 40, 150, 150, 0.7)))
        except ValueError:
            pass   # "não abriu" também serve; o que não pode é estourar outro erro (500 na página)

    def test_nome_com_dois_pontos_seguidos(self):
        (config.ENVIOS / "rostos_a..b").mkdir()
        (config.ENVIOS / "rostos_a..b" / "perfil_0.png").write_bytes(b"x")
        self.assertEqual(rostos_video.caminho_candidato("rostos_a..b", "perfil_0.png"), config.ENVIOS / "rostos_a..b" / "perfil_0.png")

    def test_pasta_de_uma_foto_usada(self):
        self.assertEqual(rostos_video.pasta_da_foto("rostos_meu_video_perfil_2.png"), "rostos_meu_video")
        self.assertEqual(rostos_video.pasta_da_foto("rostos_v_frente_0_quadro.png"), "rostos_v")
        self.assertIsNone(rostos_video.pasta_da_foto("foto.png"))

    def test_olha_para_direita(self):
        img = np.zeros((240, 320, 3), np.uint8)
        self.assertTrue(rostos_video.olha_para_direita(img, DetectorFalso(linha_yunet(80, 40, 150, 150, 0.5))))
        self.assertFalse(rostos_video.olha_para_direita(img, DetectorFalso(linha_yunet(80, 40, 150, 150, -0.5))))
        self.assertIsNone(rostos_video.olha_para_direita(img, DetectorFalso(None)))


if __name__ == "__main__":
    unittest.main()
