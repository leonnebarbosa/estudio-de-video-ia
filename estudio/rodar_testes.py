r"""Roda todos os testes do estudio com um comando.

Uso (de qualquer pasta):
    ComfyUI_windows_portable\python_embeded\python.exe -I estudio\rodar_testes.py

Procura estudio/testes/testar_*.py, roda tudo com unittest e sai com codigo 0 se passou, 1 se algum falhou.
"""
import os, sys, unittest
from pathlib import Path

# Os testes nao descarregam os modelos do LM Studio desta maquina (lmstudio.py)
os.environ["ESTUDIO_SEM_LMSTUDIO"] = "1"

sys.path.insert(0, str(Path(__file__).resolve().parent))  # os testes fazem `import config, servidor...`
import config, extras

# Os testes nao leem o modelos_locais.json desta maquina: o resultado tem que ser o mesmo em qualquer PC
extras._lido = {}


def main():
    suite = unittest.defaultTestLoader.discover(str(config.ESTUDIO / "testes"), pattern="testar_*.py", top_level_dir=str(config.ESTUDIO / "testes"))
    resultado = unittest.TextTestRunner(verbosity=1, buffer=True).run(suite)
    return 0 if resultado.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
