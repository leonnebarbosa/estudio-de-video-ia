"""Testes da liberacao da placa antes de gerar (lmstudio.py). Nao chamam o LM Studio de verdade.
Uso: python -I testar_lmstudio.py"""
import os, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import lmstudio

LISTA = '"System Idle Process","0","Services","0","8 K"\n"Bionic.exe","31768","Console","1","428.732 K"\n"python.exe","4492","Console","1","1.000 K"\n'


def processos(saida):
    return lambda cmd, **k: subprocess.CompletedProcess(cmd, 0, stdout=saida, stderr="")


class Aberto(unittest.TestCase):
    def test_acha_o_bionic_e_o_lm_studio(self):
        with mock.patch.object(lmstudio.subprocess, "run", processos(LISTA)):
            self.assertTrue(lmstudio.aberto())
        with mock.patch.object(lmstudio.subprocess, "run", processos('"LM Studio.exe","1","Console","1","1 K"\n')):
            self.assertTrue(lmstudio.aberto())
        with mock.patch.object(lmstudio.subprocess, "run", processos('"python.exe","1","Console","1","1 K"\n')):
            self.assertFalse(lmstudio.aberto())

    def test_falha_do_tasklist_conta_como_fechado(self):
        def quebra(*a, **k):
            raise OSError("sem tasklist")
        with mock.patch.object(lmstudio.subprocess, "run", quebra):
            self.assertFalse(lmstudio.aberto())


class Descarregar(unittest.TestCase):
    def setUp(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, d, True)
        self.lms = d / "lms.exe"
        self.lms.write_bytes(b"x")
        self.chamadas = []
        ambiente = {k: v for k, v in os.environ.items() if k != "ESTUDIO_SEM_LMSTUDIO"}
        for p in (mock.patch.dict(os.environ, ambiente, clear=True), mock.patch.object(lmstudio, "LMS", self.lms)):
            p.start()
            self.addCleanup(p.stop)

    def rodar(self, cmd, **k):
        self.chamadas.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="Unloaded 1 model." if cmd[0] == str(self.lms) else LISTA, stderr="")

    def test_aberto_descarrega_tudo(self):
        with mock.patch.object(lmstudio.subprocess, "run", self.rodar):
            self.assertEqual(lmstudio.descarregar(), "Unloaded 1 model.")
        self.assertEqual(self.chamadas[-1], [str(self.lms), "unload", "--all"])

    def test_fechado_nao_chama_o_lms(self):
        # Chamar o lms com o app fechado poria o servico dele no ar
        with mock.patch.object(lmstudio, "aberto", lambda: False), mock.patch.object(lmstudio.subprocess, "run", self.rodar):
            self.assertIsNone(lmstudio.descarregar())
        self.assertEqual(self.chamadas, [])

    def test_sem_lm_studio_instalado_nao_faz_nada(self):
        self.lms.unlink()
        with mock.patch.object(lmstudio.subprocess, "run", self.rodar):
            self.assertIsNone(lmstudio.descarregar())
        self.assertEqual(self.chamadas, [])

    def test_desligado_nos_testes(self):
        with mock.patch.dict(os.environ, {"ESTUDIO_SEM_LMSTUDIO": "1"}), mock.patch.object(lmstudio.subprocess, "run", self.rodar):
            self.assertIsNone(lmstudio.descarregar())
        self.assertEqual(self.chamadas, [])

    def test_falha_do_lms_nao_impede_a_geracao(self):
        def rodar(cmd, **k):
            if cmd[0] == str(self.lms):
                raise subprocess.TimeoutExpired(cmd, 60)
            return subprocess.CompletedProcess(cmd, 0, stdout=LISTA, stderr="")
        with mock.patch.object(lmstudio.subprocess, "run", rodar):
            self.assertTrue(lmstudio.descarregar().startswith("falhou"))


if __name__ == "__main__":
    unittest.main()
