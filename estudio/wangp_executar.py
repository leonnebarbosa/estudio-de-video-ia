"""Roda uma lista de tarefas no WanGP (pasta WanGP ao lado do repositorio) pela API Python dele. Chamado pelo troca_wangp.py com o Python do
WanGP (o venv dele), nunca com o do ComfyUI: nao importa nada do estudio.

Uso: <WanGP>\\venv\\Scripts\\python.exe -I -X utf8 -u wangp_executar.py tarefas.json

tarefas.json: {"raiz": "<pasta do WanGP>", "saida": "<pasta de saida>", "cli": [...],
               "tarefas": [{"etapa": "pintar", "settings": {...}, "destino": "<arquivo>"}, ...]}
Fala com o estudio por linhas que comecam com "@@ " seguidas de um JSON:
  {"etapa": e, "tarefa": i, "de": n}          comecou a tarefa i (de 1 a n)
  {"passo": p, "total": t}                    passo da amostragem
  {"pronta": i, "segundos": s}                terminou e copiou o arquivo para o destino
O resto da saida do WanGP passa como texto (sem as barras de progresso, que viram centenas de linhas).
Codigos de saida: 0 ok, 4 falha de uma tarefa.
"""
import json
import shutil
import sys
import time
from pathlib import Path


def avisar(**dados):
    # sys.__stdout__: o WanGP troca o sys.stdout para capturar o print; reimprimir a captura com print vira um ciclo
    # sem fim (travou o primeiro teste de 17/11/2026)
    sys.__stdout__.write("@@ " + json.dumps(dados) + "\n")
    sys.__stdout__.flush()


def texto(linha):
    linha = linha.rstrip()
    # As barras do tqdm (downloads, passos) chegam como dezenas de linhas por segundo
    if linha and "%|" not in linha and "it/s]" not in linha and "s/it]" not in linha:
        sys.__stdout__.write(linha + "\n")
        sys.__stdout__.flush()


def main():
    pedido = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    raiz = Path(pedido["raiz"])
    sys.path.insert(0, str(raiz))
    from shared.api import init

    session = init(root=raiz, output_dir=pedido["saida"], console_output=False, cli_args=pedido.get("cli") or ["--attention", "sage2", "--profile", "4"])
    tarefas = pedido["tarefas"]
    for i, t in enumerate(tarefas, 1):
        avisar(etapa=t["etapa"], tarefa=i, de=len(tarefas))
        inicio = time.time()
        job = session.submit_task(t["settings"])
        ultimo = None
        for evento in job.events.iter(timeout=0.5):
            if evento.kind == "stream":
                texto(evento.data.text)
            elif evento.kind == "progress":
                d = evento.data
                atual, total = getattr(d, "current_step", None), getattr(d, "total_steps", None)
                if total and (atual, total) != ultimo:
                    ultimo = (atual, total)
                    avisar(passo=atual or 0, total=total)
        r = job.result()
        if not r.success or not r.generated_files:
            erros = "; ".join(e.message.strip().splitlines()[0] for e in r.errors) or "o WanGP não devolveu arquivo"
            print(f"FALHA na geracao: {t['etapa']} no WanGP: {erros}", file=sys.__stdout__, flush=True)
            sys.exit(4)
        shutil.copy(r.generated_files[0], t["destino"])
        avisar(pronta=i, segundos=round(time.time() - inicio))


if __name__ == "__main__":
    main()
