"""Todos os caminhos e constantes do estudio, num lugar so.
Os outros modulos fazem `import config` e leem `config.X` na hora de usar (nunca `from config import X`),
assim os testes podem apontar as pastas para outro lugar.

Os caminhos partem da pasta do repositorio, sem letra de disco fixa. O ComfyUI portatil fica dentro dela
(`ComfyUI_windows_portable`, onde o instalador o poe) ou ao lado dela (na pasta de cima).
Um `local.json` na pasta do repositorio troca o lugar e as portas: {"comfy": "E:\\\\ComfyUI_windows_portable", "porta": 8190, "porta_comfy": 8188}.

Acesso remoto (rede privada, por exemplo Tailscale), tambem no local.json (nunca no codigo):
  "remoto": {"escutar": "<IPv4 da rede privada>", "chaves": {"operador": "<24+ caracteres>", "completo": "<outros 24+ caracteres>"}}
As chaves usam so letras, numeros, - e _ (pelo menos 24) e precisam ser diferentes.
`python -I estudio/acesso.py --gerar` imprime um trecho "remoto" com chaves novas."""
import ipaddress, json, re, subprocess
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


CHAVE_VALIDA = re.compile(r"[A-Za-z0-9_-]{24,}")  # o que o acesso.py --gerar produz (token_urlsafe)


def _remoto(local: dict) -> dict:
    """Le local.json["remoto"]: IPv4 onde escutar (fora loopback, 0.0.0.0 e multicast) e as chaves, descartando o que for invalido."""
    r = local.get("remoto")
    r = r if isinstance(r, dict) else {}
    escutar = None
    if isinstance(r.get("escutar"), str):
        try:
            ip = ipaddress.IPv4Address(r["escutar"].strip())
            escutar = None if ip.is_loopback or ip.is_unspecified or ip.is_multicast else str(ip)
        except ValueError:
            pass
    c = r.get("chaves")
    c = c if isinstance(c, dict) else {}
    chaves = {n: c[n] for n in ("operador", "completo") if isinstance(c.get(n), str) and CHAVE_VALIDA.fullmatch(c[n])}
    if len(chaves) == 2 and chaves["operador"] == chaves["completo"]:
        # Com as duas iguais nao daria para saber o nivel de quem chega: nenhuma vale
        print("AVISO: as chaves operador e completo do local.json são iguais; o acesso remoto fica desligado.", flush=True)
        chaves = {}
    return {"escutar": escutar, "chaves": chaves}


REMOTO = _remoto(_LOCAL)

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

def _temp_max(local: dict):
    v = local.get("temp_max")
    return v if isinstance(v, int) and not isinstance(v, bool) and 70 <= v <= 95 else None


# Temperatura da placa em que a geracao para (comfy_api.limite_temperatura): 90 °C, ou menos se a placa disser que
# opera so ate menos que isso. Notebook esquenta mais; o local.json troca: {"temp_max": 92} (de 70 a 95).
TEMP_MAX_PADRAO = 90
TEMP_MAX_LOCAL = _temp_max(_LOCAL)

PORTA = _porta(_LOCAL, "porta", 8190)
PORTA_COMFY = _porta(_LOCAL, "porta_comfy", 8188)
URL_COMFY = f"http://127.0.0.1:{PORTA_COMFY}"
COMANDO_COMFY = [str(PYTHON), "-u", "-s", r"ComfyUI\main.py", "--windows-standalone-build", "--lowvram", "--reserve-vram", "1.5",
                 "--disable-pinned-memory", "--cache-none", "--fast-disk", "--disable-auto-launch", "--port", str(PORTA_COMFY)]
# --disable-auto-launch: --windows-standalone-build abriria uma aba do ComfyUI a cada ligada; o estudio ja abre a sua pagina

# Janela de console oculta em todo subprocess do servidor (o lancador nao tem console)
SEM_JANELA = subprocess.CREATE_NO_WINDOW
