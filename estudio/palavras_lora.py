"""Palavras-chave de cada LoRA instalada: o que o usuário editou na página e o que a ficha do Civitai diz.

Fica em palavras_loras.json, na pasta do repositório e fora do git, com uma entrada por nome de arquivo (minúsculas):
  {"tamanho", "mtime", "sha256",                              o arquivo consultado; se mudar, consulta de novo
   "ficha": {"estado": "achou" | "nao_achou" | "erro", "palavras": [...], "modelo", "versao", "pagina", "em"},
   "meu":   {"modo": "fixa" | "aviso" | "nenhuma", "palavras": [...], "nota": ""}}     só quando o usuário editou

Quem vale para uma LoRA, nesta ordem (loras.gatilho_de):
  1. o que o usuário salvou na página ("meu");
  2. o cadastro do estúdio (loras.GATILHOS e a seção gatilhos do arquivo local);
  3. as palavras de treino da ficha do Civitai, só como aviso: a ficha não diz se a palavra é fixa ou se depende da cena.

A consulta manda ao Civitai só o SHA256 do arquivo. Roda em segundo plano (`vigiar`), uma LoRA por vez, e não roda
enquanto uma geração está em andamento, para não disputar o disco."""
import hashlib, json, re, subprocess, threading, time, urllib.error, urllib.request
from pathlib import Path

import caminhos, config

ARQUIVO = "palavras_loras.json"
MODOS = ("fixa", "aviso", "nenhuma")
MAX_PALAVRAS, MAX_LETRAS, MAX_NOTA = 12, 200, 300
NOTA_FICHA = "Palavras de treino da ficha no Civitai. Confira e, se for uma palavra fixa, mude para entrar sozinha."
# LoRAs que o estúdio usa por conta própria (aceleração, troca, nitidez, folha de vistas): não entram na tela nem na consulta
TECNICA = re.compile(r"turbo|dmd|dmad|lightning|lightx2v|distill|\d+steps?|_lms_|upscal|character_swap|head_swap|bfs_head|five_view|turnaround|scail|rife|open_regenerate", re.I)
LIGADO = True   # os testes desligam (rodar_testes.py): nada de calcular hash nem de ir à internet
_trava = threading.RLock()
_dados = None
_com_erro = set()
_fio = None


class Erro(ValueError):
    pass


def _arquivo() -> Path:
    return config.WORKFLOWS / ARQUIVO


def ler() -> dict:
    global _dados
    with _trava:
        if _dados is None:
            try:
                d = json.loads(_arquivo().read_text(encoding="utf-8"))
            except (OSError, ValueError):
                d = {}
            _dados = d if isinstance(d, dict) and isinstance(d.get("arquivos"), dict) else {"arquivos": {}}
        return _dados


def _gravar():
    caminhos.gravar_json(_arquivo(), ler())


def tecnica(nome: str) -> bool:
    return bool(TECNICA.search(nome))


def _modo_e_palavras(g: dict) -> tuple:
    """Entrada no formato de loras.GATILHOS -> (modo, palavras)."""
    if isinstance(g.get("palavra"), str) and g["palavra"].strip():
        return "fixa", [g["palavra"].strip()]
    return "aviso", [str(f) for f in g.get("frases") or []]


def do_arquivo(nome: str):
    """O que este módulo sabe da LoRA `nome` (só o nome do arquivo), no formato de loras.GATILHOS:
    ("meu", entrada ou None) se o usuário editou (None: ele marcou que não usa palavra-chave);
    ("ficha", entrada) se só há as palavras da ficha; None se não há nada."""
    e = ler()["arquivos"].get(nome.lower())
    if not isinstance(e, dict):
        return None
    ficha = e.get("ficha") if isinstance(e.get("ficha"), dict) else {}
    meu = e.get("meu")
    if isinstance(meu, dict) and meu.get("modo") in MODOS:
        palavras = [p for p in meu.get("palavras") or [] if isinstance(p, str) and p.strip()]
        if meu["modo"] == "nenhuma" or not palavras:
            return "meu", None
        g = {"palavra": ", ".join(palavras)} if meu["modo"] == "fixa" else {"frases": palavras}
        if meu.get("nota"):
            g["nota"] = meu["nota"]
        if ficha.get("pagina"):
            g["pagina"] = ficha["pagina"]
        return "meu", g
    if ficha.get("estado") == "achou" and ficha.get("palavras"):
        return "ficha", {"frases": list(ficha["palavras"]), "nota": NOTA_FICHA, "pagina": ficha.get("pagina", "")}
    return None


