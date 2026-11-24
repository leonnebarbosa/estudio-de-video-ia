"""Testes da receita de 22/11/2026 para refazer um reel com outra pessoa (testes_troca/reel_identico_2026-11-22): as janelas
do Viggle, o pintor Klein + BFS, a pele, as fotos de expressao, o acabamento do rosto, a medida de fidelidade, o fundo novo
com o SAM e o motor Wan Animate 2. Nao usam o ComfyUI, a placa nem o MediaPipe.

Uso: python -I testar_troca_reel.py
"""
import sys, tempfile, types, unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import config, entrada, validacao
import acabamento_rosto, fidelidade, fundo, personagens, troca_viggle, troca_wan
import troca_wangp as tw
from testar_troca import P

OK = {"status": "success", "erro": "", "pico_vram": 9000, "temp_max": 70, "segundos": 1, "saidas": {}}


class Janelas(unittest.TestCase):
    def test_ate_141_quadros_vai_numa_janela_so(self):
        # 5 s: uma janela de 124 quadros (17n+5), cortada nos 120 pedidos
        self.assertEqual(tw.plano_janelas(120, 124), [(0, 124, 120)])
        self.assertEqual(tw.plano_janelas(141, 141), [(0, 141, 141)])
        # 1 s: o Viggle gera no minimo 90
        self.assertEqual(tw.plano_janelas(24, 100), [(0, 90, 24)])
        self.assertIsNone(tw.plano_janelas(24, 80))

    def test_acima_disso_janelas_de_124_com_a_ultima_no_fim(self):
        # 10 s (o reel de 22/11): duas janelas; a segunda encosta no fim
        self.assertEqual(tw.plano_janelas(240, 240), [(0, 124, 124), (116, 124, 124)])
        plano = tw.plano_janelas(336, 400)
        self.assertEqual([i for i, _, _ in plano], [0, 119, 212])
        for (a, n, _), (b, _, _) in zip(plano, plano[1:]):
            # Cada janela repete pelo menos SOBRA quadros da anterior
            self.assertGreaterEqual(a + n - b, tw.SOBRA)
        self.assertEqual(plano[-1][0] + plano[-1][1], 336)
        # O video tem menos quadros que o pedido: o plano cobre so o que existe
        self.assertEqual(tw.plano_janelas(240, 200)[-1], (76, 124, 124))

    def test_emenda_mistura_so_os_quadros_repetidos(self):
        a = [np.full((2, 2, 3), 0, np.uint8)] * 6
        b = [np.full((2, 2, 3), 90, np.uint8)] * 6
        junto = tw.emendar([a, b], [0, 4])
        self.assertEqual(len(junto), 10)
        self.assertEqual([int(q[0, 0, 0]) for q in junto], [0, 0, 0, 0, 30, 60, 90, 90, 90, 90])
        self.assertEqual(len(tw.emendar([a], [0])), 6)


class Pele(unittest.TestCase):
    def test_pedido_com_a_pele_fosca(self):
        from imagem_para_video import PELE_RETER, PELE_TEXTO
        sem, com = tw.prompt_viggle([0, 108], "video", True), tw.prompt_viggle([0, 108], "video", True, pele=True)
        self.assertNotIn("matte", sem)
        self.assertIn(PELE_RETER, com)
        self.assertIn(PELE_TEXTO, com)
        # As seis secoes continuam, na ordem
        posicoes = [com.index(s + ":") for s in ("subject_definitions", "summary", "retention_analysis", "detailed_description", "overall_soundscape", "non_diegetic_music")]
        self.assertEqual(posicoes, sorted(posicoes))
        self.assertLess(com.index(PELE_RETER), com.index("detailed_description:"))

    def test_lora_de_pele_entra_entre_a_do_viggle_e_o_desvio(self):
        g = troca_viggle.grafo("v.mp4", [(0, "a.png")], "p", 544, 960, 124, 1, "x")
        self.assertEqual(g["13"]["inputs"]["model"], ["11", 0])
        g = troca_viggle.grafo("v.mp4", [(0, "a.png")], "p", 544, 960, 124, 1, "x", loras_extra=[("pele.safetensors", 0.8)])
        self.assertEqual(g["70"]["inputs"], {"model": ["11", 0], "lora_name": "pele.safetensors", "strength_model": 0.8})
        self.assertEqual(g["13"]["inputs"]["model"], ["70", 0])

    def test_so_usa_a_lora_de_pele_instalada(self):
        with mock.patch.object(troca_viggle.loras, "mapa", lambda: {}):
            self.assertEqual(troca_viggle.loras_de_pele(), [])
        with mock.patch.object(troca_viggle.loras, "mapa", lambda: {troca_viggle.PELE_LORA[0].lower(): "h3/x"}):
            self.assertEqual(troca_viggle.loras_de_pele(), [troca_viggle.PELE_LORA])


