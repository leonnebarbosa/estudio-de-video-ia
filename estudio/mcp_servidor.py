"""MCP (Model Context Protocol) do estudio, em JSON-RPC 2.0 escrito a mao, so com a biblioteca padrao.
Um pedido POST /mcp traz uma mensagem; atender() devolve (codigo HTTP, resposta ou None). As ferramentas
(mcp_ferramentas.py) se registram aqui com registrar(); cada uma diz para quais niveis de chave aparece.
Uso por quem chama: atender(corpo, nivel) com nivel "operador" ou "completo" (ver acesso.py)."""
import base64, contextvars, json, re, sys, time, traceback
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
_BASE = contextvars.ContextVar("base", default=None)  # o endereco (http://host:porta) pelo qual o pedido chegou


def nivel_atual():
    """O nivel da chave ("operador" ou "completo") de quem chamou a ferramenta em andamento; None fora de uma chamada."""
    return _NIVEL.get()


def base_atual():
    """O endereco do estudio como quem chamou o enxerga (para montar links); fora de um pedido, o endereco local."""
    return _BASE.get() or f"http://127.0.0.1:{config.PORTA}"


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


REGISTRO = None  # arquivo do registro das chamadas (logs/mcp.log); None = desligado. Quem liga e o lancador (estudio.pyw)
MAX_REGISTRO = 2_000_000  # bytes; acima disso o arquivo vira mcp.log.1 e comeca outro
_SO_O_TAMANHO = ("conteudo_base64",)  # argumentos que nunca vao para o registro (o arquivo inteiro em base64)


def _resumir(valor, limite=300, chave=None):
    """Os argumentos como vao para o registro: textos longos (um prompt) cortados, com o tamanho; base64 so o tamanho."""
    if isinstance(valor, str):
        if chave in _SO_O_TAMANHO:
            return f"({len(valor)} caracteres)"
        return valor if len(valor) <= limite else f"{valor[:limite]}… ({len(valor)} caracteres)"
    if isinstance(valor, dict):
        return {k: _resumir(v, limite, k) for k, v in list(valor.items())[:30]}
    if isinstance(valor, list):
        return [_resumir(v, limite) for v in valor[:20]]
    return valor


def _registrar(texto_da_linha):
    """Uma linha em REGISTRO. Nunca quebra quem chama."""
    if not REGISTRO:
        return
    try:
        arq = Path(REGISTRO)
        arq.parent.mkdir(parents=True, exist_ok=True)
        if arq.is_file() and arq.stat().st_size > MAX_REGISTRO:
            arq.replace(arq.with_name(arq.name + ".1"))
        with open(arq, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {texto_da_linha}\n")
    except Exception:
        pass


def _registrar_chamada(nivel, params, resultado, segundos):
    """nivel ferramenta ok|ERRO tempo args={...} -> comeco da resposta. O codigo dos links (/m/...) nao entra: e uma credencial."""
    if not REGISTRO:
        return
    try:
        resposta = " | ".join(str(c.get("text", "")) for c in resultado.get("content", []) if isinstance(c, dict))
        resposta = re.sub(r"/m/[\w-]+", "/m/<código>", " | ".join(resposta.splitlines()))[:400]
        args = json.dumps(_resumir(params.get("arguments")), ensure_ascii=False)
        _registrar(f"{nivel} {params.get('name')} {'ERRO' if resultado.get('isError') else 'ok'} {segundos:.1f}s args={args} -> {resposta}")
    except Exception:
        pass


def _chamar(params, nivel, base=None):
    inicio = time.monotonic()
    resultado = _executar(params, nivel, base)
    _registrar_chamada(nivel, params, resultado, time.monotonic() - inicio)
    return resultado


def _executar(params, nivel, base=None):
    ferramenta = FERRAMENTAS.get(params.get("name"))
    if ferramenta is None or nivel not in ferramenta["niveis"]:
        return _falha(INDISPONIVEL)
    argumentos = params.get("arguments")
    if argumentos is None:
        argumentos = {}
    if not isinstance(argumentos, dict):
        return _falha("Os argumentos precisam ser um objeto.")
    marca, marca_base = _NIVEL.set(nivel), _BASE.set(base)
    try:
        return {"content": ferramenta["funcao"](argumentos), "isError": False}
    except Erro as e:
        return _falha(e.mensagem)
    except Exception as e:
        traceback.print_exc()
        return _falha(f"Falha inesperada no estúdio ({type(e).__name__}: {str(e)[:200]}).")
    finally:
        _NIVEL.reset(marca)
        _BASE.reset(marca_base)


def atender(corpo, nivel, base=None):
    """Responde uma mensagem JSON-RPC; `base` e o endereco pelo qual o pedido chegou (base_atual). Devolve (codigo HTTP, dict) ou (202, None) para notificacoes."""
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
        _registrar(f"{nivel} initialize")
        return 200, _resposta(id_, _iniciar(params, nivel))
    if metodo == "ping":
        return 200, _resposta(id_, {})
    if metodo == "tools/list":
        _registrar(f"{nivel} tools/list")
        return 200, _resposta(id_, {"tools": listar(nivel)})
    if metodo == "tools/call":
        if not isinstance(params.get("name"), str):
            return 200, _erro(id_, -32602, "O nome da ferramenta precisa ser um texto.")
        return 200, _resposta(id_, _chamar(params, nivel, base))
    return 200, _erro(id_, -32601, f"Método não existe: {metodo}")
