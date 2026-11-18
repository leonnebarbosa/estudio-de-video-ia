"""Pacotes de modelos para baixar: o que cada aba precisa, de onde vem, e o download em segundo plano.

O catalogo (pacotes.json) da o caminho de cada arquivo dentro de `models`, a URL, o tamanho e o sha256 (o do Hugging Face).
O download vai para <arquivo>.parte, retoma de onde parou e so ganha o nome final depois de conferir tamanho e sha256:
um arquivo com o nome final no disco esta sempre inteiro. O sha256 e calculado durante o download (e sobre o pedaco
ja baixado, ao retomar), sem ler o arquivo de novo no fim.

So usa a biblioteca padrao: roda no Python minimo do instalador (pagina de boas-vindas) e no do ComfyUI.
Linha de comando:
    python -I estudio\\pacotes.py situacao
    python -I estudio\\pacotes.py baixar imagem"""
import hashlib, json, os, shutil, subprocess, sys, threading, time, urllib.error, urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config
from erros import Erro

ARQUIVO = "pacotes.json"
ORIGENS = ("https://huggingface.co/", "https://github.com/")
EXTENSOES = (".safetensors", ".gguf", ".pth", ".ckpt", ".pt", ".bin")
BLOCO = 4 * 2**20
MARGEM = 2 * 2**30          # deixa ao menos 2 GB livres no disco depois de baixar
AGENTE = "estudio-de-video/1.0"
SUFIXO = ".parte"
TENTATIVAS = 4              # a conexao caiu: tenta de novo (retomando) 3 vezes antes de desistir
GIB = 2**30


class Cancelado(Exception):
    pass


def gb(n: int) -> str:
    return f"{n / GIB:.1f}".replace(".", ",") + " GB"


def _conferir(a: dict):
    """Recusa o que nao veio de origem conhecida ou escaparia da pasta models (mesma regra de modelos._validar_caminho)."""
    if not isinstance(a.get("url"), str) or not a["url"].startswith(ORIGENS):
        raise Erro(f"Origem não permitida: {a.get('url')!r}")
    c = a.get("caminho")
    if not isinstance(c, str) or not c or len(c) > 300 or any(x in c for x in ("\0", "\\", ":")) or c.startswith("/"):
        raise Erro(f"Caminho inválido: {c!r}")
    partes = c.split("/")
    if len(partes) < 2 or any(p in ("", ".", "..") or p != p.strip() or p.endswith(".") for p in partes) or not c.lower().endswith(EXTENSOES):
        raise Erro(f"Caminho inválido: {c!r}")
    if not isinstance(a.get("tamanho"), int) or isinstance(a.get("tamanho"), bool) or a["tamanho"] <= 0:
        raise Erro(f"Tamanho inválido em {c}")
    s = a.get("sha256")
    if not isinstance(s, str) or len(s) != 64 or any(ch not in "0123456789abcdef" for ch in s):
        raise Erro(f"sha256 inválido em {c}")


def carregar(arquivo=None) -> list:
    dados = json.loads(Path(arquivo or config.ESTUDIO / ARQUIVO).read_text(encoding="utf-8"))
    pacotes = dados["pacotes"]
    for p in pacotes:
        for a in p["arquivos"]:
            _conferir(a)
    return pacotes


def destino(a: dict, models=None) -> Path:
    return Path(models or config.MODELOS).joinpath(*a["caminho"].split("/"))


def _parte(a: dict, models) -> Path:
    d = destino(a, models)
    return d.with_name(d.name + SUFIXO)


def _nomes_por_tipo(models: Path) -> dict:
    """{"loras": {"x.safetensors", ...}}: o ComfyUI acha o modelo pelo nome em qualquer subpasta do tipo, entao basta o nome."""
    nomes = {}
    try:
        tipos = [e for e in os.scandir(models) if e.is_dir(follow_symlinks=False)]
    except OSError:
        return nomes
    for t in tipos:
        conjunto = nomes.setdefault(t.name, set())
        for _raiz, _pastas, arquivos in os.walk(t.path):
            conjunto.update(f for f in arquivos if not f.endswith(SUFIXO))
    return nomes


