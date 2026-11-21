"""Envia um grafo ao ComfyUI, espera terminar e mede o pico de VRAM."""
import json, subprocess, sys, time, urllib.error, urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config
import loras

if sys.stdout is not None:  # no pythonw.exe nao ha console
    sys.stdout.reconfigure(encoding="utf-8")


def pega(caminho):
    with urllib.request.urlopen(config.URL_COMFY + caminho, timeout=30) as r:
        return json.load(r)


def posta(caminho, dados):
    req = urllib.request.Request(config.URL_COMFY + caminho, data=json.dumps(dados).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def gpu():
    s = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,temperature.gpu", "--format=csv,noheader,nounits"],
                       capture_output=True, text=True, creationflags=config.SEM_JANELA).stdout.strip()
    usada, temp = s.split(",")
    # O nvidia-smi novo imprime a temperatura com decimais ("8447, 70.66"): le como float e arredonda
    return round(float(usada)), round(float(temp))


TEMP_MIN = 85  # o limite antigo: nunca para antes disso
_limite = {}


def limite_temperatura(rodar=None) -> int:
    """Temperatura em que a geracao para. O local.json manda ({"temp_max": 92}); senao 90 °C, com 2 °C de folga abaixo
    do "GPU Max Operating Temp" que a placa informa, se for menor (a placa ja se freia ali), e nunca abaixo de 85 °C."""
    if config.TEMP_MAX_LOCAL is not None:
        return config.TEMP_MAX_LOCAL
    if "valor" not in _limite:
        limite = config.TEMP_MAX_PADRAO
        try:
            s = (rodar or subprocess.run)(["nvidia-smi", "-q", "-d", "TEMPERATURE"], capture_output=True, text=True, timeout=10, creationflags=config.SEM_JANELA).stdout
            for linha in s.splitlines():
                nome, _, valor = linha.partition(":")
                if nome.strip() == "GPU Max Operating Temp" and valor.strip().removesuffix("C").strip().isdigit():
                    limite = min(limite, int(valor.strip().removesuffix("C")) - 2)
        except Exception:
            pass
        _limite["valor"] = max(TEMP_MIN, limite)
    return _limite["valor"]


PERDIDO_MAX = 3  # consultas seguidas sem o pedido no historico nem na fila


def _na_fila(pid, fila):
    """O id do pedido e o elemento [1] de cada item de queue_running e queue_pending."""
    return any(len(e) > 1 and e[1] == pid for e in (fila.get("queue_running") or []) + (fila.get("queue_pending") or []))


def rodar(g, limite=7200):
    # As LoRAs vao pelo nome do arquivo; aqui viram o caminho atual dentro de models/loras (podem estar em subpastas)
    loras.resolver_grafo(g)
    try:
        pid = json.loads(posta("/prompt", {"prompt": g}))["prompt_id"]
    except urllib.error.HTTPError as e:
        return {"status": "recusado", "erro": e.read().decode()[:3000], "segundos": 0, "pico_vram": 0, "temp_max": 0, "saidas": {}}
    except OSError as e:
        return {"status": "servidor caiu", "erro": str(e), "segundos": 0, "pico_vram": 0, "temp_max": 0, "saidas": {}}
    inicio = time.time()
    pico = temp = falhas = perdido = 0
    while time.time() - inicio < limite:
        try:
            u, t = gpu()
            pico, temp = max(pico, u), max(temp, t)
            h = pega(f"/history/{pid}")
            achou = pid in h or _na_fila(pid, pega("/queue"))
            falhas = 0
        except Exception as e:
            falhas += 1
            if falhas >= 12:
                return {"status": "servidor caiu", "erro": str(e), "segundos": time.time() - inicio, "pico_vram": pico, "temp_max": temp, "saidas": {}}
            time.sleep(5)
            continue
        # Se o vigia religou o ComfyUI, o pedido sumiu: o historico fica vazio para sempre
        perdido = 0 if achou else perdido + 1
        if perdido >= PERDIDO_MAX:
            return {"status": "servidor caiu", "erro": "o ComfyUI foi reiniciado e perdeu o pedido", "segundos": round(time.time() - inicio), "pico_vram": pico, "temp_max": temp, "saidas": {}}
        if pid in h:
            s = h[pid]["status"]
            erro = ""
            for m in s["messages"]:
                if m[0] == "execution_error":
                    erro = f"{m[1].get('node_id')} {m[1].get('node_type')}: {m[1].get('exception_message', '')[:1500]}"
            return {"status": s["status_str"], "erro": erro, "segundos": round(time.time() - inicio), "pico_vram": pico, "temp_max": temp, "saidas": h[pid].get("outputs", {})}
        time.sleep(2)
    # Tira o prompt da fila para o proximo teste nao ficar esperando atras dele
    try:
        posta("/queue", {"delete": [pid]})
        posta("/interrupt", {})
    except OSError as e:
        return {"status": "servidor caiu", "erro": str(e), "segundos": limite, "pico_vram": pico, "temp_max": temp, "saidas": {}}
    return {"status": "limite", "erro": "", "segundos": limite, "pico_vram": pico, "temp_max": temp, "saidas": {}}
