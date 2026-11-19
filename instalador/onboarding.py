"""Pagina de boas-vindas do estudio: numa maquina limpa, instala o que falta e baixa os modelos, tudo pelo navegador.

Roda no Python minimo (o "embeddable" do python.org, so a biblioteca padrao) que o "Instalar estudio.bat" baixa em segundos.
A pagina abre na hora e mostra cada passo com o progresso:
  1. conferir o computador (placa NVIDIA, memoria, disco)
  2. baixar o ComfyUI portatil oficial e por o nucleo na versao testada
  3. instalar os nos extras, cada um no commit testado (instalador/nos.json)
  4. instalar as dependencias Python com as versoes testadas (instalador/requisitos_estudio.txt)
  5. criar os atalhos na area de trabalho
Em paralelo baixa os pacotes de modelos escolhidos (estudio/pacotes.json). O estudio pode ser aberto assim que os passos
terminam, mesmo com modelos ainda baixando. Rodar de novo pula o que ja esta feito: serve tambem para baixar mais pacotes.

Tudo fica dentro da pasta do repositorio: ComfyUI_windows_portable/ ao lado de estudio/. Numa maquina que ja tem o
ComfyUI ao lado da pasta (como a de desenvolvimento), usa esse."""
import ctypes, hashlib, json, os, shutil, subprocess, sys, tempfile, threading, time, traceback, urllib.error, urllib.parse, urllib.request, webbrowser, zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

AQUI = Path(__file__).resolve().parent
REPO = AQUI.parent
sys.path.insert(0, str(REPO / "estudio"))
import config, pacotes  # noqa: E402
from erros import Erro  # noqa: E402

PORTAS = range(8191, 8200)
BAIXADOS = AQUI / "baixados"
ENDERECO = BAIXADOS / "endereco.txt"  # o endereco da pagina, para o iniciar.ps1 mostrar
LOG = REPO / "logs" / "instalacao.log"
TAR = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "tar.exe"
SEM_JANELA = subprocess.CREATE_NO_WINDOW

# ComfyUI: o portatil oficial v0.43.0 (python, torch e CUDA) e o nucleo no commit testado (v0.43.2, 09/11/2026)
VERSAO_PORTATIL = "v0.43.0"
PORTATEIS = {  # tamanho e sha256 publicados pelo GitHub na pagina da versao
    "nvidia": (2039673203, "4928f88e6a8407c4574d4f7d92cfeba020d782edba4a076b7d107ecc98955e50"),
    "nvidia_cu126": (1930972692, "691dcb5295e73594c6530ff7f3fca8dbe7dfb45114b951328c5dd3df0fff6c6b"),
}
URL_PORTATIL = "https://github.com/Comfy-Org/ComfyUI/releases/download/{versao}/ComfyUI_windows_portable_{variante}.7z"
COMMIT_NUCLEO = "423cbd20511becb1f16122ab518e92e58bfa03d9"
URL_NUCLEO = "https://github.com/Comfy-Org/ComfyUI/archive/{commit}.zip"
OCIOSO_MAX = 15 * 60  # sem a pagina aberta e sem nada rodando por 15 min, o instalador fecha sozinho

PASSOS = [("placa", "Conferir o computador"), ("comfy", "Baixar o ComfyUI"), ("nos", "Instalar os complementos do ComfyUI"),
          ("dependencias", "Instalar as dependências"), ("atalho", "Criar os atalhos na área de trabalho")]


def registrar(texto: str):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {texto}\n")


def ultimas_linhas(n=40) -> list:
    try:
        return LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
    except OSError:
        return []


def raiz_comfy() -> Path:
    """O ComfyUI que o estudio vai usar: o que o config acha, se ja estiver instalado; senao, dentro da pasta do repositorio."""
    if (config.RAIZ_COMFY / "python_embeded" / "python.exe").is_file():
        return config.RAIZ_COMFY
    return REPO / "ComfyUI_windows_portable"


def comfy_de_fora() -> bool:
    """ComfyUI que ja existia fora da pasta do repositorio (maquina de desenvolvimento): nao se instala nada nele."""
    raiz = raiz_comfy()
    return raiz != REPO / "ComfyUI_windows_portable" and (raiz / "python_embeded" / "python.exe").is_file()