def listar() -> list:
    """As LoRAs instaladas (menos as técnicas) com a palavra-chave que vale para cada uma e de onde ela veio."""
    import loras
    cadastro, arquivos, lista = loras.gatilhos(), ler()["arquivos"], []
    for chave, rel in sorted(loras.mapa().items(), key=lambda x: x[1].lower()):
        nome = loras.nome(rel)
        if tecnica(nome):
            continue
        rel = rel.replace("\\", "/")
        e = arquivos.get(chave) if isinstance(arquivos.get(chave), dict) else {}
        ficha = e.get("ficha") if isinstance(e.get("ficha"), dict) else {}
        daqui = do_arquivo(nome)
        do_estudio = loras.gatilho_do_cadastro(nome, cadastro)
        if daqui and daqui[0] == "meu":
            origem, g = "meu", daqui[1]
        elif do_estudio:
            origem, g = "estudio", do_estudio
        elif daqui:
            origem, g = "ficha", daqui[1]
        else:
            origem, g = "nenhuma", None
        modo, palavras = _modo_e_palavras(g) if g else ("nenhuma", [])
        if origem == "meu":
            # Na tela de edição as palavras voltam separadas, como foram salvas
            modo, palavras = e["meu"]["modo"], [p for p in e["meu"].get("palavras") or [] if isinstance(p, str)]
        nota = e["meu"].get("nota", "") if origem == "meu" else g.get("nota", "") if origem == "estudio" else ""
        lista.append({"nome": nome, "pasta": rel.rsplit("/", 1)[0] if "/" in rel else "", "origem": origem, "modo": modo, "palavras": palavras, "nota": nota,
                      "opcional": bool((g or {}).get("opcional")), "pagina": (g or {}).get("pagina") or ficha.get("pagina", ""),
                      "ficha": {"estado": "erro" if chave in _com_erro and not ficha else ficha.get("estado", "pendente"), "palavras": ficha.get("palavras") or [],
                                "modelo": ficha.get("modelo", ""), "versao": ficha.get("versao", "")}})
    return lista


def _limpar_palavras(palavras) -> list:
    if not isinstance(palavras, list):
        raise Erro("As palavras-chave não vieram numa lista.")
    limpas = []
    for p in palavras:
        p = re.sub(r"\s+", " ", str(p)).strip().strip(",").strip()
        if p and p.lower() not in [x.lower() for x in limpas]:
            limpas.append(p)
    if len(limpas) > MAX_PALAVRAS:
        raise Erro(f"Use até {MAX_PALAVRAS} palavras-chave por LoRA.")
    if any(len(p) > MAX_LETRAS for p in limpas):
        raise Erro(f"Cada palavra-chave pode ter até {MAX_LETRAS} letras.")
    return limpas


def _instalada(nome) -> str:
    import loras
    chave = loras.nome(str(nome or "")).lower()
    if not chave or chave not in loras.mapa():
        raise Erro("Esta LoRA não está mais na pasta loras.")
    return chave


def salvar(nome, modo, palavras, nota="") -> None:
    """O que o usuário escolheu na página para a LoRA `nome`. Passa a valer no lugar do cadastro do estúdio e da ficha."""
    chave = _instalada(nome)
    if modo not in MODOS:
        raise Erro("Escolha como a palavra-chave entra no texto.")
    limpas = [] if modo == "nenhuma" else _limpar_palavras(palavras)
    if modo != "nenhuma" and not limpas:
        raise Erro("Escreva pelo menos uma palavra-chave, ou escolha \"Não usar palavra-chave\".")
    with _trava:
        e = ler()["arquivos"].setdefault(chave, {})
        e["meu"] = {"modo": modo, "palavras": limpas, "nota": re.sub(r"\s+", " ", str(nota or "")).strip()[:MAX_NOTA]}
        _gravar()


def restaurar(nome) -> None:
    """Apaga o que o usuário editou: volta a valer o cadastro do estúdio ou a ficha."""
    chave = _instalada(nome)
    with _trava:
        e = ler()["arquivos"].get(chave)
        if isinstance(e, dict) and e.pop("meu", None) is not None:
            _gravar()


# ---------- Consulta à ficha do Civitai ----------

def _baixar(url: str):
    """(código HTTP, corpo). Com o curl do Windows: o urllib do Python embutido recusa o certificado do Civitai nesta
    máquina (certificado raiz vencido no pacote dele, 20/11/2026). Sem o curl, tenta o urllib."""
    try:
        r = subprocess.run(["curl.exe", "-s", "-m", "40", "-A", "Mozilla/5.0", "-w", "\n%{http_code}", url], capture_output=True, timeout=60,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        corpo, _, codigo = r.stdout.decode("utf-8", "replace").rpartition("\n")
        if codigo.strip().isdigit() and int(codigo) > 0:
            return int(codigo), corpo
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=40) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""


