"""Vigia do ComfyUI: liga o processo escondido, confere a cada 5 s se ele ainda responde e religa sozinho.

Regras (passo):
- o processo saiu: religa, mesmo durante uma geracao;
- 60 s seguidos sem resposta e nenhuma geracao em andamento: mata e religa (durante a geracao nunca religa por silencio,
  porque o ComfyUI pode ficar mudo enquanto carrega um modelo grande);
- a primeira ligada de cada ligar() tem 420 s para ficar pronta (a primeira vez o ComfyUI varre a pasta de modelos);
  uma religada tem 180 s. Nao ficar pronta no prazo, ou o processo morrer antes disso, conta como falha;
  2 falhas seguidas e o vigia desiste ("caiu") ate alguem chamar ligar() de novo;
- outro programa na porta 8188: so mata se for um python (um ComfyUI esquecido); senao nao liga e avisa.
O ComfyUI fica preso a um Job Object do Windows: se o lancador morrer (pythonw fechado, queda), o Windows fecha o ComfyUI junto.
O relogio vem de fora (parametro `agora` de passo), assim os testes controlam o tempo."""
import os, subprocess, threading, time, urllib.request
from pathlib import Path
from typing import Callable

import config

PORTA_COMFY = config.PORTA_COMFY
SILENCIO_MAX = 60
PRAZO_PRONTO = 180
PRAZO_PRIMEIRA = 420
FALHAS_MAX = 2
INTERVALO = 5
MSG_CAIU = "O ComfyUI não voltou depois de 2 tentativas. A placa pode ter caído: se continuar assim, reinicie o PC."
MSG_PORTA = "A porta {porta} está ocupada por {nome} (pid {pid}). Feche esse programa e clique em Tentar de novo."


def consultar_comfy() -> bool:
    """Uma consulta rapida ao ComfyUI. Sem resposta em 2 s conta como silencio."""
    try:
        with urllib.request.urlopen(config.URL_COMFY + "/queue", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def matar_arvore(pid: int) -> None:
    try:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=15, creationflags=config.SEM_JANELA)
    except subprocess.TimeoutExpired:
        pass


def nome_do_pid(pid: int) -> str:
    import psutil
    try:
        return psutil.Process(pid).name()
    except (psutil.Error, OSError):
        return "um programa desconhecido"


# --- Job Object: o Windows mata o ComfyUI quando o ultimo handle do job fecha (o lancador morreu) ---
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9


