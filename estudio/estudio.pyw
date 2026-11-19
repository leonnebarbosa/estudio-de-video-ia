"""Lancador do estudio: um clique liga o ComfyUI escondido, vigia e religa se cair, serve a pagina e abre o navegador.
Roda com pythonw.exe (sem console); o botao "Fechar o estudio" da pagina encerra tudo.
Sem pythonw (Abrir estudio.bat) a saida continua indo para o console."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config

if __name__ == "__main__" and (sys.stdout is None or sys.stderr is None):
    # No pythonw.exe nao ha console: sem isto qualquer print ou erro some (ou quebra). Vai tudo para o log.
    config.LOGS.mkdir(parents=True, exist_ok=True)
    _log = open(config.LOGS / "estudio.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stdout or _log
    sys.stderr = sys.stderr or _log

import traceback, webbrowser
import servidor
from vigia import Vigia
import tarefa, retomada


def criar_vigia() -> Vigia:
    return Vigia(config.COMANDO_COMFY, config.RAIZ_COMFY, config.LOGS)


def principal(porta: int = config.PORTA, abrir_navegador=webbrowser.open, criar_vigia=criar_vigia) -> None:
    """Primeira instancia: liga o ComfyUI, serve a pagina e abre o navegador. Se a porta ja esta em uso
    (estudio ja aberto), so abre o navegador nele e sai, sem criar vigia nenhum."""
    url = f"http://127.0.0.1:{porta}/"
    try:
        s = servidor.criar(porta)
    except OSError:
        abrir_navegador(url)
        return
    v = criar_vigia()
    s.vigia = v
    try:
        try:
            v.ligar()
        except Exception as e:
            # Sem isto o finally fecharia tudo e o navegador nem abriria: a pagina mostra o erro e o botao Tentar de novo
            curto = (str(e) or type(e).__name__)[:200]
            v.falhou(f"Não consegui ligar o ComfyUI: {curto}. Veja logs\\estudio.log.", traceback.format_exc())
        v.correr(tarefa.tarefa.rodando)
        fio = retomada.retomar_em_fundo(v, tarefa.tarefa)
        # A fila (fila.py): segue depois da geracao retomada; sem retomada, os pedidos que sobraram ficam pausados
        tarefa.tarefa.fila.ao_ligar(fio, retomada.ultimo_motivo)
        abrir_navegador(url)
        s.serve_forever()
    finally:
        v.desligar()
        s.server_close()


if __name__ == "__main__":
    # Para o Gerenciador de Tarefas mostrar "Estúdio de vídeo": faz o estudio.exe (e aponta o atalho antigo para ele), em fundo
    import executavel
    executavel.preparar_em_fundo()
    principal()
