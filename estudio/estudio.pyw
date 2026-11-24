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

import threading, traceback, webbrowser
import servidor
from vigia import Vigia
import mcp_ferramentas, mcp_completo, palavras_lora, tarefa, retomada


def criar_vigia() -> Vigia:
    return Vigia(config.COMANDO_COMFY, config.RAIZ_COMFY, config.LOGS)


INTERVALO_REMOTO = 30  # s entre as tentativas de abrir o acesso remoto


class AcessoRemoto:
    """O mesmo estudio na VPN (servidor.criar_remoto: so atende com chave). Se o IP ainda nao existe (a VPN liga depois do
    estudio, ou caiu), tenta de novo a cada `intervalo` s ate abrir ou o estudio fechar; avisa no log so na primeira falha
    e quando abrir. Sem o remoto configurado no local.json, nao tenta."""

    def __init__(self, porta, vigia, criar_remoto=servidor.criar_remoto, intervalo=INTERVALO_REMOTO):
        self.porta, self.vigia, self.intervalo = porta, vigia, intervalo
        self._criar = criar_remoto
        self._parar = threading.Event()
        self._trava = threading.Lock()
        self.servidor = None

    def tentar(self):
        """Tenta ate abrir (devolve o servidor, ja servindo numa thread) ou ate fechar() (None). Sem configuracao: None."""
        falhou = False
        while not self._parar.is_set():
            try:
                s = self._criar(self.porta, self.vigia)
            except OSError as e:
                if not falhou:
                    print(f"AVISO: não consegui abrir o acesso remoto ({e}). Tento de novo a cada {self.intervalo:g} s.", flush=True)
                    falhou = True
                self._parar.wait(self.intervalo)
                continue
            if s is None:
                return None
            with self._trava:
                if self._parar.is_set():
                    s.server_close()
                    return None
                self.servidor = s
                # Dentro da trava: um shutdown() antes do serve_forever comecar esperaria para sempre
                threading.Thread(target=s.serve_forever, daemon=True).start()
            if falhou:
                print("Acesso remoto aberto.", flush=True)
            return s
        return None

    def em_fundo(self) -> threading.Thread:
        fio = threading.Thread(target=self.tentar, daemon=True)
        fio.start()
        return fio

    def fechar(self):
        with self._trava:
            self._parar.set()
            s, self.servidor = self.servidor, None
        if s is not None:
            s.shutdown()
            s.server_close()


def principal(porta: int = config.PORTA, abrir_navegador=webbrowser.open, criar_vigia=criar_vigia) -> None:
    """Primeira instancia: liga o ComfyUI, serve a pagina e abre o navegador. Se a porta ja esta em uso
    (estudio ja aberto), so abre o navegador nele e sai, sem criar vigia nenhum."""
    url = f"http://127.0.0.1:{porta}/"
    try:
        s = servidor.criar(porta)
    except OSError:
        abrir_navegador(url)
        return
    # O chamar_api do MCP fala com a API nesta porta
    mcp_completo.PORTA_API = porta
    v = criar_vigia()
    s.vigia = v
    remoto = AcessoRemoto(porta, v)
    try:
        # O mesmo estudio na VPN: so atende com chave (acesso.py); sem local.json configurado nao liga
        remoto.em_fundo()
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
        # Palavras-chave das LoRAs novas: consulta a ficha de cada uma em segundo plano, fora das gerações
        palavras_lora.vigiar(lambda: tarefa.tarefa.rodando() or bool(servidor.ambiente.comfy().get("ocupado")))
        abrir_navegador(url)
        s.serve_forever()
    finally:
        v.desligar()
        remoto.fechar()
        s.server_close()


if __name__ == "__main__":
    # Para o Gerenciador de Tarefas mostrar "Estúdio de vídeo": faz o estudio.exe (e aponta o atalho antigo para ele), em fundo
    import executavel
    executavel.preparar_em_fundo()
    # O registro das chamadas do MCP so liga aqui, no estudio de verdade (os testes chamam principal() e nao gravam nele)
    import mcp_servidor
    mcp_servidor.REGISTRO = config.LOGS / "mcp.log"
    principal()
