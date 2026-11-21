"""MCP (Model Context Protocol) do estudio, em JSON-RPC 2.0 escrito a mao, so com a biblioteca padrao.
Um pedido POST /mcp traz uma mensagem; atender() devolve (codigo HTTP, resposta ou None). As ferramentas
(mcp_ferramentas.py) se registram aqui com registrar(); cada uma diz para quais niveis de chave aparece.
Uso por quem chama: atender(corpo, nivel) com nivel "operador" ou "completo" (ver acesso.py)."""
import base64, contextvars, json, sys, traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config
from erros import Erro

PROTOCOLOS = ("2025-06-18", "2025-03-26", "2024-11-05")  # a primeira e a preferida
INSTRUCOES = config.ESTUDIO / "mcp" / "instrucoes_operador.md"
INSTRUCOES_COMPLETO = config.ESTUDIO / "mcp" / "instrucoes_completo.md"  # o que o nivel completo tem a mais
FERRAMENTAS = {}  # nome -> {"descricao", "esquema", "niveis", "funcao"}
INDISPONIVEL = "Ferramenta não disponível para esta chave."
_NIVEL = contextvars.ContextVar("nivel", default=None)  # o nivel da chave do pedido em andamento (cada thread tem o seu)


def nivel_atual():
    """O nivel da chave ("operador" ou "completo") de quem chamou a ferramenta em andamento; None fora de uma chamada."""
    return _NIVEL.get()


def registrar(nome, descricao, esquema, niveis, funcao):
    """Poe uma ferramenta no ar. `funcao(argumentos: dict)` devolve a lista de conteudos (texto(), imagem())."""
    FERRAMENTAS[nome] = {"descricao": descricao, "esquema": esquema, "niveis": set(niveis), "funcao": funcao}


def texto(s):
    return {"type": "text", "text": s}


def imagem(png):
    return {"type": "image", "data": base64.b64encode(png).decode("ascii"), "mimeType": "image/png"}


def listar(nivel):
    """Os descritores das ferramentas que esse nivel de chave enxerga."""
    return [{"name": n, "description": f["descricao"], "inputSchema": f["esquema"]} for n, f in FERRAMENTAS.items() if nivel in f["niveis"]]


def _resposta(id_, resultado):
    return {"jsonrpc": "2.0", "id": id_, "result": resultado}


def _erro(id_, codigo, mensagem):
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": codigo, "message": mensagem}}


def _falha(mensagem):
    return {"content": [texto(mensagem)], "isError": True}


def _instrucoes(nivel):
    """As instrucoes do operador; ao completo, o mesmo texto e um paragrafo com as ferramentas que so ele tem."""
    try:
        t = INSTRUCOES.read_text(encoding="utf-8").strip()
    except OSError:
        t = "Estúdio de vídeo local: use ver_estado para ver o que está acontecendo."
    if nivel == "completo":
        try:
            t += "\n\n" + INSTRUCOES_COMPLETO.read_text(encoding="utf-8").strip()
        except OSError:
            pass
    return t


def _iniciar(params, nivel):
    pedida = params.get("protocolVersion")
    return {"protocolVersion": pedida if pedida in PROTOCOLOS else PROTOCOLOS[0],
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "estudio", "version": "1"},
            "instructions": _instrucoes(nivel)}


def _chamar(params, nivel):
    ferramenta = FERRAMENTAS.get(params.get("name"))
    if ferramenta is None or nivel not in ferramenta["niveis"]:
        return _falha(INDISPONIVEL)
    argumentos = params.get("arguments")
    if argumentos is None:
        argumentos = {}
    if not isinstance(argumentos, dict):
        return _falha("Os argumentos precisam ser um objeto.")
    marca = _NIVEL.set(nivel)
    try:
        return {"content": ferramenta["funcao"](argumentos), "isError": False}
    except Erro as e:
        return _falha(e.mensagem)
    except Exception as e:
        traceback.print_exc()
        return _falha(f"Falha inesperada no estúdio ({type(e).__name__}: {str(e)[:200]}).")
    finally:
        _NIVEL.reset(marca)


def atender(corpo, nivel):
    """Responde uma mensagem JSON-RPC. Devolve (codigo HTTP, dict) ou (202, None) para notificacoes."""
    try:
        msg = json.loads(corpo)
    except (ValueError, UnicodeDecodeError):
        return 200, _erro(None, -32700, "JSON inválido.")
    if not isinstance(msg, dict) or not isinstance(msg.get("method"), str):
        return 200, _erro(None, -32600, "Pedido inválido.")
    metodo, id_ = msg["method"], msg.get("id")
    params = msg.get("params")
    if not isinstance(params, dict):
        params = {}
    if "id" not in msg:  # notificacao: nao tem resposta
        return 202, None
    if metodo == "initialize":
        return 200, _resposta(id_, _iniciar(params, nivel))
    if metodo == "ping":
        return 200, _resposta(id_, {})
    if metodo == "tools/list":
        return 200, _resposta(id_, {"tools": listar(nivel)})
    if metodo == "tools/call":
        if not isinstance(params.get("name"), str):
            return 200, _erro(id_, -32602, "O nome da ferramenta precisa ser um texto.")
        return 200, _resposta(id_, _chamar(params, nivel))
    return 200, _erro(id_, -32601, f"Método não existe: {metodo}")
