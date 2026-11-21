"""Receitas de video, regras das tomadas e planos do MCP. Quem escreve as tomadas e o agente que conversa com o usuario
(cliente MCP): regras() entrega os limites e um exemplo, o planejar_video confere as tomadas com a mesma validacao da
pagina e guarda o pedido pronto por 30 min; o confirmar_plano usa o plano uma vez so. Nada aqui toca na placa."""
import copy, json, secrets, threading, time

import config
from erros import Erro
from imagem_para_video import CAMERAS, duracao_maxima, duracoes_permitidas
from validacao import MAX_TOMADAS

RECEITAS = config.ESTUDIO / "mcp" / "receitas.json"
REGRAS = config.ESTUDIO / "mcp" / "receitas" / "regras_tomadas.md"
FORMATOS = {"9:16": "9:16 (Portrait Widescreen)", "16:9": "16:9 (Widescreen)", "1:1": "1:1 (Square)"}
VALIDADE = 1800  # segundos que um plano vale
# Qualidade do planejar_video (pedido do usuario, 21/11/2026): "ugc" e a receita como esta; "rapido" troca so a resolucao e
# tira a pele natural, para um teste que fica pronto bem antes
QUALIDADES = {"ugc": {}, "rapido": {"megapixels": 0.4746, "pele": False}}
# Receitas que pedem "um corte a cada 2 a 3 s": no exemplo, tomadas de ate CORTE_MAX s (um modelo pequeno copia o JSON do
# exemplo mais do que segue a prosa). Os limites maximos ficam so no texto "Limite por tomada"
CORTE_MAX = 3.5
# Textos do exemplo de regras(); as duracoes saem dos limites da resolucao (e dos cortes da receita)
_EXEMPLO_IMAGEM = [("The character smiles and waves at the camera while talking.", "Oi, gente! Olha só que novidade.", "aproximar"),
                   ("The character points to the side and nods.", "Chegou internet nova aqui.", "acompanhar"),
                   ("The character gives a thumbs up and smiles.", "Corre lá e aproveita!", "afastar")]
_EXEMPLO_CENA = [("A router on a shelf blinks its green lights.", "", "aproximar"),
                 ("A young woman sits on the sofa and smiles at her phone.", "Agora sim, internet de verdade.", "acompanhar")]
_CENA_EXEMPLO = "Realistic live-action commercial look, a bright modern living room, natural daylight, a young woman in a green sweater"


def receitas():
    return json.loads(RECEITAS.read_text(encoding="utf-8"))


def _br(x):
    return f"{float(x):g}".replace(".", ",")


def com_qualidade(receita: dict, qualidade: str) -> dict:
    """Copia da receita com os ajustes da qualidade por cima (o resto vem da receita). Qualidade desconhecida: Erro."""
    if not isinstance(qualidade, str) or qualidade not in QUALIDADES:
        raise Erro(f"Qualidade desconhecida. Use uma destas: {', '.join(QUALIDADES)}.")
    r = copy.deepcopy(receita)
    r["ajustes"].update(QUALIDADES[qualidade])
    return r


def nome_qualidade(qualidade: str, ajustes: dict) -> str:
    """Ex.: "qualidade UGC (1,1 MP, pele natural)" ou "qualidade rápida (0,47 MP)"."""
    mp = _br(round(float(ajustes.get("megapixels", 0.4746)), 2))
    if qualidade == "rapido":
        return f"qualidade rápida ({mp} MP)"
    return f"qualidade UGC ({mp} MP" + (", pele natural" if ajustes.get("pele") else "") + ")"


def com_cortes(receita: dict) -> bool:
    """A receita pede um corte a cada 2 a 3 s (campo "cortes": fala_camera, podcast, anuncio_vertical)?"""
    return receita.get("cortes") is True


def exemplo_tomadas(receita: dict) -> list:
    """Tomadas validas para a receita (ja com a qualidade aplicada). Com cortes: tres tomadas curtas, a maior duracao
    aceita ate CORTE_MAX, a menor e de novo a maior (ex.: 3,5 + 3 + 3,5). Sem cortes: duas, a tomada 1 no limite dela e
    a 2 no limite das seguintes."""
    mp = float(receita["ajustes"].get("megapixels", 0.4746))
    if com_cortes(receita):
        curtas = [d for d in duracoes_permitidas(mp, primeira=False) if d <= CORTE_MAX]
        duracoes = [max(curtas), min(curtas), max(curtas)]
    else:
        duracoes = [max(duracoes_permitidas(mp)), max(duracoes_permitidas(mp, primeira=False))]
    textos = _EXEMPLO_IMAGEM if receita["com_imagem"] else _EXEMPLO_CENA
    return [{"acao": acao, "fala": fala, "som": "soft room tone", "camera": camera, "duracao": d}
            for (acao, fala, camera), d in zip(textos, duracoes)]