def pasta_models() -> Path:
    return raiz_comfy() / "ComfyUI" / "models"


# ---------- computador ----------

class _Memoria(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong), ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]


def ler_sistema() -> dict:
    s = {"placa": None, "vram_gb": None, "driver": None, "cc": None, "ram_gb": None, "livre": None, "avisos": [], "erro": None}
    try:
        saida = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version,compute_cap", "--format=csv,noheader,nounits"],
                               capture_output=True, text=True, timeout=10, creationflags=SEM_JANELA).stdout.strip().splitlines()[0]
        nome, mem, driver, cc = [x.strip() for x in saida.split(",")]
        s.update(placa=nome, vram_gb=round(float(mem) / 1024, 1), driver=driver, cc=float(cc))
    except Exception:
        s["erro"] = ("Não achei uma placa de vídeo NVIDIA: o comando nvidia-smi não respondeu. O estúdio precisa de uma placa NVIDIA "
                     "com o driver instalado. Instale o driver mais novo em nvidia.com/drivers, reinicie o PC e abra o instalador de novo.")
    try:
        m = _Memoria()
        m.dwLength = ctypes.sizeof(_Memoria)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        s["ram_gb"] = round(m.ullTotalPhys / 2**30)
    except Exception:
        pass
    try:
        s["livre"] = pacotes.livre(REPO)
    except OSError:
        pass
    if s["vram_gb"] is not None and s["vram_gb"] < 8:
        s["avisos"].append(f"A placa tem {s['vram_gb']:g} GB de memória. O estúdio foi testado com 10 GB; com menos de 8 GB as gerações podem falhar.")
    if s["ram_gb"] is not None and s["ram_gb"] < 32:
        s["avisos"].append(f"O PC tem {s['ram_gb']} GB de RAM. As imagens funcionam; os pacotes de vídeo pedem 32 GB.")
    if s["livre"] is not None and s["livre"] < 30 * 2**30:
        s["avisos"].append(f"Há só {pacotes.gb(s['livre'])} livres neste disco. A instalação com o pacote inicial ocupa uns 25 GB.")
    return s


def variante(sistema: dict) -> str:
    """O torch com CUDA 13 do portatil padrao pede placa RTX 20 ou mais nova (compute capability 7.5); as mais velhas usam o de CUDA 12.6."""
    return "nvidia" if (sistema.get("cc") or 0) >= 7.5 else "nvidia_cu126"


# ---------- instalacao ----------

def _marca(caminho: Path) -> str:
    try:
        return caminho.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _baixar_zip(url: str, pasta_tmp: Path, parar) -> Path:
    """Zip do GitHub (codigo de um repositorio num commit). Sem tamanho conhecido: baixa inteiro, numa pasta temporaria."""
    destino = pasta_tmp / "codigo.zip"
    pedido = urllib.request.Request(url, headers={"User-Agent": pacotes.AGENTE})
    for tentativa in range(3):
        try:
            with urllib.request.urlopen(pedido, timeout=60) as r, destino.open("wb") as f:
                while bloco := r.read(2**20):
                    if parar.is_set():
                        raise pacotes.Cancelado()
                    f.write(bloco)
            return destino
        except (OSError, urllib.error.URLError) as e:
            if tentativa == 2:
                raise Erro(f"Não consegui baixar {url} ({type(e).__name__}). Confira a internet e clique em Tentar de novo.")
            time.sleep(3)
    return destino


def _extrair_zip_de_repositorio(arq: Path, destino: Path):
    """O zip do GitHub tem uma pasta de topo (repo-commit/): o conteudo dela vai direto para `destino`, por cima do que ja houver.

    Direto, sem extrair a pasta de topo numa pasta temporaria: o nome dela tem o commit inteiro (40 caracteres) e,
    com o estudio numa pasta funda (Downloads\\...-main\\...-main\\), o caminho passava dos 260 caracteres do Windows."""
    destino = destino.resolve()
    with zipfile.ZipFile(arq) as z:
        membros = z.infolist()
        topos = {m.filename.split("/", 1)[0] for m in membros}
        if len(topos) != 1 or not all(m.filename.startswith(next(iter(topos)) + "/") for m in membros):
            raise Erro("O zip baixado não tem o formato esperado.")
        prefixo = topos.pop() + "/"
        alvos = []
        for m in membros:
            rel = m.filename[len(prefixo):]
            if not rel:
                continue
            alvo = (destino / rel).resolve()
            if not alvo.is_relative_to(destino):
                raise Erro("O arquivo baixado tem um caminho estranho e foi recusado.")
            alvos.append((m, alvo))
        for m, alvo in alvos:
            if m.is_dir():
                alvo.mkdir(parents=True, exist_ok=True)
                continue
            alvo.parent.mkdir(parents=True, exist_ok=True)
            with z.open(m) as origem, alvo.open("wb") as saida:
                shutil.copyfileobj(origem, saida)