class PintorKlein(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.raiz = Path(d.name)
        for nome in ("entrada", "saida"):
            (self.raiz / nome).mkdir()
        for nome, valor in (("ENTRADA", self.raiz / "entrada"), ("SAIDA", self.raiz / "saida")):
            m = mock.patch.object(config, nome, valor)
            m.start()
            self.addCleanup(m.stop)

    def test_cada_quadro_com_a_sua_cabeca_e_pula_o_que_ja_existe(self):
        grafos = []

        def rodar(g, limite):
            grafos.append(g)
            (self.raiz / "saida" / "p.png").write_bytes(b"pintado")
            return {**OK, "saidas": {"9": {"images": [{"filename": "p.png", "subfolder": ""}]}}}

        for n in (0, 108):
            (self.raiz / f"q{n}.png").write_bytes(b"q")
        (self.raiz / "d108.png").write_bytes(b"ja pintado")
        feitos = []
        r = troca_viggle.pintar_klein("proj", [(0, self.raiz / "q0.png", self.raiz / "d0.png", "neutra.png"), (108, self.raiz / "q108.png", self.raiz / "d108.png", "sorriso.png")],
                                      7, rodar, feitos.append)
        self.assertEqual(r["status"], "success")
        self.assertEqual(len(grafos), 1)
        self.assertEqual((self.raiz / "d0.png").read_bytes(), b"pintado")
        self.assertEqual((self.raiz / "d108.png").read_bytes(), b"ja pintado")
        self.assertEqual(feitos, [1, 2])
        # A troca em foto do estudio: o quadro e a base, a cabeca a referencia, com a LoRA BFS
        import troca_foto
        imagens = sorted(n["inputs"]["image"] for n in grafos[0].values() if n["class_type"] == "LoadImage")
        self.assertEqual(imagens, ["estudio/temp/proj/viggle_proj_quadro_000.png", "neutra.png"])
        self.assertIn(troca_foto.LORA_ROSTO, [n["inputs"].get("lora_name") for n in grafos[0].values()])
        # O quadro copiado para a entrada some depois
        self.assertEqual([f for f in (self.raiz / "entrada").rglob("*") if f.is_file()], [])

    def test_para_no_quadro_que_falha(self):
        (self.raiz / "q0.png").write_bytes(b"q")
        r = troca_viggle.pintar_klein("proj", [(0, self.raiz / "q0.png", self.raiz / "d0.png", "c.png")], 7, lambda g, l: {**OK, "status": "error", "erro": "x"})
        self.assertEqual(r["status"], "error")
        self.assertFalse((self.raiz / "d0.png").exists())

    def test_preparar_pede_o_klein_com_a_roupa_do_video(self):
        with mock.patch.object(troca_viggle, "falta_do_klein", lambda: ["loras/klein/bfs.safetensors"]), mock.patch.object(troca_viggle, "falta_do_pintor", lambda: []):
            self.assertIn("Klein", troca_viggle.preparar("swap_klein"))


class Expressoes(unittest.TestCase):
    A = {"boca": 0.0, "sorriso": 0.6, "bico": 0.0, "piscada": 0.1, "olho_arregalado": 0.0, "sobrancelha": 0.2}
    B = {"boca": 0.1, "sorriso": 0.0, "bico": 0.1, "piscada": 0.1, "olho_arregalado": 0.0, "sobrancelha": 0.2}

    def test_distancia_pesa_boca_e_sorriso(self):
        self.assertEqual(fidelidade.distancia(self.A, self.A), 0)
        self.assertAlmostEqual(fidelidade.distancia(self.A, self.B), 2 * 0.1 + 2 * 0.6 + 0.1)
        self.assertIsNone(fidelidade.distancia(self.A, None))

    def test_escolhe_a_mais_parecida(self):
        serio = {**self.B, "sorriso": 0.05}
        self.assertEqual(fidelidade.mais_parecida(serio, {"sorrindo.png": self.A, "neutra.png": self.B}), "neutra.png")
        # Sem rosto no quadro original, ou numa das fotos, vale o que der para comparar; sem nada, a primeira
        self.assertEqual(fidelidade.mais_parecida(serio, {"sem_rosto.png": None, "sorrindo.png": self.A}), "sorrindo.png")
        self.assertEqual(fidelidade.mais_parecida(None, {"a.png": self.A, "b.png": self.B}), "a.png")

    def test_uma_foto_so_nao_mede_nada(self):
        with mock.patch.object(fidelidade, "expressao", side_effect=AssertionError("nao devia medir")):
            self.assertEqual(tw.escolher_cabecas(["q0.png", "q1.png"], ["c.png"]), ["c.png", "c.png"])

    def test_cada_quadro_leva_a_foto_da_sua_expressao(self):
        medidas = {"sorrindo.png": self.A, "neutra.png": self.B, "q_serio.png": {**self.B, "sorriso": 0.02}, "q_sorri.png": {**self.A, "sorriso": 0.5}}
        with mock.patch.object(fidelidade, "disponivel", lambda: True), mock.patch.object(fidelidade, "expressao", lambda arq: medidas[Path(arq).name]):
            self.assertEqual(tw.escolher_cabecas(["q_serio.png", "q_sorri.png"], ["sorrindo.png", "neutra.png"]), ["neutra.png", "sorrindo.png"])
        with mock.patch.object(fidelidade, "disponivel", lambda: False):
            self.assertEqual(tw.escolher_cabecas(["q_serio.png"], ["sorrindo.png", "neutra.png"]), ["sorrindo.png"])

    def test_fotos_guardadas_no_personagem(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as d:
            raiz = Path(d)
            (raiz / "pers" / "ana").mkdir(parents=True)
            (raiz / "pers" / "ana" / personagens.FICHA).write_text("{}", encoding="utf-8")
            (raiz / "entrada").mkdir()
            Image.new("RGB", (8, 8), (200, 150, 120)).save(raiz / "foto.jpg")
            with mock.patch.object(personagens, "PASTA", raiz / "pers"), mock.patch.object(config, "ENTRADA", raiz / "entrada"):
                nomes = [personagens.gravar_expressao("ana", raiz / "foto.jpg") for _ in range(personagens.MAX_EXPRESSOES)]
                self.assertEqual(nomes, ["expressao_1.png", "expressao_2.png", "expressao_3.png"])
                with self.assertRaises(ValueError):
                    personagens.gravar_expressao("ana", raiz / "foto.jpg")
                personagens.apagar_expressao("ana", "expressao_2.png")
                self.assertEqual([a.name for a in personagens.expressoes("ana")], ["expressao_1.png", "expressao_3.png"])
                # A vaga livre e reaproveitada
                self.assertEqual(personagens.gravar_expressao("ana", raiz / "foto.jpg"), "expressao_2.png")
                with self.assertRaises(ValueError):
                    personagens.apagar_expressao("ana", "..\\frente.png")
                copiadas = personagens.expressoes_para_entrada("ana")
                self.assertEqual(len(copiadas), 3)
                for nome in copiadas:
                    self.assertTrue(nome.startswith("pers_ana_") and (raiz / "entrada" / "estudio" / "envios" / nome).is_file())


class Fidelidade(unittest.TestCase):
    def test_correlacao(self):
        self.assertAlmostEqual(fidelidade.correlacao([0, 1, 2, 3], [0, 2, 4, 6]), 1.0)
        self.assertAlmostEqual(fidelidade.correlacao([0, 1, 2, 3], [3, 2, 1, 0]), -1.0)
        # Uma curva parada nao tem correlacao
        self.assertIsNone(fidelidade.correlacao([1, 1, 1, 1], [0, 1, 2, 3]))
        self.assertIsNone(fidelidade.correlacao([0, 1], [0, 1]))

    def test_relatorio_com_a_nota_das_medidas_do_resumo(self):
        base = {m: 0.0 for m in fidelidade.MEDIDAS}
        a = [{**base, "boca": k / 10, "sorriso": (k % 3) / 3, "piscada": (k % 2), "sobrancelha": k / 20} for k in range(20)]
        b = [{**l, "boca": l["boca"] * 0.5} for l in a]
        with mock.patch.object(fidelidade, "disponivel", lambda: True), mock.patch.object(fidelidade, "curvas", side_effect=[(a, 0), (b + b[:3], 1)]):
            r = fidelidade.medir_video("o.mp4", "g.mp4")
        self.assertEqual(r["quadros"], 20)
        self.assertEqual(r["medidas"]["boca"], 1.0)
        self.assertEqual(r["nota"], 1.0)
        # "bico" nao varia: fica fora
        self.assertNotIn("bico", r["medidas"])

    def test_sem_rosto_ou_sem_mediapipe_nao_mede(self):
        with mock.patch.object(fidelidade, "disponivel", lambda: False):
            self.assertIsNone(fidelidade.medir_video("o.mp4", "g.mp4"))
        vazio = [{m: 0.0 for m in fidelidade.MEDIDAS}] * 30
        with mock.patch.object(fidelidade, "disponivel", lambda: True), mock.patch.object(fidelidade, "curvas", side_effect=[(vazio, 0), (vazio, 20)]):
            self.assertIsNone(fidelidade.medir_video("o.mp4", "g.mp4"))


def _pontos_de_olhos():
    """478 pontos de rosto de mentira (0 a 1): o contorno de cada olho numa elipse e a iris no meio dela."""
    pts = [types.SimpleNamespace(x=0.0, y=0.0) for _ in range(478)]
    for (contorno, centro, borda), cx in zip(fidelidade.OLHOS, (0.3, 0.7)):
        for k, i in enumerate(contorno):
            ang = 2 * np.pi * k / len(contorno)
            pts[i] = types.SimpleNamespace(x=cx + 0.1 * np.cos(ang), y=0.4 + 0.05 * np.sin(ang))
        pts[centro] = types.SimpleNamespace(x=cx, y=0.4)
        for i, (dx, dy) in zip(borda, ((0.04, 0), (0, -0.04), (-0.04, 0), (0, 0.04))):
            pts[i] = types.SimpleNamespace(x=cx + dx, y=0.4 + dy)
    return pts


class Acabamento(unittest.TestCase):
    def test_cor_da_iris_ignora_pupila_e_reflexo(self):
        lab = np.zeros((20, 20, 3), np.float32)
        lab[..., 0], lab[..., 1], lab[..., 2] = 80, 140, 150          # a iris castanha
        lab[8:12, 8:12] = (5, 128, 128)                               # a pupila
        lab[2:4, 2:4] = (250, 128, 128)                               # o reflexo
        cor = acabamento_rosto.cor_da_iris(lab, np.ones((20, 20), np.float32))
        self.assertEqual([round(float(c)) for c in cor], [80, 140, 150])
        self.assertIsNone(acabamento_rosto.cor_da_iris(lab, np.zeros((20, 20), np.float32)))

    def test_iris_esverdeada_volta_para_a_referencia_e_so_escurece(self):
        lab = np.zeros((10, 10, 3), np.float32)
        lab[..., 0], lab[..., 1], lab[..., 2] = 120, 118, 140          # clara e esverdeada
        lab[0, 0] = (250, 128, 128)                                   # o reflexo fica como esta
        m = np.zeros((10, 10), np.float32)
        m[:5] = 1
        acabamento_rosto.pintar_iris(lab, m, np.array([120, 118, 140], np.float32), np.array([60, 136, 134], np.float32))
        self.assertEqual([round(float(c)) for c in lab[2, 2]], [60, 136, 134])
        self.assertEqual([round(float(c)) for c in lab[8, 8]], [120, 118, 140])      # fora da mascara
        self.assertEqual([round(float(c)) for c in lab[0, 0]], [250, 128, 128])
        # Uma iris mais escura que a referencia nao clareia
        escura = np.full((4, 4, 3), (30, 128, 128), np.float32)
        acabamento_rosto.pintar_iris(escura, np.ones((4, 4), np.float32), np.array([30, 128, 128], np.float32), np.array([60, 136, 134], np.float32))
        self.assertEqual(round(float(escura[1, 1, 0])), 30)

    def test_fosco_achata_so_o_reflexo_dentro_da_pele(self):
        lab = np.full((60, 60, 3), (120, 140, 145), np.float32)
        lab[28:32, 28:32, 0] = 220                                    # um reflexo na bochecha
        lab[28:32, 2:6, 0] = 220                                      # o mesmo brilho fora da pele
        m = np.zeros((60, 60), np.float32)
        m[20:40, 20:40] = 1
        acabamento_rosto.foscar(lab, m, 0.7)
        self.assertLess(lab[30, 30, 0], 170)
        self.assertEqual(lab[30, 4, 0], 220)
        self.assertAlmostEqual(float(lab[22, 22, 0]), 120, delta=3)

    def test_sem_rosto_o_tom_fica_como_a_pintura(self):
        import cv2
        with tempfile.TemporaryDirectory() as d:
            for nome, cor in (("p.png", 90), ("o.png", 160)):
                cv2.imwrite(str(Path(d) / nome), np.full((32, 32, 3), cor, np.uint8))
            with mock.patch.object(acabamento_rosto.troca_foto, "caixa_rosto", lambda img, det=None: None):
                self.assertFalse(acabamento_rosto.igualar_tom(Path(d) / "p.png", Path(d) / "o.png", Path(d) / "s.png"))
            self.assertEqual(int(cv2.imread(str(Path(d) / "s.png"))[0, 0, 0]), 90)

    def _tom(self, iris=None):
        """igualar_tom num rosto de mentira de 200x200: pele rosada com dois olhos cor de mel sobre um original de pele mais
        escura. Devolve (pintado, saida) em BGR."""
        import cv2
        pintado = np.full((200, 200, 3), (150, 160, 210), np.uint8)
        for cx in (60, 140):
            cv2.ellipse(pintado, (cx, 80), (20, 10), 0, 0, 360, (70, 110, 140), -1)
        with tempfile.TemporaryDirectory() as d:
            cv2.imwrite(str(Path(d) / "p.png"), pintado)
            cv2.imwrite(str(Path(d) / "o.png"), np.full((200, 200, 3), (110, 130, 170), np.uint8))
            with mock.patch.object(acabamento_rosto.troca_foto, "caixa_rosto", lambda img, det=None: (40, 30, 120, 140)), \
                 mock.patch.object(fidelidade, "disponivel", lambda: True), \
                 mock.patch.object(fidelidade, "detectar", lambda img: ({}, _pontos_de_olhos())):
                self.assertTrue(acabamento_rosto.igualar_tom(Path(d) / "p.png", Path(d) / "o.png", Path(d) / "s.png", iris=iris))
            return pintado, cv2.imread(str(Path(d) / "s.png"))

    def test_o_tom_da_pele_nao_mexe_nos_olhos(self):
        # 23/11/2026: o ajuste levava o olho junto com a pele, e a iris castanha saia verde-oliva com o branco azulado
        pintado, fora = self._tom()
        self.assertLess(int(fora[150, 100, 2]), 190)                    # a pele foi para o tom do original
        for ponto in ((80, 60), (80, 140), (80, 45)):                   # a iris dos dois olhos e o branco do olho
            np.testing.assert_allclose(fora[ponto].astype(int), pintado[ponto].astype(int), atol=3)

    def test_a_iris_do_quadro_pintado_vai_para_a_cor_da_foto(self):
        import cv2
        pintado, fora = self._tom(iris=np.array([40, 140, 142], np.float32))
        lab = cv2.cvtColor(fora, cv2.COLOR_BGR2LAB).astype(int)
        np.testing.assert_allclose(lab[80, 60], (40, 140, 142), atol=4)
        np.testing.assert_allclose(lab[80, 140], (40, 140, 142), atol=4)
        np.testing.assert_allclose(fora[80, 45].astype(int), pintado[80, 45].astype(int), atol=3)   # fora da iris, o olho fica

    def test_o_tom_mede_e_muda_so_a_pele(self):
        # 23/11/2026, troca com uma personagem de franja preta: a elipse do rosto pegava a franja, o contraste da pele era
        # achatado (as sardas sumiam, as sobrancelhas desbotavam) e a franja saia castanho-avermelhada no video inteiro
        import cv2
        pintado = np.full((200, 200, 3), (150, 160, 210), np.uint8)
        pintado[100:, 100:] = (130, 140, 190)                          # um lado do rosto mais escuro (o relevo da pele)
        pintado[20:50, 50:150] = (10, 10, 10)                          # a franja preta
        original = np.full((200, 200, 3), (110, 130, 170), np.uint8)
        original[100:, 100:] = (95, 112, 150)
        with tempfile.TemporaryDirectory() as d:
            cv2.imwrite(str(Path(d) / "p.png"), pintado)
            cv2.imwrite(str(Path(d) / "o.png"), original)
            with mock.patch.object(acabamento_rosto.troca_foto, "caixa_rosto", lambda img, det=None: (40, 30, 120, 140)), \
                 mock.patch.object(fidelidade, "disponivel", lambda: False):
                self.assertTrue(acabamento_rosto.igualar_tom(Path(d) / "p.png", Path(d) / "o.png", Path(d) / "s.png"))
            fora = cv2.imread(str(Path(d) / "s.png")).astype(int)
        np.testing.assert_allclose(fora[35, 100], (10, 10, 10), atol=6)                 # a franja fica preta
        self.assertLess(fora[150, 60, 2], 195)                                          # a pele foi para o tom do original
        self.assertGreater(fora[150, 60, 2] - fora[150, 140, 2], 14)                    # e guardou o relevo (eram 20)

    def test_iris_pequena_demais_nao_serve_de_referencia(self):
        # Foto de corpo inteiro: a iris tinha 190 pixels, a medida saiu saturada e os olhos do video ficaram laranja (23/11/2026)
        import cv2
        m = np.zeros((40, 40), np.float32)
        m[10:20, 10:20] = 1                                            # 100 pixels de iris
        with tempfile.TemporaryDirectory() as d:
            cv2.imwrite(str(Path(d) / "f.png"), np.full((40, 40, 3), (60, 90, 120), np.uint8))
            with mock.patch.object(fidelidade, "disponivel", lambda: True), mock.patch.object(fidelidade, "detectar", lambda img: ({}, object())), \
                 mock.patch.object(fidelidade, "mascara_iris", lambda pontos, h, w: m):
                self.assertIsNotNone(acabamento_rosto.referencia_da_iris([Path(d) / "f.png"]))
                self.assertIsNone(acabamento_rosto.referencia_da_iris([Path(d) / "f.png"], minimo=600))

    def test_iris_das_fotos_mede_cada_cabeca_uma_vez_e_nao_derruba_a_troca(self):
        vistos = []
        with mock.patch.object(acabamento_rosto, "referencia_da_iris", lambda imagens, minimo=0: vistos.extend(imagens) or ("cor", minimo)):
            self.assertEqual(tw.iris_das_fotos(["a.png", "b.png", "a.png"]), ("cor", tw.IRIS_MINIMA))
        self.assertEqual(vistos, [entrada.caminho("a.png"), entrada.caminho("b.png")])
        with mock.patch.object(acabamento_rosto, "referencia_da_iris", mock.Mock(side_effect=RuntimeError("sem modelo"))), mock.patch("builtins.print"):
            self.assertIsNone(tw.iris_das_fotos(["a.png"]))

    def test_a_iris_pode_guardar_parte_da_textura(self):
        lab = np.full((4, 4, 3), (50, 130, 130), np.float32)
        lab[0, 0] = (50, 140, 130)                                     # um ponto mais avermelhado que a media da iris
        acabamento_rosto.pintar_iris(lab, np.ones((4, 4), np.float32), np.array([50, 130, 130], np.float32), np.array([50, 138, 140], np.float32), textura=0.5)
        self.assertEqual([round(float(c)) for c in lab[1, 1]], [50, 138, 140])
        self.assertEqual([round(float(c)) for c in lab[0, 0]], [50, 143, 140])


class FundoComSam(unittest.TestCase):
    def test_grafo_pede_pessoa_mao_e_braco(self):
        g = fundo.grafo_sam("v.mp4", 10, 288, "troca/x")
        self.assertEqual([n["inputs"]["text"] for n in g.values() if n["class_type"] == "CLIPTextEncode"], list(fundo.SAM_TEXTOS))
        self.assertEqual(g["3"]["inputs"]["frame_load_cap"], 10)

    def test_sem_o_modelo_do_sam_ficam_os_alfas_do_birefnet(self):
        alfas = [np.ones((4, 4), np.float32)]
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "MODELOS", Path(d)):
            self.assertIs(fundo.so_pessoas(alfas, "v.mp4", 1, 4, 4, 4, mock.Mock(side_effect=AssertionError("nao devia rodar"))), alfas)

    def test_o_que_o_sam_nao_chama_de_pessoa_sai_do_recorte(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as d:
            raiz = Path(d)
            (raiz / "checkpoints").mkdir()
            (raiz / "checkpoints" / fundo.SAM).write_bytes(b"x")
            (raiz / "saida").mkdir()
            pessoa = np.zeros((40, 40), np.uint8)
            pessoa[:, :20] = 255                                      # a pessoa ocupa a metade esquerda
            for nome, img in (("person.png", pessoa), ("hand.png", np.zeros((40, 40), np.uint8)), ("arm.png", np.zeros((40, 40), np.uint8))):
                Image.fromarray(img).save(raiz / "saida" / nome)
            r = {**OK, "saidas": {f"6{k}": {"images": [{"filename": n, "subfolder": ""}]} for k, n in enumerate(("person.png", "hand.png", "arm.png"))}}
            with mock.patch.object(config, "MODELOS", raiz), mock.patch.object(config, "SAIDA", raiz / "saida"), mock.patch("comfy_api.posta", lambda *a, **k: None):
                # O BiRefNet marcou o quadro inteiro (a pessoa e a cama atras dela)
                saida = fundo.so_pessoas([np.ones((40, 40), np.float32)], "v.mp4", 1, 40, 40, 40, lambda g, l: r)
                self.assertGreater(saida[0][20, 5], 0.9)
                self.assertLess(saida[0][20, 36], 0.05)
                self.assertEqual(list((raiz / "saida").iterdir()), [])
                # Faltou mascara: fica como o BiRefNet deu
                alfas = [np.ones((40, 40), np.float32)] * 2
                self.assertIs(fundo.so_pessoas(alfas, "v.mp4", 2, 40, 40, 40, lambda g, l: {**OK, "saidas": {}}), alfas)


class WanAnimate(unittest.TestCase):
    def test_janelas_de_81_com_um_quadro_repetido(self):
        self.assertEqual(troca_wan.comprimentos(81), [81])
        # 5 s a 30 fps, o teste de 22/11: 81 + 72 novos (73 gerados, o primeiro repete)
        self.assertEqual(troca_wan.comprimentos(150), [81, 73])
        for total in (5, 81, 82, 120, 240, 336):
            tamanhos = troca_wan.comprimentos(total)
            self.assertGreaterEqual(tamanhos[0] + sum(n - 1 for n in tamanhos[1:]), total)
            for n in tamanhos:
                self.assertEqual(n % 4, 1)
                self.assertLessEqual(n, troca_wan.JANELA)

    def test_tamanho_com_o_lado_menor_em_480(self):
        self.assertEqual(troca_wan.tamanho(720, 1280), (480, 848))
        self.assertEqual(troca_wan.tamanho(1920, 1080), (848, 480))
        self.assertEqual(troca_wan.tamanho(1080, 1080), (480, 480))

    def test_cada_janela_continua_da_anterior(self):
        g = troca_wan.grafo("ref.png", "v.mp4", 150, 480, 848, 9, "troca/x")
        for n in g.values():
            for valor in n["inputs"].values():
                if isinstance(valor, list) and len(valor) == 2 and isinstance(valor[0], str) and isinstance(valor[1], int):
                    self.assertIn(valor[0], g, f"no {valor[0]} citado nao existe")
        self.assertNotIn("continue_motion", g["087"]["inputs"])
        self.assertEqual(g["087"]["inputs"]["video_frame_offset"], 0)
        self.assertEqual(g["187"]["inputs"]["continue_motion"], ["001", 0])
        self.assertEqual(g["187"]["inputs"]["video_frame_offset"], ["087", 5])
        self.assertEqual(g["187"]["inputs"]["length"], 73)
        # A segunda janela perde o quadro que repete o ultimo da primeira, e o video sai com o som e os quadros pedidos
        self.assertEqual(g["104"]["inputs"]["batch_index"], 1)
        self.assertEqual(g["95"]["inputs"]["length"], 150)
        self.assertEqual(g["245"]["inputs"]["audio"], ["288", 1])
        self.assertEqual(g["594"]["inputs"]["device"], "cpu")

    def test_passo_da_janela_que_esta_amostrando(self):
        aviso = lambda nos: {"type": "progress_state", "data": {"nodes": nos}}
        self.assertEqual(troca_wan.janela_do_evento(aviso({"097": {"state": "running", "value": 3, "max": 6}}), 2), (1, 3))
        self.assertEqual(troca_wan.janela_do_evento(aviso({"097": {"state": "finished", "value": 6, "max": 6}, "197": {"state": "running", "value": 1, "max": 6}}), 2), (2, 1))
        self.assertIsNone(troca_wan.janela_do_evento(aviso({"584": {"state": "running", "value": 0, "max": 1}}), 2))
        self.assertIsNone(troca_wan.janela_do_evento({"type": "status"}, 2))

    def test_lista_o_que_falta(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "MODELOS", Path(d)), mock.patch.object(troca_wan.loras, "mapa", lambda: {}):
            faltam = troca_wan.faltam()
            self.assertIn(f"diffusion_models/{troca_wan.MODELO}", faltam)
            self.assertIn(f"loras/wan/{troca_wan.LORA}", faltam)


class Cabelo(unittest.TestCase):
    def mascaras(self, fim_do_cabelo):
        rosto = np.zeros((100, 60), bool)
        rosto[20:60, 20:40] = True                                    # rosto de 40 px de altura, queixo na linha 59
        cabelo = np.zeros((100, 60), bool)
        cabelo[10:fim_do_cabelo, 10:50] = True
        return cabelo, rosto

    def test_mede_em_alturas_de_rosto_abaixo_do_queixo(self):
        import trocar_personagem as tp
        self.assertAlmostEqual(tp.cabelo_abaixo_do_queixo(*self.mascaras(100)), 1.0, delta=0.03)      # ate o peito
        self.assertAlmostEqual(tp.cabelo_abaixo_do_queixo(*self.mascaras(80)), 0.5, delta=0.03)       # no ombro
        self.assertEqual(tp.cabelo_abaixo_do_queixo(*self.mascaras(40)), 0.0)                         # curto: acaba acima do queixo
        self.assertEqual(tp.cabelo_abaixo_do_queixo(None, self.mascaras(40)[1]), 0.0)                 # careca
        self.assertIsNone(tp.cabelo_abaixo_do_queixo(self.mascaras(80)[0], None))                     # sem rosto nao ha medida

    def test_avisa_so_quando_o_comprimento_difere_muito(self):
        import trocar_personagem as tp
        with tempfile.TemporaryDirectory() as d, mock.patch.object(config, "ENTRADA", Path(d)), mock.patch.object(tp, "ffmpeg", lambda *a: None), \
                mock.patch.object(tp, "posta", lambda *a, **k: None), mock.patch.object(tp, "AVISOS", []):
            with mock.patch.object(tp, "comprimento_do_cabelo", side_effect=[1.6, 0.6]):
                tp.avisar_do_cabelo("foto.png", "v.mp4", "proj")
            self.assertEqual(len(tp.AVISOS), 1)
            self.assertIn("mais comprido", tp.AVISOS[0])
            with mock.patch.object(tp, "comprimento_do_cabelo", side_effect=[0.7, 0.6]):
                tp.avisar_do_cabelo("foto.png", "v.mp4", "proj")
            with mock.patch.object(tp, "comprimento_do_cabelo", side_effect=[None, 0.6]):
                tp.avisar_do_cabelo("foto.png", "v.mp4", "proj")
            # Uma falha na medida nunca interrompe a troca
            with mock.patch.object(tp, "comprimento_do_cabelo", side_effect=RuntimeError("SAM fora do ar")):
                tp.avisar_do_cabelo("foto.png", "v.mp4", "proj")
            self.assertEqual(len(tp.AVISOS), 1)


class RotaDeExpressao(unittest.TestCase):
    def test_guarda_apaga_e_devolve_a_lista(self):
        import acoes
        from PIL import Image
        with tempfile.TemporaryDirectory() as d:
            raiz = Path(d)
            (raiz / "pers" / "ana").mkdir(parents=True)
            (raiz / "pers" / "ana" / personagens.FICHA).write_text("{}", encoding="utf-8")
            (raiz / "entrada").mkdir()
            Image.new("RGB", (8, 8), (200, 150, 120)).save(raiz / "entrada" / "foto.png")
            (raiz / "entrada" / "nao_e_imagem.png").write_bytes(b"x")
            with mock.patch.object(personagens, "PASTA", raiz / "pers"), mock.patch.object(config, "ENTRADA", raiz / "entrada"), \
                    mock.patch.object(personagens, "ler", lambda pid: {"expressoes": [{"arquivo": a.name} for a in personagens.expressoes(pid)]}):
                r = acoes.acao_personagem_expressao({"id": "ana", "foto": "foto.png"})
                self.assertEqual(r["expressoes"], [{"arquivo": "expressao_1.png"}])
                with self.assertRaises(validacao.Erro):
                    acoes.acao_personagem_expressao({"id": "ana", "foto": "sumiu.png"})
                with self.assertRaises(validacao.Erro):
                    acoes.acao_personagem_expressao({"id": "ana", "foto": "nao_e_imagem.png"})
                with self.assertRaises(validacao.Erro):
                    acoes.acao_personagem_expressao({"id": "ninguem", "foto": "foto.png"})
                self.assertEqual(acoes.acao_personagem_expressao({"id": "ana", "apagar": "expressao_1.png"})["expressoes"], [])


class Regras(unittest.TestCase):
    def setUp(self):
        opcoes = {"modelos": [P["modelo"]], "samplers": ["euler"], "agendadores": ["beta", "simple"], "upscalers": [P["upscaler"]],
                  "loras_troca": {"troca": [P["troca"][0]], "turbo": [P["turbo"][0]], "nitidez": [P["nitidez"][0]]}, "loras": [], "loras_estilo": ["estilo.safetensors"]}
        for alvo, nome, valor in ((validacao.ambiente, "ler_opcoes", lambda: opcoes), (validacao, "validar_loras_video", lambda r, x: None)):
            m = mock.patch.object(alvo, nome, valor)
            m.start()
            self.addCleanup(m.stop)

    def test_wan_e_um_motor_com_as_regras_do_viggle(self):
        self.assertEqual(validacao.validar_troca({"esrgan": False, "motor": "wan"})["motor"], "wan")
        with self.assertRaises(validacao.Erro) as e:
            validacao.validar_troca({"esrgan": False, "motor": "wan", "upscale": True})
        self.assertIn("Wan Animate 2", e.exception.mensagem)
        with self.assertRaises(validacao.Erro):
            validacao.validar_troca({"esrgan": False, "motor": "wan", "loras": [["estilo.safetensors", 1.0]]})

    def test_acabamento_ligado_por_padrao(self):
        self.assertIs(validacao.validar_troca({"esrgan": False})["acabamento"], True)
        self.assertIs(validacao.validar_troca({"esrgan": False, "acabamento": False})["acabamento"], False)


if __name__ == "__main__":
    unittest.main()