def sha256(arq: Path) -> str:
    h = hashlib.sha256()
    with open(arq, "rb") as f:
        while bloco := f.read(8 << 20):
            h.update(bloco)
    return h.hexdigest().upper()


def ficha_do_civitai(sha: str, baixar=None) -> dict:
    """A ficha da versão do modelo com este SHA256. `estado`: achou, nao_achou (não está no Civitai) ou erro (rede)."""
    agora = time.strftime("%Y-%m-%d %H:%M")
    try:
        codigo, corpo = (baixar or _baixar)(f"https://civitai.com/api/v1/model-versions/by-hash/{sha}")
    except Exception as e:
        return {"estado": "erro", "erro": repr(e)[:200], "em": agora}
    if codigo == 404:
        return {"estado": "nao_achou", "em": agora}
    try:
        d = json.loads(corpo) if codigo == 200 else None
    except ValueError:
        d = None
    if not isinstance(d, dict):
        return {"estado": "erro", "erro": f"HTTP {codigo}", "em": agora}
    palavras = []
    for p in d.get("trainedWords") or []:
        p = re.sub(r"\s+", " ", str(p)).strip().strip(",").strip()
        # Algumas fichas guardam um prompt inteiro de exemplo no lugar da palavra: isso não é palavra-chave
        if p and len(p) <= MAX_LETRAS and p not in palavras:
            palavras.append(p)
    modelo = d.get("model") if isinstance(d.get("model"), dict) else {}
    return {"estado": "achou", "palavras": palavras[:MAX_PALAVRAS], "modelo": str(modelo.get("name") or "")[:200], "versao": str(d.get("name") or "")[:100],
            "pagina": f"https://civitai.com/models/{d['modelId']}" if str(d.get("modelId", "")).isdigit() else "", "em": agora}


def consultar(nome, baixar=None, forcar=True) -> dict:
    """Calcula o SHA256 da LoRA (só se o arquivo mudou) e busca a ficha. Devolve a ficha guardada."""
    import loras
    chave = _instalada(nome)
    arq = loras.pasta() / loras.mapa()[chave]
    st = arq.stat()
    with _trava:
        e = dict(ler()["arquivos"].get(chave) or {})
    mesmo = e.get("tamanho") == st.st_size and e.get("mtime") == int(st.st_mtime) and e.get("sha256")
    if mesmo and not forcar and isinstance(e.get("ficha"), dict) and e["ficha"].get("estado") != "erro":
        return e["ficha"]
    sha = e["sha256"] if mesmo else sha256(arq)
    ficha = ficha_do_civitai(sha, baixar)
    with _trava:
        atual = ler()["arquivos"].setdefault(chave, {})
        atual.update(tamanho=st.st_size, mtime=int(st.st_mtime), sha256=sha, ficha=ficha)
        _gravar()
    _com_erro.discard(chave)
    return ficha


def pendentes() -> list:
    """As LoRAs instaladas (menos as técnicas) que ainda não têm ficha, ou cujo arquivo mudou desde a consulta.
    A que deu erro de rede não volta sozinha nesta sessão do estúdio: tenta de novo ao religar ou pelo botão da tela."""
    import loras
    arquivos, lista = ler()["arquivos"], []
    for chave, rel in loras.mapa().items():
        if tecnica(chave) or chave in _com_erro:
            continue
        e = arquivos.get(chave) if isinstance(arquivos.get(chave), dict) else {}
        try:
            st = (loras.pasta() / rel).stat()
        except OSError:
            continue
        ficha = e.get("ficha") if isinstance(e.get("ficha"), dict) else None
        if not ficha or ficha.get("estado") == "erro" or e.get("tamanho") != st.st_size or e.get("mtime") != int(st.st_mtime):
            lista.append(chave)
    return sorted(lista)


def vigiar(ocupado=lambda: False, intervalo=60, parar=None):
    """Liga o fio que consulta, uma por vez, as LoRAs sem ficha. Uma LoRA nova na pasta é vista na volta seguinte."""
    global _fio
    parar = parar or threading.Event()
    if not LIGADO:
        return parar

    def laco():
        while not parar.wait(5):
            try:
                for chave in pendentes():
                    if parar.is_set() or ocupado():
                        break
                    try:
                        if consultar(chave, forcar=False).get("estado") == "erro":
                            _com_erro.add(chave)
                    except (Erro, OSError):
                        _com_erro.add(chave)
            except Exception:
                pass   # a consulta é um extra: nunca derruba o estúdio
            parar.wait(intervalo)

    _fio = threading.Thread(target=laco, daemon=True, name="palavras-lora")
    _fio.start()
    return parar
