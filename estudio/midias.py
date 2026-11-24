"""Registro das midias que entraram no estudio (fotos, audios e videos), para o agente do MCP saber o que ja foi enviado.
Fica em midias.json (ignorado pelo Git): {nome: {"tipo", "quando", "origem", ...medidas}}. Os arquivos continuam nas pastas de sempre
(input/estudio/envios do ComfyUI para foto e audio, ou a raiz do input nos antigos; config.ENVIOS para video); o registro so guarda de onde vieram e as medidas.
Uso: registrar(...) ao receber um arquivo; listar(...) para ver os que ainda existem; tipo_de(nome) para saber de que tipo e um nome."""
import json, threading, time
from pathlib import Path

import caminhos
import config
import entrada

ARQUIVO = config.WORKFLOWS / "midias.json"  # lido na hora do uso: os testes apontam para outro
ORIGENS = ("pagina", "link", "url", "mcp")
LIMITES = {"foto": 30_000_000, "audio": 50_000_000, "video": 200_000_000}  # bytes por envio
SUFIXOS_FOTO = (".png", ".jpg", ".jpeg", ".webp")

_trava = threading.Lock()


def _arquivo(tipo, nome):
    """Onde a midia `nome` do `tipo` fica: video em config.ENVIOS; foto e audio na entrada (envios, ou a raiz nos antigos)."""
    if tipo == "video":
        return config.ENVIOS / nome
    try:
        return entrada.caminho(nome)
    except ValueError:
        return None


def _existe(tipo, nome):
    arq = _arquivo(tipo, nome)
    return arq is not None and arq.is_file()


def _ler():
    try:
        dados = json.loads(Path(ARQUIVO).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return dados if isinstance(dados, dict) else {}


def registrar(nome, tipo, origem, info):
    """Anota a midia `nome` (o nome final, na pasta do tipo). `info` traz as medidas (largura, altura, duracao...)."""
    if origem not in ORIGENS:
        raise ValueError(f"Origem desconhecida: {origem!r}. Use uma de {', '.join(ORIGENS)}.")
    with _trava:
        dados = _ler()
        dados[nome] = {"tipo": tipo, "quando": time.time(), "origem": origem, **info}
        caminhos.gravar_json(ARQUIVO, dados)


def listar(tipo=None, limite=30):
    """As midias registradas que ainda existem no disco, da mais nova para a mais antiga, cada uma com `nome`."""
    itens = []
    for nome, r in _ler().items():
        if not isinstance(r, dict) or (tipo and r.get("tipo") != tipo):
            continue
        if not isinstance(nome, str) or not nome or Path(nome).name != nome or not _existe(r.get("tipo"), nome):
            continue
        itens.append({"nome": nome, **r})
    itens.sort(key=lambda m: m.get("quando") or 0, reverse=True)
    return itens[:limite]


def tipo_de(nome):
    """O tipo de `nome`, pelo registro ou, sem registro, pelo sufixo; so se o arquivo existir na pasta do tipo. Senao: None."""
    if not isinstance(nome, str) or not nome or Path(nome).name != nome:
        return None
    r = _ler().get(nome)
    if isinstance(r, dict) and r.get("tipo") in LIMITES:
        tipo = r["tipo"]
    else:
        from envio import SUFIXOS_AUDIO  # so aqui: o envio importa este arquivo
        sufixo = Path(nome).suffix.lower()
        tipo = "video" if sufixo == ".mp4" else "foto" if sufixo in SUFIXOS_FOTO else "audio" if sufixo in SUFIXOS_AUDIO else None
    return tipo if tipo and _existe(tipo, nome) else None
