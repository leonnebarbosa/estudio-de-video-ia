"""Todos os caminhos e constantes do estudio, num lugar so.
Os outros modulos fazem `import config` e leem `config.X` na hora de usar (nunca `from config import X`),
assim os testes podem apontar as pastas para outro lugar.

Os caminhos partem da pasta do repositorio, sem letra de disco fixa. O ComfyUI portatil fica dentro dela
(`ComfyUI_windows_portable`, onde o instalador o poe) ou ao lado dela (na pasta de cima).
Um `local.json` na pasta do repositorio troca o lugar e as portas: {"comfy": "E:\\\\ComfyUI_windows_portable", "porta": 8190, "porta_comfy": 8188}."""
import json, subprocess
from pathlib import Path

ESTUDIO = Path(__file__).resolve().parent
WORKFLOWS = ESTUDIO.parent
ARQUIVO_LOCAL = WORKFLOWS / "local.json"


def _local() -> dict:
    try:
        d = json.loads(ARQUIVO_LOCAL.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _raiz_comfy(local: dict) -> Path:
    if isinstance(local.get("comfy"), str) and local["comfy"].strip():
        return Path(local["comfy"])
    dentro = WORKFLOWS / "ComfyUI_windows_portable"
    return dentro if dentro.is_dir() else WORKFLOWS.parent / "ComfyUI_windows_portable"


def _porta(local: dict, chave: str, padrao: int) -> int:
    v = local.get(chave)
    return v if isinstance(v, int) and not isinstance(v, bool) and 1024 <= v <= 65535 else padrao


_LOCAL = _local()

PROJETOS = WORKFLOWS / "projetos"
ENVIOS = WORKFLOWS / "entradas"
LOGS = WORKFLOWS / "logs"

RAIZ_COMFY = _raiz_comfy(_LOCAL)
PYTHON = RAIZ_COMFY / "python_embeded" / "python.exe"
PYTHONW = RAIZ_COMFY / "python_embeded" / "pythonw.exe"
ENTRADA = RAIZ_COMFY / "ComfyUI" / "input"
SAIDA = RAIZ_COMFY / "ComfyUI" / "output"
MODELOS = RAIZ_COMFY / "ComfyUI" / "models"

# WanGP (deepbeepmeep/WanGP), motor opcional da troca de personagem (troca_wangp.py): ao lado do repositorio
# (pasta WanGP), ou onde o local.json disser ({"wangp": "E:\\\\WanGP"}). Roda com o Python do venv dele.
WANGP = Path(_LOCAL["wangp"]) if isinstance(_LOCAL.get("wangp"), str) and _LOCAL["wangp"].strip() else WORKFLOWS.parent / "WanGP"
WANGP_PYTHON = WANGP / "venv" / "Scripts" / "python.exe"

GRAFOS = ESTUDIO / "grafos"
PAGINA = ESTUDIO / "pagina"

PORTA = _porta(_LOCAL, "porta", 8190)
PORTA_COMFY = _porta(_LOCAL, "porta_comfy", 8188)
URL_COMFY = f"http://127.0.0.1:{PORTA_COMFY}"
COMANDO_COMFY = [str(PYTHON), "-u", "-s", r"ComfyUI\main.py", "--windows-standalone-build", "--lowvram", "--reserve-vram", "1.5",
                 "--disable-pinned-memory", "--cache-none", "--fast-disk", "--disable-auto-launch", "--port", str(PORTA_COMFY)]
# --disable-auto-launch: --windows-standalone-build abriria uma aba do ComfyUI a cada ligada; o estudio ja abre a sua pagina

# Janela de console oculta em todo subprocess do servidor (o lancador nao tem console)
SEM_JANELA = subprocess.CREATE_NO_WINDOW
