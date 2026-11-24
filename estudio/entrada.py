"""Arquivos que o estudio guarda pelo nome na pasta input do ComfyUI (envios do usuario e arquivos fixos do estudio).

Os novos vao para input/estudio/envios/<nome>. Os antigos, que ainda estao soltos na raiz do input, continuam valendo:
quem procura um nome olha primeiro em envios e depois na raiz. O nome guardado no estado, no interface.json, no
midias.json e na pagina continua sem pasta ("foto.png"); so na hora de montar o grafo (no_grafo) ou de abrir o arquivo
(caminho) ele vira o caminho de verdade. Os temporarios das geracoes ficam a parte, em entrada_temp.py.
"""
import json
from pathlib import Path

import config

SUBPASTA = ("estudio", "envios")


def pasta_envios():
    """A pasta dos envios. Funcao (e nao constante) para seguir config.ENTRADA, que os testes trocam."""
    return config.ENTRADA.joinpath(*SUBPASTA)


def _partes(nome):
    texto = str(nome or "").replace("\\", "/")
    partes = texto.split("/")
    if not texto or texto.startswith("/") or ":" in texto or any(p in ("", ".", "..") for p in partes):
        raise ValueError(f"nome invalido na entrada: {nome!r}")
    return partes


def caminho(nome):
    """O arquivo de `nome` no disco. Nome sem pasta: envios/nome se existe, senao a raiz do input se existe (arquivo
    antigo), senao envios/nome (onde o novo vai). Nome com pasta ("estudio/temp/..."): junto da raiz, como veio."""
    partes = _partes(nome)
    if len(partes) > 1:
        return config.ENTRADA.joinpath(*partes)
    novo_ = pasta_envios() / partes[0]
    if novo_.exists():
        return novo_
    antigo = config.ENTRADA / partes[0]
    return antigo if antigo.exists() else novo_


def existe(nome):
    """O arquivo de `nome` existe (em envios ou na raiz)? Nome vazio ou invalido: False."""
    try:
        return bool(nome) and caminho(nome).is_file()
    except ValueError:
        return False


def no_grafo(nome):
    """O nome que o carregador do ComfyUI recebe: "estudio/envios/<nome>" se o arquivo esta em envios; senao o nome
    como veio (arquivo antigo na raiz, ou um nome que ja tem pasta). O que nao e texto (uma ligacao do grafo, None)
    volta como veio."""
    if not isinstance(nome, str) or not nome:
        return nome
    partes = _partes(nome)
    if len(partes) == 1 and (pasta_envios() / partes[0]).exists():
        return "/".join((*SUBPASTA, partes[0]))
    return "/".join(partes)


def novo(nome):
    """Onde gravar `nome` (sem pasta) a partir de agora: envios/nome, com a pasta criada."""
    partes = _partes(nome)
    if len(partes) > 1:
        raise ValueError(f"nome com pasta nao vai para envios: {nome!r}")
    destino = pasta_envios()
    destino.mkdir(parents=True, exist_ok=True)
    return destino / partes[0]


def onde(nome):
    """Todos os lugares em que `nome` (sem pasta) pode estar: envios e a raiz (para apagar ou substituir de vez)."""
    partes = _partes(nome)
    return [pasta_envios() / partes[0], config.ENTRADA / partes[0]]


# Os carregadores do ComfyUI e o campo que leva o nome do arquivo da pasta input
CAMPOS_CARREGADOR = {"LoadImage": "image", "LoadImageMask": "image", "LoadVideo": "file", "LoadAudio": "audio",
                     "VHS_LoadVideoFFmpeg": "video", "VHS_LoadVideo": "video", "VHS_LoadAudio": "audio", "VHS_LoadAudioUpload": "audio"}


def resolver_grafo(g):
    """Passa por no_grafo o nome de cada carregador do grafo (e cada "file" do media_state do carregador de midia do H3),
    na hora de mandar ao ComfyUI: o arquivo que esta em envios vai com a subpasta. Muda o grafo e o devolve."""
    for no in (g or {}).values():
        if not isinstance(no, dict) or not isinstance(no.get("inputs"), dict):
            continue
        ins, tipo = no["inputs"], no.get("class_type")
        campo = CAMPOS_CARREGADOR.get(tipo)
        if campo and isinstance(ins.get(campo), str) and ins[campo]:
            try:
                ins[campo] = no_grafo(ins[campo])
            except ValueError:
                pass  # nome fora do padrao: vai como veio, e o ComfyUI recusa
        if tipo == "MiniMaxH3MediaLoader" and isinstance(ins.get("media_state"), str):
            try:
                midia = json.loads(ins["media_state"])
            except ValueError:
                continue
            if not isinstance(midia, list):
                continue
            for item in midia:
                if isinstance(item, dict) and isinstance(item.get("file"), str) and item["file"]:
                    try:
                        item["file"] = no_grafo(item["file"])
                    except ValueError:
                        pass
            ins["media_state"] = json.dumps(midia)
    return g