def faltando(p: dict, models=None, nomes=None) -> list:
    models = Path(models or config.MODELOS)
    nomes = _nomes_por_tipo(models) if nomes is None else nomes
    return [a for a in p["arquivos"] if a["caminho"].rsplit("/", 1)[-1] not in nomes.get(a["caminho"].split("/")[0], set())]


def _ja_baixado(a: dict, models) -> int:
    try:
        return min(_parte(a, models).stat().st_size, a["tamanho"])
    except OSError:
        return 0


def _unicos(arquivos: list) -> list:
    """Dois pacotes escolhidos juntos podem dividir arquivos (o codificador do H3): cada um entra uma vez so."""
    vistos, lista = set(), []
    for a in arquivos:
        if a["caminho"] not in vistos:
            vistos.add(a["caminho"])
            lista.append(a)
    return lista


def situacao(pacotes=None, models=None) -> list:
    pacotes = carregar() if pacotes is None else pacotes
    models = Path(models or config.MODELOS)
    nomes = _nomes_por_tipo(models)
    lista = []
    for p in pacotes:
        f = faltando(p, models, nomes)
        lista.append({"id": p["id"], "nome": p["nome"], "modelo": p.get("modelo", ""), "descricao": p.get("descricao", ""), "libera": p.get("libera", []),
                      "minimo": p.get("minimo", {}), "inicial": bool(p.get("inicial")), "total": sum(a["tamanho"] for a in p["arquivos"]),
                      "falta": sum(a["tamanho"] - _ja_baixado(a, models) for a in f), "arquivos": len(p["arquivos"]), "faltam": len(f), "pronto": not f})
    return lista


def abas(pacotes=None, models=None) -> dict:
    """{"texto": {"pronto": True}, "novo": {"pronto": False, "pacote": "Continuar...", "falta": bytes}}: as abas que um pacote libera
    (campo "abas" do catalogo) ficam prontas quando algum pacote que as libera esta inteiro. A pagina abre numa aba pronta e avisa nas outras."""
    lista = situacao(pacotes, models)
    r = {}
    for s, p in zip(lista, carregar() if pacotes is None else pacotes):
        for aba in p.get("abas", []):
            atual = r.get(aba)
            if s["pronto"]:
                r[aba] = {"pronto": True}
            elif atual is None or (not atual["pronto"] and s["falta"] < atual["falta"]):
                r[aba] = {"pronto": False, "pacote": s["nome"], "falta": s["falta"]}
    return r


def livre(pasta: Path) -> int:
    pasta = Path(pasta)
    while not pasta.exists() and pasta.parent != pasta:
        pasta = pasta.parent
    return shutil.disk_usage(pasta).free


