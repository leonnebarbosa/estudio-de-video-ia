"""Avalia um modelo (API compativel com a OpenAI, ex.: LM Studio) como operador do estudio: manda cada pedido de
mcp/avaliacao/pedidos.json com as ferramentas do nivel operador e confere a PRIMEIRA chamada de ferramenta que ele propoe.
Nada e executado no estudio. Uso:
  python -I avaliar_operador.py --url http://HOST:1234/v1 --modelo NOME [--saida logs/avaliacao_NOME.md] [--chave CHAVE] [--tempo 120]"""
import argparse, json, re, sys, time, urllib.error, urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # com -I a pasta do script nao entra sozinha
import config
import mcp_servidor, mcp_ferramentas  # noqa: F401 (o import registra as ferramentas)

PEDIDOS = config.ESTUDIO / "mcp" / "avaliacao" / "pedidos.json"
TEMPO = 120  # segundos por pedido


def carregar_pedidos(caminho=PEDIDOS):
    return json.loads(Path(caminho).read_text(encoding="utf-8"))


def ferramentas_openai(nivel="operador"):
    return [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["inputSchema"]}}
            for t in mcp_servidor.listar(nivel)]


def _lista(v):
    return v if isinstance(v, list) else [v]


def pontuar(espera, chamada):
    """(acertou, motivo). `chamada` e {"name", "arguments"} da primeira chamada proposta, ou None se nao chamou nada.
    `espera` pode ser uma lista de alternativas: basta acertar uma (o motivo de erro e o da primeira)."""
    if isinstance(espera, list):
        resultados = [pontuar(e, chamada) for e in espera]
        return next((r for r in resultados if r[0]), resultados[0])
    aceitas = _lista(espera.get("ferramenta"))
    if aceitas == [None]:
        if chamada is None:
            return True, "perguntou antes, sem chamar nada"
        return False, f"chamou {chamada['name']}, mas devia perguntar antes"
    if chamada is None:
        return False, "não chamou nenhuma ferramenta (esperava " + " ou ".join(aceitas) + ")"
    if chamada["name"] not in aceitas:
        return False, f"chamou {chamada['name']}, esperava " + " ou ".join(aceitas)
    args = chamada.get("arguments")
    if not isinstance(args, dict):
        return False, "argumentos que não são um objeto"
    for campo, valor in (espera.get("argumentos") or {}).items():
        if campo not in args:
            return False, f"faltou o argumento {campo}"
        if args[campo] not in _lista(valor):
            return False, f"{campo}={args[campo]!r}, esperava " + " ou ".join(repr(v) for v in _lista(valor))
    return True, "ok"


def _perguntar(url, chave, corpo, tempo):
    cab = {"Content-Type": "application/json"}
    if chave:
        cab["Authorization"] = f"Bearer {chave}"
    pedido = urllib.request.Request(url.rstrip("/") + "/chat/completions", json.dumps(corpo).encode(), cab)
    with urllib.request.urlopen(pedido, timeout=tempo) as r:
        return json.loads(r.read().decode("utf-8"))


def _primeira_chamada(resposta):
    """(chamada ou None, texto da resposta). Argumentos que nao sao JSON ficam como texto e a pontuacao os recusa."""
    msg = resposta["choices"][0]["message"]
    texto = (msg.get("content") or "").strip()
    for c in msg.get("tool_calls") or []:
        f = c.get("function") or {}
        bruto = f.get("arguments")
        try:
            args = json.loads(bruto) if isinstance(bruto, str) and bruto.strip() else (bruto or {})
        except ValueError:
            args = bruto
        return {"name": f.get("name"), "arguments": args}, texto
    return None, texto


def avaliar(url, modelo, pedidos, chave=None, tempo=TEMPO):
    """Roda os pedidos um a um. Devolve [{pedido, espera, chamada, texto, ok, motivo, segundos}]; falha de um nao para os outros."""
    sistema = mcp_servidor.INSTRUCOES.read_text(encoding="utf-8").strip()
    ferramentas = ferramentas_openai()
    resultados = []
    for p in pedidos:
        corpo = {"model": modelo, "tool_choice": "auto", "tools": ferramentas, "temperature": 0,
                 "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": p["pedido"]}]}
        r = {"pedido": p["pedido"], "espera": p["espera"], "chamada": None, "texto": "", "ok": False, "motivo": "", "segundos": 0.0}
        t0 = time.time()
        try:
            r["chamada"], r["texto"] = _primeira_chamada(_perguntar(url, chave, corpo, tempo))
            r["ok"], r["motivo"] = pontuar(p["espera"], r["chamada"])
        except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError, TypeError) as e:
            r["motivo"] = f"falha na requisição ({type(e).__name__}: {str(e)[:150]})"
        r["segundos"] = round(time.time() - t0, 1)
        resultados.append(r)
    return resultados


def _celula(s):
    return str(s).replace("|", "\\|").replace("\n", " ")


def relatorio(modelo, resultados):
    acertos = sum(r["ok"] for r in resultados)
    linhas = [f"# Avaliação do operador: {modelo}", "", f"Acertos: {acertos}/{len(resultados)}", "",
              "| # | Pedido | Resultado | Chamada recebida | Motivo | s |", "|---|---|---|---|---|---|"]
    for i, r in enumerate(resultados, 1):
        c = r["chamada"]
        if c:
            recebida = f"{c['name']}({json.dumps(c['arguments'], ensure_ascii=False)})"
        else:
            recebida = "sem chamada" + (f": {r['texto'][:200]}" if r["texto"] else "")
        linhas.append(f"| {i} | {_celula(r['pedido'])} | {'acertou' if r['ok'] else 'errou'} | {_celula(recebida)} | {_celula(r['motivo'])} | {r['segundos']} |")
    return "\n".join(linhas) + "\n"


def gravar(caminho, texto):
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(texto, encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--url", required=True, help="base da API, ex.: http://HOST:1234/v1")
    ap.add_argument("--modelo", required=True)
    ap.add_argument("--saida", help="relatório em Markdown (padrão: logs/avaliacao_<modelo>.md)")
    ap.add_argument("--chave", help="chave da API, se o servidor pedir")
    ap.add_argument("--tempo", type=int, default=TEMPO, help="segundos de espera por pedido")
    a = ap.parse_args(argv)
    nome = re.sub(r"[^A-Za-z0-9._-]+", "_", a.modelo)
    saida = Path(a.saida) if a.saida else config.LOGS / f"avaliacao_{nome}.md"
    resultados = avaliar(a.url, a.modelo, carregar_pedidos(), a.chave, a.tempo)
    texto = relatorio(a.modelo, resultados)
    gravar(saida, texto)
    print(texto)
    print(f"Relatório gravado em {saida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
