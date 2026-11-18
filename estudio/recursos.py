"""CPU, memoria, placa e disco para o painel do cabecalho. Cada fonte falha sozinha: o que nao der para ler vira None."""
import collections, subprocess
from pathlib import Path

import psutil

import config
from ambiente import Cache

HISTORICO = collections.deque(maxlen=60)  # 60 leituras de 3 s = 3 minutos
CONSULTA_GPU = "utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw"

psutil.cpu_percent(interval=None)  # a primeira chamada sempre devolve 0; esta so prepara a medida


def _gpu(rodar):
    try:
        s = rodar(["nvidia-smi", f"--query-gpu={CONSULTA_GPU}", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5, creationflags=config.SEM_JANELA).stdout
        # O nvidia-smi imprime a temperatura (e outros campos) com decimais: le tudo como float e so depois arredonda
        uso, usada, total, temp, potencia = [float(x) for x in s.strip().splitlines()[0].split(",")]
        return {"uso": round(uso), "memoria": round(usada), "memoria_total": round(total), "temp": round(temp), "potencia": potencia}
    except Exception:
        return None


def _disco(ps, pasta):
    try:
        pasta = Path(pasta)
        d = ps.disk_usage(str(pasta if pasta.exists() else (pasta.anchor or ".")))
        return {"livre": int(d.free), "total": int(d.total)}
    except Exception:
        return None


def _ram(ps):
    try:
        m = ps.virtual_memory()
        return {"usada": int(m.used), "total": int(m.total)}
    except Exception:
        return None


def _cpu(ps):
    try:
        return float(ps.cpu_percent(interval=None))
    except Exception:
        return None


def ler_recursos(rodar=subprocess.run, ps=psutil, disco=config.PROJETOS):
    cpu, gpu = _cpu(ps), _gpu(rodar)
    HISTORICO.append({"cpu": cpu, "gpu": gpu and gpu["uso"], "gpu_memoria": gpu and gpu["memoria"]})
    return {"cpu": cpu, "ram": _ram(ps), "gpu": gpu, "disco": _disco(ps, disco), "historico": list(HISTORICO)}


# O cache envolve a leitura, nao a resposta: varias abas abertas nao aumentam o ritmo da amostragem
lidos = Cache(2, ler_recursos)
