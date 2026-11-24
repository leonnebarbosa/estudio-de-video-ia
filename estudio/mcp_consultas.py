"""Ferramentas do MCP que consultam o estudio: estado, personagens, projetos, andamento, parar, retomar e resultado.
Cada resultado e um texto curto, nunca o JSON bruto (o agente que le pode ser um LLM pequeno)."""
import io, re, subprocess, tempfile, time
from pathlib import Path

import config
import acoes, ambiente, links, personagens, planos, projetos, recursos, tarefa, validacao
from erros import Erro
import mcp_servidor
from mcp_servidor import imagem, texto

MAX_PROJETOS = 10


def ver_estado(_argumentos):
    """De 2 a 4 linhas: ComfyUI, geracao em andamento, fila e placa."""
    c = ambiente.comfy()
    linhas = ["ComfyUI: " + ("ligado" + (", ocupado" if c.get("ocupado") else ", livre") if c.get("ligado") else "desligado")]
    t = tarefa.tarefa.resumo()
    if t and t.get("rodando"):
        linhas.append(f"Gerando: projeto {t.get('projeto')} ({t.get('modo')}), etapa {t.get('etapa') or 'iniciando'}, há {t.get('segundos')} s.")
    elif t:
        linhas.append(f"Última geração: projeto {t.get('projeto')}, " + ("parada pelo usuário." if t.get("parada") else f"terminou com código {t.get('codigo')}."))
    else:
        linhas.append("Nenhuma geração desde que o estúdio ligou.")
    f = tarefa.tarefa.fila.resumo()
    linhas.append(f"Fila: {len(f['itens'])} pedido(s)" + (f", pausada ({f['motivo']})." if f.get("pausada") and f.get("motivo") else ", pausada." if f.get("pausada") else "."))
    g = (recursos.lidos() or {}).get("gpu")
    if g:
        linhas.append(f"Placa: {g['uso']}% de uso, {g['memoria']}/{g['memoria_total']} MiB, {g['temp']} °C.")
    return [texto("\n".join(linhas))]


def listar_personagens(_argumentos):
    lista = personagens.listar()
    if not lista:
        return [texto("Nenhum personagem na biblioteca. Para criar um a partir de uma foto, chame criar_personagem (a foto vem de pedir_envio); o usuário também cria pela página do estúdio (menu Personagem).")]
    nomes = {p["id"]: p.get("nome") or p["id"] for p in lista}
    linhas = [f"{p['id']}: {nomes.get(p.get('pessoa'), p.get('nome') or p['id'])} · {p.get('visual') or 'Original'}"
              + ("" if p.get("pronto", True) else " (frente ainda não aprovada)")
              + (f" ({p['descricao']})" if p.get("descricao") else "") for p in lista]
    return [texto("\n".join(linhas) + "\nUse o id (antes dos dois-pontos) no campo personagem do planejar_video.")]


# O tipo interno engana o agente (projeto de imagem e "texto", vídeo de receita e "imagem"): ele ve so "vídeo" e "imagem"
ROTULO_PROJETO = {"texto": "imagem", "imagem": "vídeo", "wan": "vídeo", "troca": "vídeo (troca)", "editar": "vídeo (edição)"}

def listar_projetos(_argumentos):
    lista = projetos.listar_projetos()[:MAX_PROJETOS]
    if not lista:
        return [texto("Nenhum projeto ainda.")]
    linhas = [f"{p['nome']}: {ROTULO_PROJETO.get(p.get('tipo'), 'vídeo') if p.get('tipo') else 'vídeo (continuação)'}, {time.strftime('%d/%m %H:%M', time.localtime(p['quando']))}, "
              + ("pronto" if p.get("final") or (p.get("tipo") == "texto" and p.get("completo")) else "incompleto") for p in lista]
    return [texto("\n".join(linhas) + "\nUse ver_resultado com o nome de um projeto pronto para ver o vídeo ou as imagens.")]


