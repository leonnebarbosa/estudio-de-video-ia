"""Le os projetos gravados em disco e diz o que pertence a cada um."""
import json, math, re
from pathlib import Path

import config
from validacao import Erro, FPS, NOVOS, PARAMETROS, QUADROS_RODADA, SOBREPOSICAO, pasta_projeto


def total_rodadas(f0, duracao):
    alvo = round(duracao * FPS)
    return max(1, math.ceil((alvo - (f0 - SOBREPOSICAO + QUADROS_RODADA)) / NOVOS) + 1)


_ultimos = {}


def ler_projeto(pasta):
    try:
        e = json.loads((pasta / "estado.json").read_text(encoding="utf-8"))
        _ultimos[pasta.name] = e
    except Exception:
        # O script pode estar gravando o arquivo neste instante
        e = _ultimos.get(pasta.name)
        if e is None:
            return None
    p = None
    if (pasta / PARAMETROS).exists():
        try:
            p = json.loads((pasta / PARAMETROS).read_text(encoding="utf-8"))
        except Exception:
            p = None
    if e.get("tipo") == "troca":
        return ler_troca(pasta, e, p)
    if e.get("tipo") == "imagem":
        return ler_imagem(pasta, e, p)
    if e.get("tipo") == "texto":
        return ler_texto(pasta, e, p)
    if e.get("tipo") == "wan":
        return ler_wan(pasta, e, p)
    if e.get("tipo") == "editar":
        return ler_editar(pasta, e, p)
    rodadas =[{"n": r.get("rodada"), "pediu": r.get("summary", ""), "viu": r.get("aconteceu", ""), "aprovada": r.get("aprovada"), "tentativa": r.get("tentativa"), "segundos": (r.get("s_video") or 0) + (r.get("s_llm") or 0), "s_video": r.get("s_video"), "s_llm": r.get("s_llm"), "passo": r.get("passo", 0)} for r in e.get("rodadas", [])]
    f0 = e.get("quadros_origem") or 0
    total = total_rodadas(f0, p["duracao"]) if p else len(rodadas)
    final = pasta / "final.mp4"
    plano = e.get("plano") or {}
    return {"nome": pasta.name, "ideia": e.get("ideia", ""), "origem": Path(e.get("origem", "")).name, "personagem": e.get("personagem"), "quadros_origem": f0, "passos": plano.get("beats", []),
            "rodadas": rodadas, "total": total, "pagina": bool(p), "config": p, "completo": len(rodadas) >= total and total > 0,
            "final": {"marca": int(final.stat().st_mtime), "caminho": str(final)} if final.exists() else None, "tem_quadro": ultimo_quadro(pasta.name, len(rodadas)) is not None,
            "quando": (pasta / "estado.json").stat().st_mtime}


def ler_troca(pasta, e, p):
    final, comparativo = pasta / "final.mp4", pasta / "comparativo.mp4"
    marca = lambda arq: {"marca": int(arq.stat().st_mtime), "caminho": str(arq)} if arq.exists() else None
    return {"nome": pasta.name, "tipo": "troca", "ideia": "", "origem": Path(e.get("origem", "")).name, "personagem": e.get("personagem"), "quadros_origem": e.get("quadros_origem") or 0, "passos": [], "rodadas": [], "total": 0,
            "pagina": bool(p), "config": p, "completo": final.exists(), "final": marca(final), "comparativo": marca(comparativo), "prompt": e.get("prompt", ""), "resultado": e.get("resultado"),
            "tem_quadro": False, "foto_existe": bool(e.get("personagem")) and (config.ENTRADA / e["personagem"]).is_file(), "quando": (pasta / "estado.json").stat().st_mtime,
            # Com a roupa do video: a referencia que a troca usou (cabeca da foto com a roupa do primeiro quadro)
            "referencia": e["referencia"] if e.get("referencia") and e["referencia"] != e.get("personagem") and (config.ENTRADA / e["referencia"]).is_file() else None,
            # Troca em janelas com os quadros guardados: cada uma pode ser refeita (Refazer uma janela)
            "janelas": e.get("janelas") if (pasta / "janelas_feitas" / "janelas.json").exists() else None}


