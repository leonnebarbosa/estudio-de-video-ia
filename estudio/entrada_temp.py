"""Arquivos temporarios das geracoes na pasta input do ComfyUI.

Tudo o que uma geracao copia para o input so para o grafo ler (quadros, recortes, trechos de video e audio) fica em
input/estudio/temp/<dono>/, onde <dono> e o nome do projeto (ou personagem_<id> para os trabalhos de personagem).
A pasta some quando a geracao termina bem, quando o projeto e apagado e, se sobrar de uma queda, na varredura que o
servidor faz ao ligar (pastas sem mudanca ha mais de 2 dias). O que o estudio guarda de proposito (envios, fotos de
personagem, continuacoes) fica em input/estudio/envios (entrada.py), e os antigos continuam valendo na raiz do input.

Os carregadores do ComfyUI (LoadImage, LoadVideo, LoadAudio, VHS_LoadVideoFFmpeg, o de midia do H3) aceitam o nome com a
subpasta, sempre com "/": "estudio/temp/<dono>/<arquivo>".
"""
import shutil, time
from pathlib import Path

import config

SUBPASTA = ("estudio", "temp")
DIAS = 2


def pasta(entrada=None):
    """A raiz dos temporarios. Funcao (e nao constante) para seguir config.ENTRADA, que os testes trocam."""
    return Path(entrada or config.ENTRADA).joinpath(*SUBPASTA)


def _parte(texto, oque):
    texto = str(texto or "")
    if not texto or texto in (".", "..") or any(c in texto for c in "/\\:") or ".." in texto:
        raise ValueError(f"{oque} invalido para arquivo temporario: {texto!r}")
    return texto


def dono_personagem(pid):
    return f"personagem_{pid}"


def arquivo(dono, nome, entrada=None):
    """(caminho absoluto, nome para o grafo) de um temporario de `dono`. Cria a pasta do dono. `entrada`: outra pasta
    input no lugar de config.ENTRADA (testes)."""
    dono, nome = _parte(dono, "dono"), _parte(nome, "nome")
    destino = pasta(entrada) / dono
    destino.mkdir(parents=True, exist_ok=True)
    return destino / nome, "/".join((*SUBPASTA, dono, nome))


def caminho(nome_grafo):
    """O caminho absoluto de um nome que o grafo recebe (com ou sem subpasta)."""
    return config.ENTRADA.joinpath(*str(nome_grafo).replace("\\", "/").split("/"))


def _e_link(p):
    try:
        return p.is_symlink() or bool(getattr(p, "is_junction", lambda: False)())
    except OSError:
        return True


def _dentro(alvo):
    """A pasta do dono, so se for uma pasta de verdade (sem link) direto dentro da raiz dos temporarios."""
    raiz = pasta()
    if not raiz.is_dir() or _e_link(raiz) or not alvo.exists() or _e_link(alvo) or not alvo.is_dir():
        return False
    try:
        return alvo.resolve().parent == raiz.resolve()
    except OSError:
        return False


def _remover(alvo):
    # O rmtree do Python 3.13 nao entra em links nem em juncoes la dentro: apaga o link, sem tocar no destino
    shutil.rmtree(alvo)


def pasta_do_dono(dono):
    """A pasta de temporarios de `dono`, se ela existe e passa na conferencia (sem link, direto na raiz); senao None."""
    try:
        alvo = pasta() / _parte(dono, "dono")
    except ValueError:
        return None
    return alvo if _dentro(alvo) else None


def apagar(dono):
    """Apaga input/estudio/temp/<dono>. Devolve a lista do que apagou (vazia se nao havia nada)."""
    try:
        alvo = pasta() / _parte(dono, "dono")
    except ValueError:
        return []
    if not _dentro(alvo):
        return []
    try:
        _remover(alvo)
    except OSError:
        return []
    return [alvo]


def _mais_novo(p):
    try:
        maior = p.stat().st_mtime
        for f in p.rglob("*"):
            try:
                maior = max(maior, f.lstat().st_mtime)
            except OSError:
                pass
        return maior
    except OSError:
        return None


def varrer(dias=DIAS, agora=None):
    """Apaga as pastas de temporarios sem mudanca ha mais de `dias` (sobras de geracoes que cairam). Devolve as apagadas."""
    raiz = pasta()
    if not raiz.is_dir() or _e_link(raiz):
        return []
    limite = (time.time() if agora is None else agora) - dias * 86400
    apagadas = []
    for d in list(raiz.iterdir()):
        if not _dentro(d):
            continue
        quando = _mais_novo(d)
        if quando is not None and quando < limite and apagar(d.name):
            apagadas.append(d)
    return apagadas
