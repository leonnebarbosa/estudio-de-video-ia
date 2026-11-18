"""Libera a placa antes de gerar: descarrega os modelos do LM Studio (o Bionic e o mesmo app, da mesma empresa).

O LM Studio mantem o modelo de conversa na placa depois de responder e segue rodando em segundo plano com a janela fechada.
Com uns 7 GB dele ocupados, o ComfyUI nao cabe nos 10 GB da 3080 e passa a trocar pedacos do modelo com a RAM a cada passo:
a geracao fica muito lenta em vez de dar erro (15/11/2026). Antes de cada geracao o estudio pede ao LM Studio, pela linha de
comando dele (lms unload --all), que descarregue tudo. So quando o app esta aberto: chamar o lms com ele fechado poe o servico
dele no ar. Sem o LM Studio instalado nao faz nada."""
import os, subprocess
from pathlib import Path

import config

LMS = Path.home() / ".lmstudio" / "bin" / "lms.exe"
# Os processos do app: o Bionic.exe (nome novo, roda como servico) e os do LM Studio classico
PROCESSOS = {"bionic.exe", "lm studio.exe", "llmster.exe"}


def aberto() -> bool:
    """O LM Studio (ou o Bionic) esta rodando? Pela lista de processos do Windows."""
    try:
        r = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, timeout=15, creationflags=config.SEM_JANELA)
    except (OSError, subprocess.SubprocessError):
        return False
    nomes = {linha.split('","')[0].strip('"').lower() for linha in r.stdout.splitlines() if linha.startswith('"')}
    return bool(nomes & PROCESSOS)


def descarregar() -> str | None:
    """Descarrega os modelos do LM Studio, se ele estiver instalado e aberto. Devolve a resposta do lms (para o registro),
    ou None quando nao havia o que fazer. Nunca impede a geracao: uma falha aqui so fica no texto devolvido.
    Os testes desligam com ESTUDIO_SEM_LMSTUDIO=1 (rodar_testes.py), para nao mexer no LM Studio desta maquina."""
    if os.environ.get("ESTUDIO_SEM_LMSTUDIO") or not LMS.is_file() or not aberto():
        return None
    try:
        r = subprocess.run([str(LMS), "unload", "--all"], capture_output=True, text=True, timeout=60, creationflags=config.SEM_JANELA)
        return (r.stdout + r.stderr).strip() or "descarregado"
    except (OSError, subprocess.SubprocessError) as e:
        return f"falhou: {e}"