class Instalador:
    def __init__(self):
        self.trava = threading.Lock()
        self.parar = threading.Event()
        self.passos = [{"id": i, "titulo": t, "situacao": "espera", "detalhe": "", "progresso": None, "segundos": None} for i, t in PASSOS]
        self.fio = None
        self.sistema = ler_sistema()
        self.baixador = pacotes.Baixador(ao_terminar=self._modelos_terminaram)
        self.estudio_aberto = False
        self.ultimo_contato = time.monotonic()
        self._marcar_feitos()

    # estado -------------------------------------------------------------
    def _passo(self, i):
        return next(p for p in self.passos if p["id"] == i)

    def _atualizar(self, i, **kw):
        with self.trava:
            self._passo(i).update(kw)

    def _marcar_feitos(self):
        """Ao abrir, os passos ja feitos (de uma vez anterior) aparecem prontos."""
        raiz = raiz_comfy()
        if self.sistema["placa"]:
            self._atualizar("placa", situacao="feito", detalhe=self._texto_sistema())
        if comfy_de_fora() or _marca(raiz / ".estudio_comfy") == COMMIT_NUCLEO:
            self._atualizar("comfy", situacao="feito", detalhe=f"Já instalado em {raiz}")
        if not self._nos_faltando():
            self._atualizar("nos", situacao="feito", detalhe="Já instalados")
        if comfy_de_fora() or _marca(raiz / ".estudio_deps") == self._hash_requisitos():
            self._atualizar("dependencias", situacao="feito", detalhe="Já instaladas")
        if self._atalho().exists():
            self._atualizar("atalho", situacao="feito", detalhe="Já criados")

    def _modelos_terminaram(self):
        e = self.baixador.resumo() or {}
        detalhe = f": {e['erro']}" if e.get("erro") else ""
        registrar(f"modelos: {e.get('situacao')} ({', '.join(e.get('pacotes', []))}, {pacotes.gb(e.get('feito', 0))} de {pacotes.gb(e.get('total', 0))}){detalhe}")

    def _texto_sistema(self):
        s = self.sistema
        partes = [f"{s['placa']}, {s['vram_gb']:g} GB" if s["placa"] else "sem placa NVIDIA"]
        if s["ram_gb"]:
            partes.append(f"{s['ram_gb']} GB de RAM")
        if s["livre"] is not None:
            partes.append(f"{pacotes.gb(s['livre'])} livres no disco")
        return " · ".join(partes)

    def rodando(self) -> bool:
        return bool(self.fio and self.fio.is_alive())

    def pronto(self) -> bool:
        return all(p["situacao"] == "feito" for p in self.passos)

    def resumo(self) -> dict:
        try:
            self.sistema["livre"] = pacotes.livre(REPO)  # muda a cada download: o teste mostrou o numero do comeco
        except OSError:
            pass
        with self.trava:
            passos = [dict(p) for p in self.passos]
        try:
            lista = pacotes.situacao(models=pasta_models())
        except Exception as e:
            registrar(f"erro lendo os pacotes: {e}")
            lista = []
        return {"sistema": self.sistema, "passos": passos, "rodando": self.rodando(), "pronto": self.pronto(), "pacotes": lista,
                "baixando": self.baixador.resumo(), "baixando_agora": self.baixador.ocupado(),
                "estudio": {"aberto": self.estudio_aberto, "no_ar": self.pronto() and estudio_no_ar(), "url": f"http://127.0.0.1:{config.PORTA}/"},
                "log": ultimas_linhas()}

    # passos -------------------------------------------------------------
    def iniciar(self, ids: list):
        if ids:
            if self.baixador.ocupado():
                raise Erro("Já há modelos baixando. Espere terminar ou cancele.", 409)
            self.baixador.iniciar(ids, models=pasta_models())
            registrar(f"modelos: começou {', '.join(ids)}")
        if not self.rodando() and not self.pronto():
            self.parar.clear()
            self.fio = threading.Thread(target=self._correr, name="instalar", daemon=True)
            self.fio.start()

    def _correr(self):
        registrar("instalação: começou")
        for i, _t in PASSOS:
            if self._passo(i)["situacao"] == "feito":
                continue
            inicio = time.monotonic()
            self._atualizar(i, situacao="rodando", detalhe="", progresso=None)
            registrar(f"passo {i}: começou")
            try:
                getattr(self, f"_passo_{i}")()
            except pacotes.Cancelado:
                self._atualizar(i, situacao="espera", detalhe="Parado")
                registrar(f"passo {i}: parado")
                return
            except Erro as e:
                self._atualizar(i, situacao="erro", detalhe=e.mensagem, segundos=round(time.monotonic() - inicio))
                registrar(f"passo {i}: erro: {e.mensagem}")
                return
            except Exception as e:
                msg = f"Falha inesperada: {type(e).__name__}: {str(e)[:300]}. Veja logs\\instalacao.log."
                self._atualizar(i, situacao="erro", detalhe=msg, segundos=round(time.monotonic() - inicio))
                registrar(f"passo {i}: erro inesperado\n{traceback.format_exc()}")
                return
            segundos = round(time.monotonic() - inicio)
            self._atualizar(i, situacao="feito", progresso=None, segundos=segundos)
            registrar(f"passo {i}: terminou em {segundos} s")
        registrar("instalação: terminou")

    def _passo_placa(self):
        self.sistema = ler_sistema()
        if self.sistema["erro"]:
            raise Erro(self.sistema["erro"])
        self._atualizar("placa", detalhe=self._texto_sistema())

    def _passo_comfy(self):
        raiz = raiz_comfy()
        var = variante(self.sistema)
        tamanho, sha = PORTATEIS[var]
        arq = BAIXADOS / f"ComfyUI_windows_portable_{var}_{VERSAO_PORTATIL}.7z"
        if not arq.is_file():
            parte = arq.with_name(arq.name + pacotes.SUFIXO)
            feito = [parte.stat().st_size if parte.exists() else 0]

            def somar(n):
                feito[0] += n
                self._atualizar("comfy", progresso=feito[0] / tamanho,
                                detalhe=f"Baixando o ComfyUI portátil: {pacotes.gb(feito[0])} de {pacotes.gb(tamanho)}")
            somar(0)
            item = {"url": URL_PORTATIL.format(versao=VERSAO_PORTATIL, variante=var), "tamanho": tamanho, "sha256": sha}
            pacotes.baixar_arquivo(item, None, somar, self.parar, final=arq)
        self._atualizar("comfy", progresso=None, detalhe="Extraindo o ComfyUI (1 a 3 minutos)")
        raiz.parent.mkdir(parents=True, exist_ok=True)
        r = subprocess.run([str(TAR), "-xf", str(arq), "-C", str(raiz.parent)], capture_output=True, text=True, creationflags=SEM_JANELA)
        if r.returncode != 0 or not (raiz / "python_embeded" / "python.exe").is_file():
            registrar(f"tar falhou ({r.returncode}): {r.stderr[-2000:]}")
            raise Erro("Não consegui extrair o ComfyUI. Se o disco estiver cheio, libere espaço e clique em Tentar de novo.")
        self._atualizar("comfy", detalhe="Pondo o ComfyUI na versão testada")
        with tempfile.TemporaryDirectory(dir=BAIXADOS) as tmp:
            z = _baixar_zip(URL_NUCLEO.format(commit=COMMIT_NUCLEO), Path(tmp), self.parar)
            _extrair_zip_de_repositorio(z, raiz / "ComfyUI")
        (raiz / ".estudio_comfy").write_text(COMMIT_NUCLEO, encoding="utf-8")
        arq.unlink(missing_ok=True)  # 2 GB que nao servem mais
        self._atualizar("comfy", detalhe=f"Instalado em {raiz}")

    def _lista_nos(self) -> list:
        return json.loads((AQUI / "nos.json").read_text(encoding="utf-8"))["nos"]

    def _nos_faltando(self) -> list:
        pasta = raiz_comfy() / "ComfyUI" / "custom_nodes"
        # Um no ja instalado de outro jeito (git, Manager) fica como esta: nao se mexe no que o usuario pos
        return [n for n in self._lista_nos() if not (pasta / n["pasta"]).is_dir()]

    def _passo_nos(self):
        pasta = raiz_comfy() / "ComfyUI" / "custom_nodes"
        faltam = self._nos_faltando()
        for k, n in enumerate(faltam, 1):
            if self.parar.is_set():
                raise pacotes.Cancelado()
            self._atualizar("nos", progresso=(k - 1) / len(faltam), detalhe=f"{n['pasta']} ({k} de {len(faltam)})")
            with tempfile.TemporaryDirectory(dir=BAIXADOS) as tmp:
                z = _baixar_zip(f"{n['repo']}/archive/{n['commit']}.zip", Path(tmp), self.parar)
                temporario = Path(tmp) / "no"
                _extrair_zip_de_repositorio(z, temporario)
                (temporario / ".estudio_commit").write_text(n["commit"], encoding="utf-8")
                shutil.move(str(temporario), str(pasta / n["pasta"]))
            registrar(f"nó {n['pasta']} @ {n['commit'][:10]}")
        self._atualizar("nos", progresso=None, detalhe=f"{len(self._lista_nos())} complementos instalados")

    def _hash_requisitos(self) -> str:
        h = hashlib.sha256()
        for f in (raiz_comfy() / "ComfyUI" / "requirements.txt", AQUI / "requisitos_estudio.txt"):
            try:
                h.update(f.read_bytes())
            except OSError:
                h.update(b"-")
        return h.hexdigest()

    def _pip(self, raiz: Path, args: list, etapa: str):
        cmd = [str(raiz / "python_embeded" / "python.exe"), "-s", "-m", "pip", *args]
        registrar("pip: " + " ".join(cmd))
        ambiente = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
        p = subprocess.Popen(cmd, cwd=str(raiz), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True,
                             encoding="utf-8", errors="replace", env=ambiente, creationflags=SEM_JANELA)
        saida = []
        with LOG.open("a", encoding="utf-8") as log:
            for linha in p.stdout:
                log.write("    " + linha)
                log.flush()
                saida.append(linha)
                linha = linha.strip()
                if linha.startswith("Collecting "):
                    self._atualizar("dependencias", detalhe=f"{etapa}: baixando {linha.split()[1].split('==')[0][:60]}")
                elif linha.startswith("Installing collected"):
                    self._atualizar("dependencias", detalhe=f"{etapa}: instalando")
                if self.parar.is_set():
                    p.kill()
                    raise pacotes.Cancelado()
        if p.wait() != 0:
            raise Erro("A instalação das dependências falhou. As últimas linhas de logs\\instalacao.log dizem o motivo; clique em Tentar de novo.")
        return "".join(saida)

    def _passo_dependencias(self):
        """Duas rodadas: o requirements.txt do ComfyUI (a versao testada pode pedir uma interface mais nova que a do portatil) e
        depois os pacotes dos nos, com tudo o que ja esta instalado congelado como restricao: nada da base muda de versao."""
        raiz = raiz_comfy()
        comum = ["install", "--no-warn-script-location", "--disable-pip-version-check", "--progress-bar", "off"]
        self._pip(raiz, [*comum, "-r", str(raiz / "ComfyUI" / "requirements.txt")], "Pacotes do ComfyUI")
        base = self._pip(raiz, ["list", "--format=freeze", "--disable-pip-version-check"], "Conferindo")
        restricoes = BAIXADOS / "restricoes_base.txt"
        restricoes.write_text("".join(l for l in base.splitlines(keepends=True) if "==" in l and not l.lower().startswith("pip==")), encoding="utf-8")
        self._pip(raiz, [*comum, "-r", str(AQUI / "requisitos_estudio.txt"), "-c", str(restricoes)], "Pacotes dos complementos")
        (raiz / ".estudio_deps").write_text(self._hash_requisitos(), encoding="utf-8")
        self._atualizar("dependencias", detalhe="Instaladas")

    def _atalho(self) -> Path:
        if not hasattr(self, "_desktop"):
            try:
                r = subprocess.run(["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"], capture_output=True, text=True,
                                   timeout=30, creationflags=SEM_JANELA)
                self._desktop = Path(r.stdout.strip()) if r.stdout.strip() else Path.home() / "Desktop"
            except Exception:
                self._desktop = Path.home() / "Desktop"
        return self._desktop / "Estúdio de vídeo.lnk"

    def _passo_atalho(self):
        raiz = raiz_comfy()
        # O atalho do estudio leva o icone proprio (o padrao seria o do Python); o de baixar modelos fica com o do .bat, para diferenciar
        icone = REPO / "estudio" / "pagina" / "icone.ico"
        atalhos = [(self._atalho(), raiz / "python_embeded" / "pythonw.exe", f'-I "{REPO / "estudio" / "estudio.pyw"}"', REPO / "estudio",
                    "Abre o Estúdio de vídeo", str(icone) if icone.is_file() else ""),
                   (self._atalho().with_name("Estúdio de vídeo - baixar modelos.lnk"), REPO / "Instalar estudio.bat", "", REPO,
                    "Baixa mais pacotes de modelos para o Estúdio de vídeo", "")]
        script = ("$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:E_LNK); $s.TargetPath = $env:E_ALVO; $s.Arguments = $env:E_ARGS; "
                  "$s.WorkingDirectory = $env:E_PASTA; $s.Description = $env:E_DESC; if ($env:E_ICONE) { $s.IconLocation = $env:E_ICONE + ',0' }; $s.Save()")
        for lnk, alvo, args, pasta, descricao, icone_lnk in atalhos:
            r = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True, timeout=60, creationflags=SEM_JANELA,
                               env={**os.environ, "E_LNK": str(lnk), "E_ALVO": str(alvo), "E_ARGS": args, "E_PASTA": str(pasta), "E_DESC": descricao,
                                    "E_ICONE": icone_lnk})
            if r.returncode != 0:
                registrar(f"atalho falhou: {r.stderr[-1000:]}")
                raise Erro("Não consegui criar o atalho na área de trabalho. O estúdio funciona assim mesmo: abra pelo botão abaixo.")
        self._atualizar("atalho", detalhe="Estúdio de vídeo e Estúdio de vídeo - baixar modelos")

    def abrir_estudio(self):
        if not self.pronto():
            raise Erro("Termine a instalação antes de abrir o estúdio.")
        if not estudio_no_ar():
            raiz = raiz_comfy()
            subprocess.Popen([str(raiz / "python_embeded" / "pythonw.exe"), "-I", str(REPO / "estudio" / "estudio.pyw")], cwd=str(REPO / "estudio"),
                             creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP, close_fds=True)
            registrar("estúdio: aberto pelo instalador")
        else:
            webbrowser.open(f"http://127.0.0.1:{config.PORTA}/")
        self.estudio_aberto = True


