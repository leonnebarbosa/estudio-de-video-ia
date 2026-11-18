"""Testes do painel de recursos. Tudo com nvidia-smi e psutil falsos: nao toca na placa.

Uso: python -I testar_recursos.py
"""
import subprocess, sys, unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import recursos


def nvidia(saida):
    def rodar(*a, **k):
        if isinstance(saida, Exception):
            raise saida
        return SimpleNamespace(stdout=saida, returncode=0)
    return rodar


class PsFalso:
    def __init__(self, cpu=12.5, falha=()):
        self.cpu, self.falha = cpu, falha

    def cpu_percent(self, interval=None):
        if "cpu" in self.falha:
            raise OSError("sem cpu")
        return self.cpu

    def virtual_memory(self):
        if "ram" in self.falha:
            raise OSError("sem ram")
        return SimpleNamespace(used=8 * 2**30, total=32 * 2**30)

    def disk_usage(self, caminho):
        if "disco" in self.falha:
            raise OSError("sem disco")
        return SimpleNamespace(free=500 * 2**30, total=1000 * 2**30)


class Recursos(unittest.TestCase):
    def setUp(self):
        recursos.HISTORICO.clear()

    def test_recursos_completos(self):
        r = recursos.ler_recursos(nvidia("37, 5120, 10240, 61, 180.5\n"), PsFalso(), Path("."))
        self.assertEqual(r["gpu"], {"uso": 37, "memoria": 5120, "memoria_total": 10240, "temp": 61, "potencia": 180.5})
        self.assertEqual(r["cpu"], 12.5)
        self.assertEqual(r["ram"], {"usada": 8 * 2**30, "total": 32 * 2**30})
        self.assertEqual(r["disco"], {"livre": 500 * 2**30, "total": 1000 * 2**30})
        self.assertEqual(r["historico"], [{"cpu": 12.5, "gpu": 37, "gpu_memoria": 5120}])

    def test_decimais_do_nvidia_smi(self):
        r = recursos.ler_recursos(nvidia("37, 5120, 10240, 61.44, 180.5"), PsFalso(), Path("."))
        self.assertEqual(r["gpu"]["temp"], 61)
        self.assertIsInstance(r["gpu"]["temp"], int)
        r = recursos.ler_recursos(nvidia("37.0, 5120.5, 10240.0, 67.44, 231.76"), PsFalso(), Path("."))
        self.assertEqual(r["gpu"], {"uso": 37, "memoria": 5120, "memoria_total": 10240, "temp": 67, "potencia": 231.76})

    def test_recursos_sem_nvidia_smi(self):
        for erro in (FileNotFoundError("nvidia-smi"), subprocess.TimeoutExpired("nvidia-smi", 5)):
            r = recursos.ler_recursos(nvidia(erro), PsFalso(), Path("."))
            self.assertIsNone(r["gpu"])
            self.assertEqual(r["cpu"], 12.5)
            self.assertIsNotNone(r["ram"])
            self.assertIsNotNone(r["disco"])
        r = recursos.ler_recursos(nvidia("lixo, sem numeros"), PsFalso(), Path("."))
        self.assertIsNone(r["gpu"])

    def test_cada_fonte_falha_sozinha(self):
        r = recursos.ler_recursos(nvidia("37, 5120, 10240, 61, 180.5"), PsFalso(falha=("cpu", "ram", "disco")), Path("."))
        self.assertIsNone(r["cpu"])
        self.assertIsNone(r["ram"])
        self.assertIsNone(r["disco"])
        self.assertIsNotNone(r["gpu"])

    def test_historico_guarda_60(self):
        for i in range(75):
            r = recursos.ler_recursos(nvidia("37, 5120, 10240, 61, 180.5"), PsFalso(cpu=float(i)), Path("."))
        self.assertEqual(len(r["historico"]), 60)
        self.assertEqual(r["historico"][0]["cpu"], 15.0)
        self.assertEqual(r["historico"][-1]["cpu"], 74.0)

    def test_disco_inexistente_usa_a_raiz(self):
        vistos = []
        ps = PsFalso()
        ps.disk_usage = lambda c: (vistos.append(c), SimpleNamespace(free=1, total=2))[1]
        recursos.ler_recursos(nvidia("1, 2, 3, 4, 5"), ps, Path("Z:/nao/existe/mesmo"))
        self.assertEqual(vistos, [str(Path("Z:/nao/existe/mesmo").anchor or Path("Z:/nao/existe/mesmo").drive + "\\")])


if __name__ == "__main__":
    unittest.main()