def ler_imagem(pasta, e, p):
    final, hd = pasta / "final.mp4", pasta / "final_hd.mp4"
    # O prompt e o texto exato que foi ao modelo, ja montado (camera, olhar, fala, sons): a pagina mostra para conferir
    feitas = [{k: r.get(k) for k in ("n", "segundos", "pico_vram", "temp_max", "semente", "prompt")} for r in e.get("tomadas", [])]
    total = len((p or {}).get("tomadas", []))
    # Um final_hd mais velho que o final.mp4 e de uma versao anterior das tomadas
    hd_valido = hd.exists() and final.exists() and hd.stat().st_mtime >= final.stat().st_mtime
    ideia = ((p or {}).get("avancado") or {}).get("prompt", "")
    return {"nome": pasta.name, "tipo": "imagem", "ideia": ideia, "origem": "", "personagem": e.get("personagem"), "quadros_origem": 0, "passos": [], "rodadas": [], "total": total, "pagina": bool(p), "config": p,
            "feitas": feitas, "completo": total > 0 and len(feitas) >= total, "final": {"marca": int(final.stat().st_mtime), "caminho": str(final)} if final.exists() else None,
            "hd": {"marca": int(hd.stat().st_mtime), "acabamento": e.get("acabamento")} if hd_valido else None, "fps_final": e.get("fps_final"),
            "tem_quadro": False, "foto_existe": bool(e.get("personagem")) and (config.ENTRADA / e["personagem"]).is_file(), "quando": (pasta / "estado.json").stat().st_mtime,
            # Feito na aba Texto para video (sem imagem): o personagem e um quadro da tomada 1
            "sem_imagem": bool(e.get("sem_imagem"))}


def ler_texto(pasta, e, p):
    imagens = [{"n": r.get("n"), "arquivo": r["arquivo"], "semente": r.get("semente"), "segundos": r.get("segundos"), "marca": int((pasta / r["arquivo"]).stat().st_mtime)}
               for r in e.get("imagens", []) if r.get("arquivo") and not r.get("descartada") and (pasta / r["arquivo"]).is_file()]
    # Uma imagem descartada pela pagina conta como feita: o projeto segue completo e o script nao a gera de novo
    descartadas = sum(1 for r in e.get("imagens", []) if r.get("descartada"))
    total = (p or {}).get("quantidade") or len(imagens)
    return {"nome": pasta.name, "tipo": "texto", "ideia": (p or {}).get("prompt", ""), "origem": "", "personagem": None, "quadros_origem": 0, "passos": [], "rodadas": [], "total": total,
            "pagina": bool(p), "config": p, "imagens": imagens, "descartadas": descartadas, "completo": len(imagens) + descartadas >= total, "final": None, "tem_quadro": False,
            "foto_existe": False, "quando": (pasta / "estado.json").stat().st_mtime,
            # Troca em foto: projeto de texto que a aba Trocar personagem mostra (e o palco do Texto para imagem deixa de fora)
            "troca_foto": bool((p or {}).get("troca_foto")), "avisos": e.get("avisos") or []}


def ler_wan(pasta, e, p):
    final = pasta / "final.mp4"
    return {"nome": pasta.name, "tipo": "wan", "ideia": (p or {}).get("prompt", ""), "origem": "", "personagem": e.get("personagem"), "quadros_origem": 0, "passos": [], "rodadas": [], "total": 1,
            "pagina": bool(p), "config": p, "completo": final.exists(), "final": {"marca": int(final.stat().st_mtime), "caminho": str(final)} if final.exists() else None,
            "resultado": e.get("resultado"), "tem_quadro": False, "foto_existe": bool(e.get("personagem")) and (config.ENTRADA / e["personagem"]).is_file(),
            "quando": (pasta / "estado.json").stat().st_mtime}


def ler_editar(pasta, e, p):
    """Editar video (editar_video.py): o cartao e o da troca, com o pedido e a pintura usada."""
    r = ler_troca(pasta, e, p)
    r.update(tipo="editar", ideia=(p or {}).get("pedido", ""), personagem=None, foto_existe=False, referencia=None, janelas=None,
             pintura=(pasta / "pintado.png").is_file())
    return r


def ultimo_quadro(nome, rodadas):
    for n in (rodadas, 0):
        arq = config.ENTRADA / f"cont_{nome}_r{n:02d}.png"
        if arq.exists():
            return arq
    return None


def listar_projetos():
    lista = []
    if not config.PROJETOS.is_dir():
        return lista
    for d in config.PROJETOS.iterdir():
        if d.is_dir() and (d / "estado.json").exists():
            p = ler_projeto(d)
            if p:
                lista.append(p)
    return sorted(lista, key=lambda x: -x["quando"])


PASTAS_SAIDA = ("imagem", "continuacao", "troca", "texto", "wan", "editar")


def _e_link(p):
    return p.is_symlink() or p.is_junction()


