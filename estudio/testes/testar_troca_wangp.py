"""Testes das contas e das regras da troca pelo Viggle (troca_wangp.py; o motor "wangp" antigo vale como "viggle").
Nao usam o ComfyUI nem a placa.

Uso: python -I testar_troca_wangp.py
"""
import json, sys, tempfile, types, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import config, validacao
import troca_wangp as tw
from testar_troca import P


class Contas(unittest.TestCase):
    def test_quadros_no_formato_do_viggle(self):
        # 5 s = 120 quadros: o Viggle gera 124 (17n+5) e o estudio corta em 120
        self.assertEqual(tw.quadros_render(120, 124), 124)
        # Abaixo de 90 o Viggle nao gera: sobe para 90, que ja e 17n+5
        self.assertEqual(tw.quadros_render(24, 200), 90)
        # O video nao tem 141 quadros: fica no maior que cabe
        self.assertEqual(tw.quadros_render(130, 135), 124)
        # Nem 90 cabem
        self.assertIsNone(tw.quadros_render(24, 80))
        # Teto de uma janela: 345 quadros
        self.assertEqual(tw.quadros_render(400, 500), 345)
        for n in (90, 124, 345):
            self.assertEqual(n % 17, 5)

    def test_quadros_pintados(self):
        # Os testes de 17/11 pintaram os quadros 0 e 108 de 124
        self.assertEqual(tw.posicoes(124), [0, 108])
        self.assertEqual(len(tw.posicoes(10 * 24)), 3)
        self.assertEqual(len(tw.posicoes(14 * 24)), 4)
        self.assertEqual(tw.posicoes(24)[0], 0)

    def test_tamanho_igual_ao_do_imagem_para_video(self):
        self.assertEqual(tw.tamanho("16:9 (Widescreen)", 0.5), (960, 544))
        self.assertEqual(tw.tamanho("9:16 (Vertical)", 0.5), (544, 960))

    def test_prompt_tem_as_seis_secoes_e_os_quadros(self):
        texto = tw.prompt_viggle([0, 108], "video")
        secoes = [s.split(":")[0] for s in texto.split("\n\n")]
        self.assertEqual(secoes, ["subject_definitions", "summary", "retention_analysis", "detailed_description", "overall_soundscape", "non_diegetic_music"])
        self.assertIn("<Picture 1> and <Picture 2>", texto)
        self.assertIn("00:04.500", texto)
        # O WanGP avisa: "dim" escurece o video todo
        self.assertNotIn(" dim", texto.lower())
        self.assertIn("same clothes", texto)
        self.assertIn("whole outfit", tw.prompt_viggle([0, 50, 100], "foto"))


class IniciarTrocaWangp(unittest.TestCase):
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
        self.raiz, self.lancados, self.video = raiz, [], {"quadros": 240, "duracao": 10.0, "audio": True}
        for alvo, nome, valor in ((config, "PROJETOS", raiz / "projetos"), (config, "ENVIOS", raiz / "envios"), (config, "ENTRADA", raiz / "entrada"),
                                  (acoes, "exigir_comfy_livre", lambda: None), (acoes, "examinar_video", lambda v: self.video),
                                  (acoes, "validar_troca", lambda a: {**P, "upscale": False, "roupa": "video", **a}),
                                  (tarefa, "tarefa", types.SimpleNamespace(rodando=lambda: False, iniciar_troca=self.lancados.append, projeto=None))):
            m = mock.patch.object(alvo, nome, valor)
            m.start()
            self.addCleanup(m.stop)

    def iniciar(self, nome, duracao, **extra):
        self.acoes.acao_iniciar_troca({"projeto": nome, "video": "v.mp4", "foto": "f.png", "duracao": duracao, "autorizacao": True, "ajustes": {"megapixels": 0.5, "motor": "wangp"}, **extra})

    def test_ate_14_s_e_grava_o_motor(self):
        self.iniciar("a", 5)
        cfg = json.loads((self.raiz / "projetos" / "a" / validacao.PARAMETROS).read_text(encoding="utf-8"))
        self.assertEqual(cfg["motor"], "wangp")
        with self.assertRaises(validacao.Erro):
            self.iniciar("b", 14.5)
        self.assertEqual(self.lancados, ["a"])

    def test_precisa_de_90_quadros_no_video(self):
        # 1 s pedido, mas o Viggle gera 90 quadros: um video de 80 quadros nao serve
        self.video = {"quadros": 80, "duracao": 80 / 24, "audio": True}
        with self.assertRaises(validacao.Erro):
            self.iniciar("a", 1)
        self.video = {"quadros": 96, "duracao": 4.0, "audio": True}
        self.iniciar("b", 1)
        self.assertEqual(self.lancados, ["b"])

    def test_recusa_marca_e_aceita_fundo(self):
        with self.assertRaises(validacao.Erro) as e:
            self.iniciar("a", 3, marca={"x": 0.5, "y": 0.5})
        self.assertIn("Viggle Remake", e.exception.mensagem)
        self.assertEqual(self.lancados, [])
        # O fundo novo vai com o Viggle desde 22/11/2026 (troca_wangp.trocar)
        self.iniciar("b", 3, fundo="f.png")
        cfg = json.loads((self.raiz / "projetos" / "b" / validacao.PARAMETROS).read_text(encoding="utf-8"))
        self.assertEqual(cfg["fundo"], "f.png")
        self.assertEqual(self.lancados, ["b"])

    def test_fotos_de_expressao_vao_para_o_projeto(self):
        for nome in ("e1.png", "e2.png", "e3.png", "e4.png"):
            (self.raiz / "entrada" / nome).write_bytes(b"x")
        self.iniciar("a", 3, expressoes=["e1.png", "e2.png", "e1.png", "e3.png", "e4.png"])
        cfg = json.loads((self.raiz / "projetos" / "a" / validacao.PARAMETROS).read_text(encoding="utf-8"))
        # Sem repetir e no maximo MAX_EXPRESSOES
        self.assertEqual(cfg["expressoes"], ["e1.png", "e2.png", "e3.png"])
        with self.assertRaises(validacao.Erro):
            self.iniciar("b", 3, expressoes=["nao_existe.png"])


class Validar(unittest.TestCase):
    def setUp(self):
        opcoes = {"modelos": [P["modelo"]], "samplers": ["euler"], "agendadores": ["beta", "simple"], "upscalers": [P["upscaler"]],
                  "loras_troca": {"troca": [P["troca"][0]], "turbo": [P["turbo"][0]], "nitidez": [P["nitidez"][0]]}, "loras": [], "loras_estilo": []}
        for alvo, nome, valor in ((validacao.ambiente, "ler_opcoes", lambda: opcoes), (validacao, "validar_loras_video", lambda r, x: None)):
            m = mock.patch.object(alvo, nome, valor)
            m.start()
            self.addCleanup(m.stop)

    def test_motor_padrao_e_desconhecido(self):
        self.assertEqual(validacao.validar_troca({"esrgan": False})["motor"], "estudio")
        with self.assertRaises(validacao.Erro):
            validacao.validar_troca({"motor": "outro", "esrgan": False})



if __name__ == "__main__":
    unittest.main()