def baixar_arquivo(a: dict, models, somar=lambda n: None, parar=None, abrir=urllib.request.urlopen, esperar=time.sleep, final=None):
    """Baixa um arquivo do catalogo para o lugar certo em `models` (ou para `final`, como o pacote do ComfyUI no instalador).
    `a` precisa de url, tamanho e sha256. `somar(n)` recebe cada pedaco baixado."""
    parar = parar or threading.Event()
    final = Path(final) if final else destino(a, models)
    parte = final.with_name(final.name + SUFIXO)
    final.parent.mkdir(parents=True, exist_ok=True)
    nome = final.name
    h = hashlib.sha256()
    for tentativa in range(TENTATIVAS):
        ja = parte.stat().st_size if parte.exists() else 0
        if ja > a["tamanho"]:
            parte.unlink()
            ja = 0
        h = hashlib.sha256()
        if ja:
            with parte.open("rb") as f:
                while bloco := f.read(BLOCO):
                    if parar.is_set():
                        raise Cancelado()
                    h.update(bloco)
        if ja == a["tamanho"]:
            break
        try:
            pedido = urllib.request.Request(a["url"], headers={"User-Agent": AGENTE, **({"Range": f"bytes={ja}-"} if ja else {})})
            with abrir(pedido, timeout=60) as r:
                if ja and getattr(r, "status", 200) != 206:
                    # O servidor ignorou o pedaco: comeca do zero e desconta o que ja tinha sido contado
                    somar(-ja)
                    ja, h = 0, hashlib.sha256()
                with parte.open("ab" if ja else "wb") as f:
                    while True:
                        if parar.is_set():
                            raise Cancelado()
                        bloco = r.read(BLOCO)
                        if not bloco:
                            break
                        f.write(bloco)
                        h.update(bloco)
                        somar(len(bloco))
            if parte.stat().st_size >= a["tamanho"]:
                break
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 404, 410):
                raise Erro(f"{nome} não está mais disponível no endereço do catálogo (erro {e.code}). Avise quem mantém o estúdio.")
            if tentativa == TENTATIVAS - 1:
                raise Erro(f"O servidor recusou {nome} (erro {e.code}). Tente de novo mais tarde: continua de onde parou.")
        except (OSError, urllib.error.URLError) as e:
            if tentativa == TENTATIVAS - 1:
                raise Erro(f"A conexão caiu baixando {nome} ({type(e).__name__}). Tente de novo: continua de onde parou.")
        for _ in range(5 * (tentativa + 1)):
            if parar.is_set():
                raise Cancelado()
            esperar(1)
    tamanho = parte.stat().st_size if parte.exists() else 0
    if tamanho != a["tamanho"]:
        if tamanho > a["tamanho"]:
            parte.unlink()
        raise Erro(f"{nome} veio com {tamanho} bytes em vez de {a['tamanho']}. Tente de novo.")
    if h.hexdigest() != a["sha256"]:
        parte.unlink()
        raise Erro(f"{nome} veio corrompido e foi descartado. Tente de novo.")
    os.replace(parte, final)