INTERVALO_ANDAMENTO = 30  # segundos; quem consulta de novo antes disso recebe a ordem de parar
_ultima_consulta = [float("-inf")]  # time.monotonic() da ultima consulta com geracao em andamento


def ver_andamento(_argumentos):
    t = tarefa.tarefa.resumo()
    if not t or not t.get("rodando"):
        return [texto("Nada gerando agora.")]
    # Um agente local consultou mais de 70 vezes em 5 minutos: a resposta diz quanto falta e manda esperar o usuario
    agora = time.monotonic()
    desde, _ultima_consulta[0] = agora - _ultima_consulta[0], agora
    partes = [f"etapa {t.get('etapa') or 'iniciando'}"]
    pr = t.get("progresso") or {}
    if pr.get("tomada") and pr.get("total"):
        partes.append(f"tomada {pr['tomada']} de {pr['total']}")
    elif pr.get("imagem"):
        partes.append(f"imagem {pr['imagem']}" + (f" de {pr['total']}" if pr.get("total") else ""))
    if pr.get("maximo"):
        partes.append(f"passo {pr.get('valor') or 0} de {pr['maximo']}")
    partes.append(f"há {t.get('segundos')} s")
    try:
        resta = (float(pr["maximo"]) - float(pr.get("valor") or 0)) * float(pr["s_passo"])
    except (KeyError, TypeError, ValueError):
        resta = 0
    if resta > 0:
        partes.append(f"faltam cerca de {max(1, round(resta / 60))} min de geração nesta tomada")
    if desde < INTERVALO_ANDAMENTO:
        conselho = (f"Pare de consultar: você já perguntou há {int(desde)} s. Diga ao usuário que está gerando e "
                    "só chame ver_andamento de novo quando ele perguntar.")
    else:
        conselho = "Diga isso ao usuário e espere ele perguntar de novo; não fique consultando."
    return [texto(f"Gerando {t.get('projeto')}: {', '.join(partes)}. {conselho}")]


def parar_geracao(_argumentos):
    """Para a geracao e pausa a fila, com a trava da tarefa como acoes.acao_fila: o proximo da fila nao comeca no meio."""
    t = tarefa.tarefa
    with t.trava:
        projeto = t.projeto if t.rodando() else None
        t.parar()
        t.fila.pausar("Parado pelo agente (MCP).")
    if projeto:
        return [texto(f"Parei a geração de {projeto} e pausei a fila. Nada novo começa até alguém chamar retomar_fila.")]
    return [texto("Nada estava gerando. Pausei a fila: nada novo começa até alguém chamar retomar_fila.")]


def retomar_fila(_argumentos):
    r = acoes.acao_fila({"acao": "continuar"})
    n = len(r.get("itens") or [])
    if not n:
        return [texto("Fila retomada. Não há pedidos esperando.")]
    return [texto(f"Fila retomada. {n} pedido(s) esperando; o próximo começa sozinho quando a placa estiver livre.")]


def _ler_final(video):
    """Duracao (s) e ultimo quadro (PNG, ate 768 px de largura) do video, com o ffmpeg do imageio_ffmpeg (o mesmo do
    acabamento.py). O que nao der para ler volta None: (None, None) sem ffmpeg."""
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None, None
    with tempfile.TemporaryDirectory() as d:
        saida = Path(d) / "quadro.png"
        # -sseof -1: decodifica so o ultimo segundo; -update 1 deixa no arquivo o ultimo quadro lido
        cmd = [exe, "-hide_banner", "-nostdin", "-y", "-sseof", "-1", "-i", str(video), "-vf", "scale='min(768,iw)':-2", "-update", "1", str(saida)]
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=60, creationflags=config.SEM_JANELA)
        except (OSError, subprocess.SubprocessError):
            return None, None
        m = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", (r.stderr or b"").decode("utf-8", "replace"))
        segundos = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else None
        try:
            png = saida.read_bytes() or None
        except OSError:
            png = None
    return segundos, png


