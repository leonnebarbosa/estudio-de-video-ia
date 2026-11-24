"""Ferramentas do MCP do nivel completo (o Claude Code): chamar_api, enviar_arquivo e ver_log.
So aparecem para a chave completa. O chamar_api pode apagar, com confirmar: true, como a pagina."""
import config
from erros import Erro
from mcp_servidor import texto


PORTA_API = config.PORTA  # lida na hora de chamar: os testes apontam para o servidor deles
LIMITE_ARQUIVO = 20 * 1024 * 1024  # bytes, depois de decodificar
TEMPO_API = 600  # s: algumas rotas esperam o LLM local


def _postar(rota, dados, timeout=TEMPO_API):
    """POST na propria API do estudio, como a pagina faz (127.0.0.1 nao precisa de chave). Devolve (codigo HTTP, dict)."""
    import json, urllib.error, urllib.request
    host = f"127.0.0.1:{PORTA_API}"
    p = urllib.request.Request(f"http://{host}{rota}", data=json.dumps(dados).encode("utf-8"), method="POST",
                               headers={"Host": host, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(p, timeout=timeout) as r:
            codigo, corpo = r.status, r.read()
    except urllib.error.HTTPError as e:
        codigo, corpo = e.code, e.read()
    except (OSError, ValueError) as e:
        raise Erro(f"Não consegui falar com o estúdio na porta {PORTA_API} ({type(e).__name__}).", 502)
    try:
        corpo = json.loads(corpo or b"{}")
    except ValueError:
        corpo = {"erro": "Resposta do estúdio ilegível."} if codigo >= 400 else {}
    return codigo, corpo if isinstance(corpo, dict) else {"resposta": corpo}


def chamar_api(a):
    import json
    import servidor  # so aqui: o servidor importa este arquivo
    rota = a.get("rota")
    if rota not in servidor.ROTAS_POST:
        raise Erro("Rota não permitida. Use uma das rotas do esquema de chamar_api.")
    dados = a.get("dados", {})
    if not isinstance(dados, dict):
        raise Erro("O campo dados precisa ser um objeto.")
    codigo, corpo = _postar(rota, dados)
    if codigo >= 400:
        raise Erro(str(corpo.get("erro") or f"O estúdio respondeu com o código {codigo}."), codigo)
    return [texto(json.dumps(corpo, ensure_ascii=False))]


ERRO_GRANDE = "Arquivo grande demais para o MCP. Chame pedir_envio (link para o usuário enviar) ou importar_url (se ele já está na internet); a página também serve."


def enviar_arquivo(a):
    import base64, binascii, io
    from envio import receber_arquivo
    b64 = a.get("conteudo_base64")
    if not isinstance(b64, str) or not b64.strip():
        raise Erro("Falta o conteúdo do arquivo em base64 (campo conteudo_base64).")
    # Antes de decodificar: 4 caracteres dao 3 bytes, entao um texto enorme ja passa do limite
    if len(b64) * 3 // 4 > LIMITE_ARQUIVO + 3:
        raise Erro(ERRO_GRANDE)
    try:
        dados = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        raise Erro("O conteúdo não é base64 válido.")
    if len(dados) > LIMITE_ARQUIVO:
        raise Erro(ERRO_GRANDE)
    r = receber_arquivo(io.BytesIO(dados), len(dados), a.get("tipo"), str(a.get("nome") or ""), origem="mcp")
    return [texto(f"Arquivo recebido: {r.get('arquivo')} ({len(dados)} bytes).")]


def ver_log(a):
    n = a.get("linhas")
    if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= 200:
        raise Erro("O campo linhas precisa ser um número inteiro de 1 a 200.")
    arquivo = config.LOGS / "estudio.log"
    try:
        # Um log de dias cabe na memoria; so as ultimas linhas importam
        linhas = arquivo.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
    except OSError:
        return [texto("Ainda não há log do estúdio.")]
    return [texto("\n".join(linhas) or "O log está vazio.")]


def _rotas():
    import servidor
    return sorted(servidor.ROTAS_POST)