_no_ar = {"quando": 0.0, "valor": False}


def estudio_no_ar() -> bool:
    """O estudio responde? Guardado por 3 s: a pagina pergunta a cada segundo."""
    if time.monotonic() - _no_ar["quando"] > 3:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{config.PORTA}/api/estado", timeout=1) as r:
                _no_ar["valor"] = r.status == 200 and "tarefa" in json.load(r)
        except Exception:
            _no_ar["valor"] = False
        _no_ar["quando"] = time.monotonic()
    return _no_ar["valor"]


# ---------- servidor ----------

class Pagina(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def origem_valida(self):
        """Impede que um site aberto no navegador acione o instalador."""
        porta = self.server.server_address[1]
        validos = {f"127.0.0.1:{porta}", f"localhost:{porta}"}
        if self.headers.get("Host") not in validos:
            return False
        origem = self.headers.get("Origin")
        return not origem or urllib.parse.urlparse(origem).netloc in validos

    def responder(self, dados, codigo=200, tipo="application/json; charset=utf-8"):
        corpo = dados if isinstance(dados, bytes) else json.dumps(dados, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(corpo)
        except (ConnectionError, OSError):
            pass  # o navegador fechou ou recarregou a aba no meio da resposta

    def do_GET(self):
        if not self.origem_valida():
            return self.responder({"erro": "Origem recusada."}, 403)
        inst = self.server.instalador
        inst.ultimo_contato = time.monotonic()
        if self.path == "/":
            return self.responder((AQUI / "pagina.html").read_bytes(), tipo="text/html; charset=utf-8")
        if self.path == "/api/estado":
            return self.responder(inst.resumo())
        self.responder({"erro": "Endereço não encontrado."}, 404)

    def do_POST(self):
        if not self.origem_valida():
            return self.responder({"erro": "Origem recusada."}, 403)
        inst = self.server.instalador
        inst.ultimo_contato = time.monotonic()
        try:
            n = int(self.headers.get("Content-Length") or 0)
            dados = json.loads(self.rfile.read(n) or b"{}") if 0 <= n <= 10000 else {}
            if self.path == "/api/instalar":
                ids = dados.get("pacotes") or []
                if not isinstance(ids, list) or not all(isinstance(x, str) for x in ids):
                    raise Erro("Pedido inválido.")
                inst.iniciar(ids)
            elif self.path == "/api/cancelar":
                inst.baixador.cancelar()
            elif self.path == "/api/abrir-estudio":
                inst.abrir_estudio()
            elif self.path == "/api/fechar":
                if inst.baixador.ocupado() or inst.rodando():
                    raise Erro("Ainda há coisas rodando. Espere terminar ou cancele antes de fechar.")
                self.responder({"ok": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            else:
                raise Erro("Endereço não encontrado.", 404)
            self.responder(inst.resumo())
        except Erro as e:
            self.responder({"erro": e.mensagem}, e.codigo)
        except (ValueError, TypeError):
            self.responder({"erro": "Pedido inválido."}, 400)


def vigiar_ocioso(servidor):
    """Quem fechou a aba sem fechar o instalador: depois de 15 min sem a pagina e sem nada rodando, sai sozinho."""
    inst = servidor.instalador
    while True:
        time.sleep(30)
        if not inst.rodando() and not inst.baixador.ocupado() and time.monotonic() - inst.ultimo_contato > OCIOSO_MAX:
            registrar("instalador: fechou por ficar parado")
            servidor.shutdown()
            return


def instalador_ja_aberto(porta: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{porta}/api/estado", timeout=2) as r:
            return "passos" in json.load(r)
    except Exception:
        return False


def abrir_servidor():
    """A 8191, ou a proxima livre: outro programa pode estar nela (nesta maquina, o vigia da placa a segura).
    Se o proprio instalador ja estiver aberto numa delas, devolve so a porta para mostrar a pagina."""
    for porta in [*PORTAS, 0]:
        if porta and instalador_ja_aberto(porta):
            return None, porta
        try:
            return ThreadingHTTPServer(("127.0.0.1", porta), Pagina), None
        except OSError:
            continue
    raise OSError("nenhuma porta livre")


def principal():
    if sys.stdout is None or sys.stderr is None:  # pythonw: sem console, tudo vai para o log
        LOG.parent.mkdir(parents=True, exist_ok=True)
        sys.stdout = sys.stderr = open(LOG, "a", encoding="utf-8", buffering=1)
    BAIXADOS.mkdir(parents=True, exist_ok=True)
    try:
        servidor, aberto = abrir_servidor()
    except OSError as e:
        registrar(f"instalador: não consegui abrir a página ({e})")
        return
    porta = aberto or servidor.server_address[1]
    url = f"http://127.0.0.1:{porta}/"
    ENDERECO.write_text(url, encoding="utf-8")
    if servidor is None:
        webbrowser.open(url)  # ja aberto: so mostra a pagina
        return
    registrar(f"instalador: aberto em {url} (repositório {REPO})")
    servidor.instalador = Instalador()
    threading.Thread(target=vigiar_ocioso, args=(servidor,), daemon=True).start()
    if "--sem-navegador" not in sys.argv:
        webbrowser.open(url)
    try:
        servidor.serve_forever()
    finally:
        servidor.server_close()


if __name__ == "__main__":
    principal()