def _pasta_do_projeto(a):
    """(nome, pasta) do projeto pedido, ou Erro 404 mandando para listar_projetos."""
    nome = str(a.get("projeto") or "").strip()
    pasta = validacao.pasta_projeto(nome)
    if not pasta.is_dir():
        raise Erro(f"O projeto '{nome}' não existe. Chame listar_projetos para ver os nomes.", 404)
    return nome, pasta


def _projeto_de_imagem(pasta):
    """O projeto lido (projetos.ler_projeto) se for de imagem (texto para imagem ou edicao); senao None."""
    p = projetos.ler_projeto(pasta)
    return p if p and p.get("tipo") == "texto" else None


def _miniatura(arquivo):
    """A imagem em PNG com ate 768 px de largura, para o agente ver; None se nao abrir."""
    try:
        from PIL import Image
        with Image.open(arquivo) as im:
            im = im.convert("RGB")
            if im.width > 768:
                im = im.resize((768, round(im.height * 768 / im.width)))
            saida = io.BytesIO()
            im.save(saida, "PNG")
            return saida.getvalue()
    except Exception:
        return None


def _parou(nome, p):
    """O projeto de imagem esta incompleto e nao esta rodando nem na fila? Entao a geracao parou no meio (queda, parada, falha)
    e esperar nao adianta: as imagens que faltam so saem pela pagina."""
    rodando = tarefa.tarefa.rodando() and tarefa.tarefa.projeto == nome
    return not p["completo"] and not rodando and not acoes.na_fila(nome)


def _resultado_de_imagem(nome, pasta, p):
    prontas, total = p["imagens"], p["total"]
    parou = _parou(nome, p)
    if not p["completo"] and not parou:
        return [texto(f"Ainda não terminou: {len(prontas)} de {total} imagens prontas. Diga isso ao usuário e espere; "
                      "não chame ver_resultado de novo agora.")]
    if parou and not prontas:
        return [texto("A geração parou sem nenhuma imagem pronta. Planeje de novo ou veja na página do estúdio.")]
    base = mcp_servidor.base_atual()
    if parou:
        linhas = [f"A geração parou em {len(prontas)} de {total} imagens. Continuar é pela página do estúdio."]
    else:
        linhas = [f"Pronto: {nome}, {len(prontas)} {'imagem' if len(prontas) == 1 else 'imagens'}."]
    for i in prontas:
        # Um link por imagem: a chave operador so abre o /mcp (o /imagem/ daria 403)
        arquivo_baixado = f"{nome}_{i['n']}.png"
        link = f"{base}/m/{links.criar_baixar(pasta / i['arquivo'], arquivo_baixado)}"
        linhas.append(f"Imagem {i['n']}: {link} (vale pelo menos 30 minutos)")
    linhas.append("Passe os links ao usuário exatamente como vieram. Para usar uma imagem em outra geração, chame usar_resultado.")
    png = _miniatura(pasta / prontas[0]["arquivo"]) if prontas else None
    t = texto("\n".join(linhas) + (" A imagem mostrada é a primeira." if png else ""))
    return [t, imagem(png)] if png else [t]


def ver_resultado(a):
    nome, pasta = _pasta_do_projeto(a)
    de_imagem = _projeto_de_imagem(pasta)
    if de_imagem:
        return _resultado_de_imagem(nome, pasta, de_imagem)
    final = pasta / "final.mp4"
    if not final.is_file():
        return [texto("Ainda não terminou.")]
    segundos, png = _ler_final(final)
    duracao = f", {planos._br(round(segundos, 1))} s" if segundos else ""
    # A chave operador so abre o /mcp (o /video/ daria 403): os dois niveis baixam pelo link temporario
    link = f"{mcp_servidor.base_atual()}/m/{links.criar_baixar(final, f'{nome}.mp4')}"
    linha = f'Pronto: {nome}{duracao}. Baixar: {link} (vale pelo menos 30 minutos). Com terminal: curl -o {nome}.mp4 "{link}".'
    if not png:
        return [texto(linha + " Não consegui tirar o último quadro.")]
    return [texto(linha + " A imagem é o último quadro."), imagem(png)]