def alvos_apagar(nome, junto=()):
    """O que pertence ao projeto: a pasta dele, as pastas de saida do ComfyUI com o nome dele e os arquivos
    temporarios que os scripts criaram na entrada. As imagens e videos enviados ficam: outro projeto pode usar.
    Cada caminho e conferido: filho direto da pasta esperada, sem atalho (link ou juncao) no meio.
    junto: os outros projetos apagados na mesma vez, que nao contam como quem ainda usa um temporario."""
    pasta = pasta_projeto(nome)
    raiz = config.PROJETOS.resolve()
    if not pasta.is_dir() or _e_link(pasta) or pasta.resolve().parent != raiz or not (pasta / "estado.json").is_file():
        raise Erro("Projeto não encontrado.", 404)
    pastas = [pasta]
    for sub in PASTAS_SAIDA:
        base = config.SAIDA / sub
        alvo = base / nome
        if alvo.is_dir() and not _e_link(alvo) and not _e_link(base) and alvo.resolve().parent == base.resolve():
            pastas.append(alvo)
    padrao = re.compile(rf"(imagem_{re.escape(nome)}_\d{{10}}_(t\d+\.mp4|ref\d+\.png|voz\.wav|acab\d+\.mp4|suave\.mp4|av_video[1-3]\.mp4|av_audio[1-3]\.wav)"
                        rf"|cont_{re.escape(nome)}_(r\d{{2}}\.(mp4|png)|ref\.png|qc\.png|seq\.png)"
                        rf"|troca_{re.escape(nome)}\.mp4|troca_{re.escape(nome)}_(q0|ref)\.png"
                        rf"|editar_{re.escape(nome)}\.mp4"
                        rf"|trocafoto_{re.escape(nome)}_(\d{{1,2}}_)?(rosto|roupa)\.png)")
    arquivos = [f for f in config.ENTRADA.iterdir() if padrao.fullmatch(f.name) and f.is_file() and not _e_link(f) and f.resolve().parent == config.ENTRADA.resolve()]
    # Um arquivo temporario usado por outro projeto (a voz, por exemplo) fica
    if arquivos:
        outros = " ".join((d / "estado.json").read_text(encoding="utf-8", errors="replace") for d in config.PROJETOS.iterdir()
                          if d.is_dir() and d.name != nome and d.name not in junto and (d / "estado.json").is_file())
        arquivos = [f for f in arquivos if f.name not in outros]
    return pastas, arquivos


def alvos_apagar_imagem(nome, arquivo):
    """Uma imagem de um projeto de texto: o arquivo na pasta do projeto e a copia que o ComfyUI gravou na saida.
    Devolve (estado, arquivos). Recusa o nome que nao e imagem_N.png ou que o projeto nao lista, e qualquer atalho no caminho."""
    pasta = pasta_projeto(nome)
    raiz = config.PROJETOS.resolve()
    if not pasta.is_dir() or _e_link(pasta) or pasta.resolve().parent != raiz or not (pasta / "estado.json").is_file():
        raise Erro("Projeto não encontrado.", 404)
    e = json.loads((pasta / "estado.json").read_text(encoding="utf-8"))
    m = re.fullmatch(r"imagem_(\d{1,2})\.png", arquivo or "")
    item = next((r for r in e.get("imagens", []) if r.get("arquivo") == arquivo and not r.get("descartada")), None)
    if e.get("tipo") != "texto" or not m or not item:
        raise Erro("Imagem não encontrada neste projeto.", 404)
    alvo = pasta / arquivo
    if not alvo.is_file() or _e_link(alvo) or alvo.resolve().parent != pasta.resolve():
        raise Erro("Imagem não encontrada neste projeto.", 404)
    arquivos = [alvo]
    # A saida do ComfyUI: texto/NOME/imagemN_00001_.png (o prefixo vem do script)
    base = config.SAIDA / "texto"
    saida = base / nome
    if saida.is_dir() and not _e_link(saida) and not _e_link(base) and saida.resolve().parent == base.resolve():
        # Na troca em foto cada passada grava a sua: imagemN_rosto_00001_.png e imagemN_roupa_00001_.png
        copia = re.compile(rf"imagem{m.group(1)}_((rosto|roupa)_)?\d+_\.png")
        arquivos += [f for f in saida.iterdir() if copia.fullmatch(f.name) and f.is_file() and not _e_link(f) and f.resolve().parent == saida.resolve()]
    return e, arquivos


def resumo_apagar(pastas, arquivos):
    n = tamanho = 0
    for p in pastas:
        for f in p.rglob("*"):
            if f.is_file():
                n += 1
                tamanho += f.stat().st_size
    for f in arquivos:
        n += 1
        tamanho += f.stat().st_size
    return {"pastas": [str(p) for p in pastas], "arquivos": n, "mb": round(tamanho / 2**20, 1)}
