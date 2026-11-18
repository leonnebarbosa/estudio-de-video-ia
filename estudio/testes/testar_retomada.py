"""Retomar a geracao depois de um reinicio do PC. Usa pastas temporarias; nao usa o ComfyUI nem gera nada.

Uso: python -I testar_retomada.py
"""
import json, sys, tempfile, time, types, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config, retomada, tarefa


class Base(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.pasta = Path(d.name)
        (self.pasta / "projetos" / "p1").mkdir(parents=True)
        for nome, valor in (("LOGS", self.pasta / "logs"), ("PROJETOS", self.pasta / "projetos")):
            m = mock.patch.object(config, nome, valor)
            m.start()
            self.addCleanup(m.stop)


class Decidir(unittest.TestCase):
    D = {"cmd": ["x"], "projeto": "p", "modo": "gerar", "tipo": "imagem", "inicio": 1000, "retomada": 0, "fim": None, "codigo": None}

    def test_reiniciou_no_meio(self):
        self.assertTrue(retomada.decidir(dict(self.D), 2000, 1500, [])[0])

    def test_sem_reinicio_nao_retoma(self):
        self.assertFalse(retomada.decidir(dict(self.D), 2000, 900, [])[0])

    def test_so_uma_vez(self):
        self.assertFalse(retomada.decidir({**self.D, "retomada": 1}, 2000, 1500, [])[0])

    def test_antiga_nao_retoma(self):
        self.assertFalse(retomada.decidir(dict(self.D), 1000 + 13 * 3600, 1500, [])[0])

    def test_erro_comum_seguido_de_reinicio_nao_retoma(self):
        self.assertFalse(retomada.decidir({**self.D, "fim": 1100, "codigo": 1}, 9000, 8000, [])[0])

    def test_erro_seguido_de_reinicio_pelo_vigia_retoma(self):
        self.assertTrue(retomada.decidir({**self.D, "fim": 1100, "codigo": 1}, 2000, 1300, [1200])[0])

    def test_reinicio_do_vigia_de_outra_vez_nao_conta(self):
        self.assertFalse(retomada.decidir({**self.D, "fim": 1100, "codigo": 1}, 2000, 1300, [500])[0])

    def test_vazio(self):
        self.assertFalse(retomada.decidir(None, 2000, 1500, [])[0])


class Arquivo(Base):
    def test_terminou_bem_apaga(self):
        retomada.gravar(["a"], "p1", "gerar", "imagem", 1000)
        self.assertIsNotNone(retomada.ler())
        retomada.terminou(0, False)
        self.assertIsNone(retomada.ler())

    def test_parada_apaga(self):
        retomada.gravar(["a"], "p1", "gerar", "imagem", 1000)
        retomada.terminou(1, True)
        self.assertIsNone(retomada.ler())

    def test_erro_guarda_codigo(self):
        retomada.gravar(["a"], "p1", "gerar", "imagem", 1000)
        retomada.terminou(3, False)
        d = retomada.ler()
        self.assertEqual(d["codigo"], 3)
        self.assertIsNotNone(d["fim"])


class Tarefa(Base):
    def rodar(self, codigo):
        t = tarefa.Tarefa()
        t._lancar([sys.executable, "-c", f"import time; time.sleep(0.3); raise SystemExit({codigo})"], "p1", "gerar", "imagem")
        gravado = retomada.ler()
        t.proc.wait()
        for _ in range(50):
            if t.codigo is not None:
                break
            time.sleep(0.05)
        return t, gravado

    def test_grava_ao_comecar_e_apaga_ao_terminar_bem(self):
        t, gravado = self.rodar(0)
        self.assertEqual(gravado["projeto"], "p1")
        self.assertEqual(gravado["retomada"], 0)
        self.assertEqual(t.codigo, 0)
        self.assertIsNone(retomada.ler())

    def test_erro_fica_registrado(self):
        t, _ = self.rodar(2)
        self.assertEqual(retomada.ler()["codigo"], 2)

    def test_relancar_conta_a_vez(self):
        t = tarefa.Tarefa()
        dados = {"cmd": [sys.executable, "-c", "import time; time.sleep(0.5)"], "projeto": "p1", "modo": "gerar", "tipo": "imagem", "retomada": 0}
        t.relancar(dados)
        self.assertEqual(retomada.ler()["retomada"], 1)
        with self.assertRaises(Exception):
            t.relancar(dados)
        t.proc.wait()


class SemSegundaPassagem(Base):
    """Uma troca que caiu volta sem a segunda passagem (ela derrubou a placa 3 vezes em 11/11/2026)."""

    def gravar_interface(self, **p):
        (self.pasta / "projetos" / "p1" / "interface.json").write_text(json.dumps(p), encoding="utf-8")

    def ler_interface(self):
        return json.loads((self.pasta / "projetos" / "p1" / "interface.json").read_text(encoding="utf-8"))

    def test_troca_com_upscale_volta_com_o_esrgan(self):
        import validacao
        self.gravar_interface(tipo="troca", upscale=True, esrgan=False, megapixels=0.8)
        modelo = self.pasta / "esrgan.pth"
        modelo.write_bytes(b"x")
        with mock.patch.object(validacao, "MODELO_ESRGAN", modelo):
            self.assertTrue(retomada.sem_segunda_passagem("p1"))
        p = self.ler_interface()
        self.assertEqual((p["upscale"], p["esrgan"], p["megapixels"]), (False, True, 0.8))
        self.assertTrue(p["segunda_passagem_desligada_na_retomada"])

    def test_sem_o_modelo_do_esrgan_so_desliga(self):
        import validacao
        self.gravar_interface(tipo="troca", upscale=True)
        with mock.patch.object(validacao, "MODELO_ESRGAN", self.pasta / "nao_existe.pth"):
            self.assertTrue(retomada.sem_segunda_passagem("p1"))
        self.assertEqual((self.ler_interface()["upscale"], self.ler_interface()["esrgan"]), (False, False))

    def test_nao_mexe_no_que_nao_precisa(self):
        self.gravar_interface(tipo="troca", upscale=False, esrgan=True)
        self.assertFalse(retomada.sem_segunda_passagem("p1"))
        self.gravar_interface(tipo="imagem", upscale=True)
        self.assertFalse(retomada.sem_segunda_passagem("p1"))
        self.assertTrue(self.ler_interface()["upscale"])
        # Projeto sem interface.json: so registra, nao quebra
        self.assertFalse(retomada.sem_segunda_passagem("nao_existe"))

    def test_retomada_da_troca_desliga_antes_de_relancar(self):
        self.gravar_interface(tipo="troca", upscale=True, esrgan=False)
        retomada.gravar(["a"], "p1", "gerar", "troca", time.time() - 600)
        vistos = []
        relancar = lambda dados: vistos.append(self.ler_interface()["upscale"])
        with mock.patch.object(retomada, "hora_do_boot", lambda: time.time() - 60):
            fio = retomada.retomar_em_fundo(types.SimpleNamespace(estado=lambda: {"situacao": "pronto"}), types.SimpleNamespace(relancar=relancar), intervalo=0.01)
            fio.join(5)
        self.assertEqual(vistos, [False])


class EmFundo(Base):
    def test_retoma_quando_o_comfy_fica_pronto(self):
        retomada.gravar(["a"], "p1", "gerar", "imagem", time.time() - 600)
        situacoes = iter(["ligando", "ligando", "pronto"])
        vigia = types.SimpleNamespace(estado=lambda: {"situacao": next(situacoes, "pronto")})
        lancados = []
        with mock.patch.object(retomada, "hora_do_boot", lambda: time.time() - 60):
            fio = retomada.retomar_em_fundo(vigia, types.SimpleNamespace(relancar=lancados.append), intervalo=0.01)
            fio.join(5)
        self.assertEqual([d["projeto"] for d in lancados], ["p1"])

    def test_sem_reinicio_apaga_e_nao_retoma(self):
        retomada.gravar(["a"], "p1", "gerar", "imagem", time.time() - 600)
        lancados = []
        with mock.patch.object(retomada, "hora_do_boot", lambda: time.time() - 3600):
            fio = retomada.retomar_em_fundo(types.SimpleNamespace(estado=lambda: {"situacao": "pronto"}), types.SimpleNamespace(relancar=lancados.append))
        self.assertIsNone(fio)
        self.assertEqual(lancados, [])
        self.assertIsNone(retomada.ler())

    def test_comfy_nao_fica_pronto(self):
        retomada.gravar(["a"], "p1", "gerar", "imagem", time.time() - 600)
        lancados = []
        with mock.patch.object(retomada, "hora_do_boot", lambda: time.time() - 60):
            fio = retomada.retomar_em_fundo(types.SimpleNamespace(estado=lambda: {"situacao": "caiu"}), types.SimpleNamespace(relancar=lancados.append), esperar=0.1, intervalo=0.02)
            fio.join(5)
        self.assertEqual(lancados, [])
        self.assertIsNone(retomada.ler())


if __name__ == "__main__":
    unittest.main(verbosity=2)
