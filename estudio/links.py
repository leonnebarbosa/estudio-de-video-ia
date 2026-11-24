"""Links temporarios do MCP: um codigo na URL (/m/<codigo>) dá acesso a um unico arquivo (baixar) ou a um unico envio (enviar).
O codigo e a credencial: quem o tem entra sem chave, so naquele alvo. Valem 1 hora e ficam tambem em logs/links.json (fora do Git) para sobreviver a um religamento do estudio.
Uso: criar_baixar/criar_enviar devolvem o codigo; ler(codigo) diz o que ele permite; gastar(codigo) encerra um link de envio."""
import json, secrets, threading, time
from pathlib import Path

import caminhos, config

VALIDADE = 3600  # segundos
MAXIMO = 200  # links guardados ao mesmo tempo; passando disso, saem os mais antigos
TIPOS_ENVIO = ("foto", "audio", "video")

ARQUIVO = None  # onde os links ficam gravados; None = config.LOGS/links.json, lido na hora do uso (os testes apontam para outro)

_itens = {}  # codigo -> {"acao", "arquivo", "nome", "tipo", "criado", "gasto"}
_trava = threading.Lock()
_carregado = False  # o arquivo e lido uma vez, na primeira operacao; esvaziar _itens na mao nao dispara nova leitura


def _caminho():
    return Path(ARQUIVO) if ARQUIVO else config.LOGS / "links.json"


def recarregar():
    """Esvazia a memoria e le o arquivo de novo na proxima operacao (o que acontece num religamento do estudio)."""
    global _carregado
    with _trava:
        _itens.clear()
        _carregado = False


def _item_valido(i):
    """O item lido do arquivo, pronto para a memoria (arquivo volta como Path), ou None se vencido, gasto ou malformado."""
    if not isinstance(i, dict) or i.get("acao") not in ("baixar", "enviar") or i.get("gasto") is not False:
        return None
    criado = i.get("criado")
    if not isinstance(criado, (int, float)) or isinstance(criado, bool) or time.time() - criado > VALIDADE:
        return None
    arquivo, nome, tipo = i.get("arquivo"), i.get("nome"), i.get("tipo")
    if not all(v is None or isinstance(v, str) for v in (arquivo, nome, tipo)):
        return None
    if i["acao"] == "baixar" and not arquivo:
        return None
    if i["acao"] == "enviar" and tipo not in TIPOS_ENVIO:
        return None
    return {"acao": i["acao"], "arquivo": Path(arquivo) if arquivo else None, "nome": nome, "tipo": tipo, "criado": criado, "gasto": False}


def _carregar():
    """Chamada com a trava: na primeira operacao junta a memoria o que o arquivo guarda e ainda vale."""
    global _carregado
    if _carregado:
        return
    _carregado = True
    try:
        dados = json.loads(_caminho().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(dados, dict):
        return
    for codigo, i in dados.items():
        item = _item_valido(i)
        if codigo and item:
            _itens.setdefault(codigo, item)
    if len(dados) != len(_itens):
        _gravar()  # o arquivo guardava codigos vencidos, gastos ou malformados: regrava so com o que vale


def _gravar():
    """Chamada com a trava. O codigo e a credencial: o arquivo so fica em logs/ e nada aqui o mostra. Se nao grava, segue em
    memoria. Devolve se gravou. Vencidos e gastos nunca ficam no arquivo."""
    agora = time.time()
    for c in [c for c, i in _itens.items() if agora - i["criado"] > VALIDADE or i["gasto"]]:
        del _itens[c]
    try:
        arq = _caminho()
        arq.parent.mkdir(parents=True, exist_ok=True)
        caminhos.gravar_json(arq, {c: {**i, "arquivo": str(i["arquivo"]) if i["arquivo"] else None} for c, i in _itens.items()})
        return True
    except (OSError, TypeError, ValueError):
        return False


def _criar(item, igual=None):
    """Cria o link. Com `igual` (item -> bool), um link que ja existe, valido e igual, e devolvido no lugar de um novo."""
    agora = time.time()
    with _trava:
        _carregar()
        for c in [c for c, i in _itens.items() if agora - i["criado"] > VALIDADE or i["gasto"]]:
            del _itens[c]
        if igual:
            achado = next((c for c, i in _itens.items() if igual(i)), None)
            if achado:
                return achado
        while len(_itens) >= MAXIMO:
            del _itens[min(_itens, key=lambda c: _itens[c]["criado"])]
        codigo = secrets.token_urlsafe(32)
        _itens[codigo] = {**item, "criado": agora, "gasto": False}
        _gravar()
    return codigo


def criar_baixar(arquivo, nome):
    """Link para baixar `arquivo` (varias vezes, ate vencer); `nome` e o nome sugerido ao salvar. Quem pede de novo o mesmo arquivo
    com o mesmo nome recebe o mesmo codigo enquanto restar metade da validade (o texto do MCP promete 30 min): o ver_resultado repetido nao enche o limite nem expulsa um link de envio."""
    arquivo = Path(arquivo)
    return _criar({"acao": "baixar", "arquivo": arquivo, "nome": nome, "tipo": None},
                  igual=lambda i: i["acao"] == "baixar" and i["arquivo"] == arquivo and i["nome"] == nome
                  and time.time() - i["criado"] <= VALIDADE / 2)


def criar_enviar(tipo):
    """Link para enviar um arquivo de `tipo` ("foto", "audio" ou "video"); vale para um envio so."""
    if tipo not in TIPOS_ENVIO:
        raise ValueError(f"Tipo de envio inválido: {tipo}")
    return _criar({"acao": "enviar", "arquivo": None, "nome": None, "tipo": tipo})


def ler(codigo):
    """O que o link permite ({"acao", "arquivo", "nome", "tipo"}), ou None se nao existe, venceu ou ja foi gasto."""
    if not isinstance(codigo, str) or not codigo:
        return None
    with _trava:
        _carregar()
        i = _itens.get(codigo)
        if i is None or i["gasto"] or time.time() - i["criado"] > VALIDADE:
            return None
        return {k: i[k] for k in ("acao", "arquivo", "nome", "tipo")}


def gastar(codigo):
    """Encerra um link de envio: depois disso `ler` devolve None."""
    with _trava:
        _carregar()
        if codigo in _itens:
            _itens[codigo]["gasto"] = True
            if not _gravar():
                # O arquivo ficou com gasto: false e um religamento reabriria o envio. Sem gravar, apaga o arquivo (perde os
                # outros links, mas nunca reabre um gasto). Se nem apagar der, segue em memoria.
                try:
                    _caminho().unlink(missing_ok=True)
                except OSError:
                    pass
