r"""Roda todos os testes do estudio com um comando.

Uso (de qualquer pasta):
    ComfyUI_windows_portable\python_embeded\python.exe -I estudio\rodar_testes.py

Procura estudio/testes/testar_*.py, roda tudo com unittest e sai com codigo 0 se passou, 1 se algum falhou.
"""
import os, sys, tempfile, unittest
from pathlib import Path

# Os testes nao descarregam os modelos do LM Studio desta maquina (lmstudio.py)
os.environ["ESTUDIO_SEM_LMSTUDIO"] = "1"

sys.path.insert(0, str(Path(__file__).resolve().parent))  # os testes fazem `import config, servidor...`
import config, extras

# Os testes nao leem o modelos_locais.json desta maquina: o resultado tem que ser o mesmo em qualquer PC
extras._lido = {}
# Nem as palavras-chave editadas nesta maquina (palavras_loras.json), nem consultam fichas na internet:
# cada teste que grava troca o arquivo por um temporario
import palavras_lora
palavras_lora._dados = {"arquivos": {}}
palavras_lora.ARQUIVO = "palavras_loras_dos_testes.json"
palavras_lora.LIGADO = False
# Nem o registro de midias desta maquina (midias.json): quem envia arquivo nos testes grava neste, que nao existe de verdade
import midias
_pasta_midias = tempfile.TemporaryDirectory(prefix="estudio_midias_")  # some sozinha ao fim da execucao
midias.ARQUIVO = Path(_pasta_midias.name) / "midias.json"
# Nem os planos e links desta maquina (logs/planos.json e logs/links.json): ficam numa pasta temporaria
import links, planos
links.ARQUIVO = Path(_pasta_midias.name) / "links.json"
planos.ARQUIVO = Path(_pasta_midias.name) / "planos.json"
# A frase da fila consulta o ComfyUI: nos testes ele esta sempre ligado e livre (quem testa os outros estados troca de novo)
import estimativas
estimativas.comfy = lambda: {"ligado": True, "ocupado": False}


def main():
    suite = unittest.defaultTestLoader.discover(str(config.ESTUDIO / "testes"), pattern="testar_*.py", top_level_dir=str(config.ESTUDIO / "testes"))
    resultado = unittest.TextTestRunner(verbosity=1, buffer=True).run(suite)
    return 0 if resultado.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