def regras(rid: str, receita: dict, qualidade: str) -> str:
    """O texto de regras_das_tomadas: limites na resolucao da qualidade, duracoes e cameras aceitas, a instrucao da
    receita, o regras_tomadas.md, a cena (obrigatoria sem imagem) e um exemplo de tomadas em JSON."""
    mp = float(receita["ajustes"].get("megapixels", 0.4746))
    linhas = [f"Regras das tomadas: receita {rid} ({receita['nome']}), {nome_qualidade(qualidade, receita['ajustes'])}.",
              f"Receita: {receita['instrucao']}",
              f"Limite por tomada a {_br(mp)} MP: tomada 1 até {_br(duracao_maxima(mp))} s; "
              f"tomadas 2 em diante até {_br(duracao_maxima(mp, primeira=False))} s.",
              f"Durações aceitas (s): tomada 1: {', '.join(map(_br, duracoes_permitidas(mp)))}; "
              f"tomadas 2 em diante: {', '.join(map(_br, duracoes_permitidas(mp, primeira=False)))}.",
              f"Câmeras aceitas: {', '.join(CAMERAS)}.",
              f"De 1 a {MAX_TOMADAS} tomadas. A duração do vídeo é a soma das tomadas."]
    if receita["com_imagem"] and not receita["ajustes"].get("pele"):
        linhas.append("Cena: não mande; nesta qualidade a tomada 1 e o lugar saem da imagem do personagem ou da foto.")
    elif receita["com_imagem"]:
        padrao = f"o lugar desta receita: \"{receita['lugar']}\"" if receita.get("lugar") else "o padrão do estúdio (um cômodo claro)"
        linhas.append("Cena (opcional): onde acontece, o lugar atrás da pessoa, em inglês: lugar e luz. A tomada 1 parte da imagem do "
                      f"personagem ou da foto; a cena só diz o lugar em volta. Sem cena, vale {padrao}. Mande só se o usuário pedir outro lugar.")
    else:
        linhas.append("Cena: obrigatória (sem imagem), em inglês: estilo, lugar e luz, e quem aparece. "
                      f"Exemplo: \"{_CENA_EXEMPLO}\".")
    linhas += ["", REGRAS.read_text(encoding="utf-8").strip(), "",
               "Exemplo de tomadas (JSON válido para esta receita e qualidade):",
               json.dumps(exemplo_tomadas(receita), ensure_ascii=False, indent=1), "",
               "Depois, chame planejar_video com estas mesmas receita e qualidade, o formato, o personagem (ou a foto)"
               + ("" if receita["com_imagem"] else ", a cena") + " e as tomadas que você escreveu."]
    return "\n".join(linhas)


class Planos:
    """Planos na memoria do servidor: codigo -> pedido pronto para acoes.acao_iniciar_imagem."""

    def __init__(self):
        self._itens = {}
        self._trava = threading.Lock()

    def criar(self, pedido: dict, resumo: str) -> str:
        with self._trava:
            agora = time.time()
            for c in [c for c, x in self._itens.items() if agora - x["criado"] > 4 * VALIDADE]:
                del self._itens[c]
            codigo = secrets.token_hex(3)
            while codigo in self._itens:
                codigo = secrets.token_hex(3)
            self._itens[codigo] = {"pedido": copy.deepcopy(pedido), "resumo": resumo, "criado": agora, "usado": False}
            return codigo

    def usar(self, codigo: str) -> dict:
        with self._trava:
            x = self._itens.get(str(codigo or "").strip().lower())
            if x is None:
                raise Erro("Plano não encontrado. Peça para planejar de novo.", 404)
            if x["usado"]:
                raise Erro("Este plano já foi confirmado.", 409)
            if time.time() - x["criado"] > VALIDADE:
                raise Erro("Este plano expirou. Peça para planejar de novo.", 410)
            x["usado"] = True
            return copy.deepcopy(x["pedido"])

    def devolver(self, codigo: str):
        """O inicio falhou (ComfyUI desligado, por exemplo): o plano pode ser confirmado de novo, dentro da validade."""
        with self._trava:
            x = self._itens.get(str(codigo or "").strip().lower())
            if x:
                x["usado"] = False


planos = Planos()


def resumo(pedido: dict, qualidade: str | None = None) -> str:
    """Uma linha geral e uma por tomada, para o operador mostrar ao usuario antes de confirmar. Com `qualidade`, a linha
    geral diz qual (nome_qualidade)."""
    a = pedido.get("ajustes") or {}
    tomadas = a.get("tomadas") or []
    formato = next((k for k, v in FORMATOS.items() if v == a.get("proporcao")), a.get("proporcao") or "?")
    total = sum(float(t["duracao"]) for t in tomadas)
    pers = pedido.get("personagem")
    if pers:
        import personagens
        try:
            quem = f"personagem {personagens.ler(pers['id']).get('nome') or pers['id']}"
        except (OSError, ValueError, KeyError):
            quem = f"personagem {pers.get('id')}"
    elif pedido.get("foto"):
        quem = f"foto {pedido['foto']}"
    else:
        quem = "sem imagem"
    linhas = [f"vídeo {formato}, {_br(total)} s, {quem}, {len(tomadas)} {'tomada' if len(tomadas) == 1 else 'tomadas'}"
              + (f", {nome_qualidade(qualidade, a)}" if qualidade else "")]
    if pers or pedido.get("foto"):
        # Com imagem, a cena e o lugar atras da pessoa, e so a pele natural usa (imagem_para_video.prompt_pele); vazia, um
        # comodo claro. Sem a pele (qualidade rapido) o lugar sai da imagem: nao entra no resumo
        if a.get("pele"):
            linhas.append(f"Onde: {a.get('cena') or 'o padrão do estúdio (um cômodo claro)'}")
    elif a.get("cena"):
        linhas.append(f"cena: {a['cena']}")
    for i, t in enumerate(tomadas, 1):
        fala = (t.get("fala") or "").strip()
        linhas.append(f"{i}) {_br(t['duracao'])} s, câmera {t['camera']}: {fala or '(sem fala) ' + (t.get('acao') or '').strip()}")
    return "\n".join(linhas)