def _kernel32():
    import ctypes
    from ctypes import wintypes

    class BASICA(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64), ("LimitFlags", wintypes.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t), ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

    class IO(ctypes.Structure):
        _fields_ = [(n, ctypes.c_uint64) for n in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                                                   "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class ESTENDIDA(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BASICA), ("IoInfo", IO), ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    k = ctypes.WinDLL("kernel32", use_last_error=True)  # instancia propria: os argtypes nao vazam para outros modulos
    k.CreateJobObjectW.argtypes, k.CreateJobObjectW.restype = [ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE
    k.SetInformationJobObject.argtypes, k.SetInformationJobObject.restype = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL
    k.AssignProcessToJobObject.argtypes, k.AssignProcessToJobObject.restype = [wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL
    k.CloseHandle.argtypes, k.CloseHandle.restype = [wintypes.HANDLE], wintypes.BOOL
    return ctypes, k, ESTENDIDA


def job_que_mata_ao_fechar() -> int:
    """Cria o job com JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE e devolve o handle. Erro do Windows vira OSError."""
    ctypes, k, ESTENDIDA = _kernel32()
    job = k.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    info = ESTENDIDA()
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not k.SetInformationJobObject(job, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, ctypes.byref(info), ctypes.sizeof(info)):
        erro = ctypes.WinError(ctypes.get_last_error())
        k.CloseHandle(job)
        raise erro
    return job


def vincular_ao_job(job: int, proc) -> None:
    """Poe o processo (um subprocess.Popen) no job."""
    ctypes, k, _ = _kernel32()
    if not k.AssignProcessToJobObject(job, int(proc._handle)):
        raise ctypes.WinError(ctypes.get_last_error())


def fechar_job(job: int) -> None:
    _, k, _ = _kernel32()
    k.CloseHandle(job)


def pid_na_porta(porta: int) -> int | None:
    """Pid do processo que escuta em `porta`, ou None."""
    import psutil
    try:
        for c in psutil.net_connections(kind="tcp"):
            if c.status == psutil.CONN_LISTEN and c.laddr and c.laddr.port == porta and c.pid:
                return c.pid
    except (psutil.Error, OSError):
        pass
    return None


class Vigia:
    def __init__(self, comando: list[str], cwd: Path, logs: Path, consultar: Callable[[], bool] = consultar_comfy,
                 abrir: Callable = subprocess.Popen, matar: Callable[[int], None] = matar_arvore,
                 pid_na_porta: Callable[[int], int | None] = pid_na_porta, nome_do_pid: Callable[[int], str] = nome_do_pid,
                 vincular: Callable | None = None):
        self.comando, self.cwd, self.logs = comando, Path(cwd), Path(logs)
        self.consultar, self.abrir, self.matar, self.pid_na_porta, self.nome_do_pid = consultar, abrir, matar, pid_na_porta, nome_do_pid
        # vincular(proc) prende o processo ao job do lancador; os testes passam um falso
        self.vincular = vincular if vincular is not None else self._vincular_ao_job
        self.job = None  # handle do Job Object; fica aberto enquanto o lancador viver
        self.trava = threading.RLock()
        self.proc = None
        self.situacao, self.mensagem, self.religadas = "desligado", "", 0
        self.falhas = 0
        self.primeira = False   # a tentativa atual e a primeira ligada de um ligar() (prazo maior)
        self.inicio = None      # quando a tentativa atual comecou (relogio de passo); None = ainda nao visto
        self.ultimo_ok = None   # ultima vez que o ComfyUI respondeu
        self.parar_fio = threading.Event()

    def registrar(self, texto: str) -> None:
        """Uma linha em logs/estudio.log. Nunca quebra quem chama."""
        try:
            self.logs.mkdir(parents=True, exist_ok=True)
            with open(self.logs / "estudio.log", "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} vigia: {texto.rstrip()}\n")
        except Exception:
            pass

    def _vincular_ao_job(self, proc) -> None:
        if self.job is None:
            self.job = job_que_mata_ao_fechar()
        vincular_ao_job(self.job, proc)

    # --- processo ---
    def _vivo(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def _matar_o_meu(self) -> None:
        if self._vivo():
            self.matar(self.proc.pid)
        self.proc = None

    def _iniciar(self, agora: float | None) -> None:
        """Mata o que for preciso (o meu processo velho e um ComfyUI esquecido na 8188) e abre o meu.
        Se a porta esta com um programa que nao e python, nao mata nada: fica "caiu" com o aviso."""
        self._matar_o_meu()
        outro = self.pid_na_porta(PORTA_COMFY)
        if outro:
            nome = self.nome_do_pid(outro)
            self.registrar(f"a porta {PORTA_COMFY} esta ocupada pelo pid {outro} ({nome}).")
            if not nome.lower().startswith("python"):
                self.registrar("nao e um python: nao mato e nao ligo o ComfyUI.")
                self.situacao, self.mensagem = "caiu", MSG_PORTA.format(porta=PORTA_COMFY, nome=nome, pid=outro)
                return
            self.registrar(f"matando o pid {outro} ({nome}) para ligar o ComfyUI do estudio.")
            self.matar(outro)
        self.logs.mkdir(parents=True, exist_ok=True)
        arquivo = self.logs / time.strftime("comfyui_%Y%m%d_%H%M.log")
        ambiente = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
        with open(arquivo, "ab") as log:
            self.proc = self.abrir(self.comando, cwd=str(self.cwd), stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                   env=ambiente, creationflags=config.SEM_JANELA)
        try:
            self.vincular(self.proc)
        except Exception as e:  # sem o job o ComfyUI so nao fecha sozinho se o lancador morrer; nunca impede a ligada
            self.registrar(f"nao consegui prender o ComfyUI ao job do lancador: {e!r}")
        self.inicio, self.ultimo_ok = agora, agora

    def ligar(self) -> None:
        """Liga o ComfyUI (tomando o lugar de um ComfyUI alheio na porta) e zera as falhas. Serve tambem para 'Tentar de novo'."""
        with self.trava:
            self.falhas, self.religadas, self.mensagem = 0, 0, ""
            self.situacao, self.primeira = "ligando", True
            self._iniciar(None)

    def tentar_de_novo(self) -> bool:
        """'Tentar de novo' da pagina: so liga se o ComfyUI estiver parado ("caiu" ou "desligado")."""
        with self.trava:
            if self.situacao not in ("caiu", "desligado"):
                return False
            self.ligar()
            return True

    def falhou(self, mensagem: str, detalhe: str = "") -> None:
        """A ligada nem chegou a acontecer (erro ao abrir o processo): fica "caiu" com a mensagem e registra o detalhe."""
        with self.trava:
            self.registrar(f"{mensagem}\n{detalhe}" if detalhe else mensagem)
            try:
                self._matar_o_meu()
            except Exception:
                self.proc = None
            self.situacao, self.mensagem = "caiu", mensagem

    def desligar(self) -> None:
        with self.trava:
            self.parar_fio.set()
            self._matar_o_meu()
            self.situacao, self.mensagem = "desligado", ""

    # --- vigilancia ---
    def _religar(self, agora: float) -> None:
        self.religadas += 1
        self.primeira = False
        self.situacao, self.mensagem = "religando", f"O ComfyUI parou; religando (tentativa {self.religadas})."
        self._iniciar(agora)

    def _falhou(self, agora: float) -> None:
        self.falhas += 1
        if self.falhas >= FALHAS_MAX:
            self._matar_o_meu()
            self.situacao, self.mensagem = "caiu", MSG_CAIU
        else:
            self._religar(agora)

    def passo(self, gerando: bool, agora: float) -> None:
        with self.trava:
            if self.situacao in ("desligado", "caiu"):
                return
            if self.inicio is None:
                self.inicio, self.ultimo_ok = agora, agora
            esperando = self.situacao in ("ligando", "religando")
            if not self._vivo():
                self._falhou(agora) if esperando else self._religar(agora)
                return
            if self.consultar():
                self.ultimo_ok = agora
                if esperando:
                    self.situacao, self.mensagem, self.falhas, self.primeira = "pronto", "", 0, False
                return
            if esperando:
                if agora - self.inicio >= (PRAZO_PRIMEIRA if self.primeira else PRAZO_PRONTO):
                    self._falhou(agora)
            elif gerando:
                self.ultimo_ok = agora  # silencio durante a geracao nao conta
            elif agora - self.ultimo_ok > SILENCIO_MAX:
                self._religar(agora)

    def correr(self, gerando: Callable[[], bool], intervalo: float = INTERVALO) -> threading.Thread:
        """Thread de fundo que chama passo a cada `intervalo` segundos ate desligar()."""
        def laco():
            while not self.parar_fio.wait(intervalo):
                try:
                    self.passo(gerando(), time.monotonic())
                except Exception as e:
                    print(f"Vigia: erro no passo: {e!r}", flush=True)
        self.parar_fio.clear()
        fio = threading.Thread(target=laco, daemon=True, name="vigia")
        fio.start()
        return fio

    def estado(self) -> dict:
        with self.trava:
            return {"situacao": self.situacao, "mensagem": self.mensagem, "religadas": self.religadas}