class Baixador:
    """Baixa pacotes, um arquivo por vez, em segundo plano (`iniciar`) ou direto (`baixar`). A pagina le `resumo()`."""

    def __init__(self, abrir=urllib.request.urlopen, esperar=time.sleep, relogio=time.monotonic, ao_terminar=None):
        self.abrir, self.esperar, self.relogio, self.ao_terminar = abrir, esperar, relogio, ao_terminar
        self.trava = threading.Lock()
        self.parar = threading.Event()
        self.estado = None
        self.fio = None

    def resumo(self):
        with self.trava:
            return dict(self.estado) if self.estado else None

    def ocupado(self) -> bool:
        return bool(self.fio and self.fio.is_alive())

    def preparar(self, ids: list, pacotes=None, models=None):
        """Confere tudo antes de comecar: pacotes existem, falta algo, cabe no disco. Devolve (nomes, arquivos que faltam)."""
        pacotes = carregar() if pacotes is None else pacotes
        models = Path(models or config.MODELOS)
        escolhidos = [p for p in pacotes if p["id"] in ids]
        if not ids or len(escolhidos) != len(set(ids)):
            raise Erro("Pacote desconhecido.")
        nomes = _nomes_por_tipo(models)
        f = _unicos([a for p in escolhidos for a in faltando(p, models, nomes)])
        if not f:
            raise Erro("Esses pacotes já estão baixados.")
        precisa = sum(a["tamanho"] - _ja_baixado(a, models) for a in f)
        tem = livre(models)
        if tem < precisa + MARGEM:
            raise Erro(f"Falta espaço no disco: precisa de {gb(precisa + MARGEM)} livres e há {gb(tem)}. "
                       f"Escolha menos pacotes ou libere espaço e tente de novo.")
        return [p["nome"] for p in escolhidos], f

    def baixar(self, nomes: list, f: list, models=None):
        """Baixa os arquivos que faltam, atualizando o estado. Levanta Erro ou Cancelado."""
        models = Path(models or config.MODELOS)
        feito = sum(_ja_baixado(a, models) for a in f)
        total = sum(a["tamanho"] for a in f)
        with self.trava:
            self.estado = {"pacotes": nomes, "arquivo": "", "indice": 0, "arquivos": len(f), "feito": feito, "total": total,
                           "velocidade": 0, "situacao": "baixando", "erro": None}
        janela = [(self.relogio(), feito)]

        def somar(n):
            agora = self.relogio()
            with self.trava:
                self.estado["feito"] += n
                janela.append((agora, self.estado["feito"]))
                while len(janela) > 2 and agora - janela[0][0] > 10:
                    janela.pop(0)
                dt = agora - janela[0][0]
                if dt > 0.5:
                    self.estado["velocidade"] = max(0, int((self.estado["feito"] - janela[0][1]) / dt))

        for i, a in enumerate(f, 1):
            with self.trava:
                self.estado.update(arquivo=a["caminho"].rsplit("/", 1)[-1], indice=i)
            baixar_arquivo(a, models, somar, self.parar, self.abrir, self.esperar)
        with self.trava:
            self.estado.update(situacao="pronto", feito=total, velocidade=0)

    def iniciar(self, ids: list, pacotes=None, models=None):
        if self.ocupado():
            raise Erro("Já há um download em andamento. Espere terminar ou cancele.", 409)
        nomes, f = self.preparar(ids, pacotes, models)
        self.parar.clear()

        def correr():
            try:
                self.baixar(nomes, f, models)
            except Cancelado:
                with self.trava:
                    self.estado.update(situacao="cancelado", velocidade=0)
            except Erro as e:
                with self.trava:
                    self.estado.update(situacao="erro", erro=e.mensagem, velocidade=0)
            except Exception as e:
                with self.trava:
                    self.estado.update(situacao="erro", erro=f"O download falhou: {type(e).__name__}: {str(e)[:200]}", velocidade=0)
            finally:
                if self.ao_terminar:
                    try:
                        self.ao_terminar()
                    except Exception:
                        pass

        with self.trava:
            self.estado = {"pacotes": nomes, "arquivo": "", "indice": 0, "arquivos": len(f), "feito": 0, "total": sum(a["tamanho"] for a in f),
                           "velocidade": 0, "situacao": "baixando", "erro": None}
            self.fio = threading.Thread(target=correr, name="baixar-pacotes", daemon=True)
            self.fio.start()
        return self.resumo()

    def cancelar(self):
        self.parar.set()


def _linha_cli(e: dict) -> str:
    pct = 100 * e["feito"] / e["total"] if e["total"] else 100
    vel = e["velocidade"]
    resta = f", faltam {int((e['total'] - e['feito']) / vel / 60) + 1} min" if vel > 0 else ""
    return f"\r  [{e['indice']}/{e['arquivos']}] {e['arquivo'][:48]:48}  {pct:5.1f}% de {gb(e['total'])}  {vel / 2**20:6.1f} MB/s{resta}   "


def principal(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if argv[:1] == ["situacao"]:
        for s in situacao():
            print(f"{s['id']:10} {'pronto' if s['pronto'] else 'falta ' + gb(s['falta']):>16}  {s['nome']}")
        return 0
    if len(argv) >= 2 and argv[0] == "baixar":
        b = Baixador()
        try:
            nomes, f = b.preparar(argv[1:])
        except Erro as e:
            print(e.mensagem)
            return 0 if "já estão baixados" in e.mensagem else 1
        print(f"Baixando {', '.join(nomes)}: {len(f)} arquivo(s), {gb(sum(a['tamanho'] - _ja_baixado(a, config.MODELOS) for a in f))}")
        fim = threading.Event()

        def mostrar():
            while not fim.wait(1):
                if b.estado:
                    print(_linha_cli(b.resumo()), end="", flush=True)

        threading.Thread(target=mostrar, daemon=True).start()
        try:
            b.baixar(nomes, f)
        except Erro as e:
            fim.set()
            print(f"\n{e.mensagem}")
            return 1
        except KeyboardInterrupt:
            fim.set()
            print("\nParado. Rode de novo para continuar de onde parou.")
            return 1
        fim.set()
        print(_linha_cli(b.resumo()) + "\nPronto.")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(principal())
