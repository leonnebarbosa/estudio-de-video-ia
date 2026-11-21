"""Ferramentas do MCP do estudio (registradas em mcp_servidor ao importar este arquivo).
Quem usa o nivel operador e o agente que conversa com o usuario (cliente MCP), as vezes um LLM pequeno: cada descricao diz
quando usar, quando nao usar e traz um exemplo, e cada resultado e um texto curto, nunca o JSON bruto. O agente escreve as
tomadas seguindo regras_das_tomadas; o estudio so confere. As ferramentas do nivel operador nao apagam nada; o chamar_api
do nivel completo pode apagar, com confirmar: true, como a pagina."""
import re, secrets, subprocess, sys, tempfile, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config
import acoes, ambiente, personagens, planos, projetos, recursos, tarefa, validacao
from envio import nome_limpo
from erros import Erro
from imagem_para_video import CAMERAS, DURACOES
import mcp_servidor
from mcp_servidor import imagem, registrar, texto

AMBOS = {"operador", "completo"}
SEM_ARGUMENTOS = {"type": "object", "properties": {}}
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
        return [texto("Nenhum personagem na biblioteca. O usuário cria personagens pela página do estúdio (menu Personagem).")]
    linhas = [f"{p['id']}: {p.get('nome') or p['id']}" + (f" ({p['descricao']})" if p.get("descricao") else "") for p in lista]
    return [texto("\n".join(linhas) + "\nUse o id (antes dos dois-pontos) no campo personagem do planejar_video.")]


def listar_projetos(_argumentos):
    lista = projetos.listar_projetos()[:MAX_PROJETOS]
    if not lista:
        return [texto("Nenhum projeto ainda.")]
    linhas = [f"{p['nome']}: {p.get('tipo') or 'continuação'}, {time.strftime('%d/%m %H:%M', time.localtime(p['quando']))}, "
              + ("pronto" if p.get("final") else "incompleto") for p in lista]
    return [texto("\n".join(linhas) + "\nUse ver_resultado com o nome de um projeto pronto para ver o vídeo.")]


def ver_andamento(_argumentos):
    t = tarefa.tarefa.resumo()
    if not t or not t.get("rodando"):
        return [texto("Nada gerando agora.")]
    partes = [f"etapa {t.get('etapa') or 'iniciando'}"]
    pr = t.get("progresso") or {}
    if pr.get("tomada") and pr.get("total"):
        partes.append(f"tomada {pr['tomada']} de {pr['total']}")
    elif pr.get("imagem"):
        partes.append(f"imagem {pr['imagem']}" + (f" de {pr['total']}" if pr.get("total") else ""))
    if pr.get("maximo"):
        partes.append(f"passo {pr.get('valor') or 0} de {pr['maximo']}")
    partes.append(f"há {t.get('segundos')} s")
    return [texto(f"Gerando {t.get('projeto')}: {', '.join(partes)}.")]


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


def ver_resultado(a):
    nome = str(a.get("projeto") or "").strip()
    pasta = validacao.pasta_projeto(nome)
    if not pasta.is_dir():
        raise Erro(f"O projeto '{nome}' não existe. Chame listar_projetos para ver os nomes.", 404)
    final = pasta / "final.mp4"
    if not final.is_file():
        return [texto("Ainda não terminou.")]
    segundos, png = _ler_final(final)
    duracao = f", {planos._br(round(segundos, 1))} s" if segundos else ""
    if mcp_servidor.nivel_atual() == "completo":
        linha = f"Pronto: {nome}{duracao}. Vídeo: /video/{nome}/final.mp4 (no endereço do estúdio)."
    else:
        # A chave operador so abre o /mcp: o endereco do video daria 403
        linha = f"Pronto: {nome}{duracao}. Para ver o vídeo, abra na página do estúdio, em Projetos."
    if not png:
        return [texto(linha + " Não consegui tirar o último quadro.")]
    return [texto(linha + " A imagem é o último quadro."), imagem(png)]


registrar("ver_estado",
          "Mostra como está o estúdio em poucas linhas: se o ComfyUI está ligado, o que está sendo gerado, a fila e o uso da placa. "
          "Quando usar: sempre no começo da conversa e antes de planejar um vídeo. "
          "Quando não usar: para saber a tomada e o passo da geração atual (use ver_andamento). "
          "Exemplo: ver_estado {}.", SEM_ARGUMENTOS, AMBOS, ver_estado)

registrar("listar_personagens",
          "Lista os personagens da biblioteca, um por linha, no formato id: nome. "
          "Quando usar: antes de planejar_video com as receitas fala_camera, podcast ou anuncio_vertical, para achar o id do personagem. "
          "Quando não usar: na receita cena_texto, que não usa personagem. Nunca invente um personagem que não está na lista. "
          "Exemplo: listar_personagens {}.", SEM_ARGUMENTOS, AMBOS, listar_personagens)

registrar("listar_projetos",
          f"Lista os {MAX_PROJETOS} projetos mais recentes com nome, tipo, data e se está pronto ou incompleto. "
          "Quando usar: quando o usuário perguntar pelos vídeos feitos ou quiser ver um vídeo antigo (depois use ver_resultado com o nome). "
          "Quando não usar: para saber o que está gerando agora (use ver_andamento). "
          "Exemplo: listar_projetos {}.", SEM_ARGUMENTOS, AMBOS, listar_projetos)

registrar("ver_andamento",
          "Diz o que a geração atual está fazendo: o projeto, a etapa, a tomada, o passo e há quantos segundos começou. "
          "Quando usar: quando o usuário perguntar \"já terminou?\" ou \"como está o vídeo?\" depois de confirmar_plano. "
          "Quando não usar: para ver o vídeo pronto (use ver_resultado). "
          "Exemplo: ver_andamento {}.", SEM_ARGUMENTOS, AMBOS, ver_andamento)

registrar("parar_geracao",
          "Para a geração que está rodando e pausa a fila, para nada novo começar sozinho. "
          "Quando usar: quando o usuário pedir para parar, cancelar ou \"para tudo\". "
          "Quando não usar: para apagar um projeto (não é possível por aqui) ou só para ver o estado (use ver_estado). "
          "Exemplo: parar_geracao {}.", SEM_ARGUMENTOS, AMBOS, parar_geracao)

registrar("retomar_fila",
          "Tira a pausa da fila: o próximo pedido começa sozinho quando a placa estiver livre. "
          "Quando usar: só quando o usuário pedir para continuar a fila (por exemplo, depois de parar_geracao). "
          "Quando não usar: para começar um vídeo novo (use planejar_video e confirmar_plano). "
          "Exemplo: retomar_fila {}.", SEM_ARGUMENTOS, AMBOS, retomar_fila)

registrar("ver_resultado",
          "Mostra o resultado de um projeto: se terminou, a duração, onde ver o vídeo e o último quadro como imagem. "
          "Quando usar: depois que ver_andamento disser \"Nada gerando agora.\", com o nome do projeto que confirmar_plano devolveu, "
          "ou com um nome de listar_projetos. "
          "Quando não usar: para saber o passo de uma geração em andamento (use ver_andamento). "
          "Exemplo: {\"projeto\": \"mcp_podcast_20261121_153000\"}.",
          {"type": "object", "properties": {"projeto": {"type": "string", "description": "Nome do projeto (de confirmar_plano ou listar_projetos)."}},
           "required": ["projeto"]}, AMBOS, ver_resultado)


def listar_receitas(_argumentos):
    linhas = [f"{rid}: {r['nome']}. {r['uso']}" + ("" if r["com_imagem"] else " Sem personagem nem foto.")
              for rid, r in planos.receitas().items()]
    return [texto("\n".join(linhas + ["Duração: a soma das tomadas (veja regras_das_tomadas)."]))]


def _achar_personagem(nome):
    """Pelo id ou pelo nome, sem diferenciar maiusculas. Inexistente: Erro com os ids disponiveis."""
    lista = personagens.listar()
    alvo = str(nome).strip().casefold()
    achado = next((p for p in lista if p["id"].casefold() == alvo), None) or next((p for p in lista if str(p.get("nome") or "").strip().casefold() == alvo), None)
    if achado is None:
        ids = ", ".join(p["id"] for p in lista) or "nenhum"
        raise Erro(f"O personagem '{nome}' não existe. Os disponíveis são: {ids}. Chame listar_personagens se precisar.", 404)
    return achado


def _receita(a):
    """(id, receita com a qualidade aplicada, qualidade) dos argumentos. Receita ou qualidade desconhecida: Erro."""
    todas = planos.receitas()
    rid = a.get("receita")
    if rid not in todas:
        raise Erro(f"Receita desconhecida. Use uma destas: {', '.join(todas)}. Chame listar_receitas se precisar.")
    # Sem qualidade, "ugc": a receita como esta. "rapido" troca a resolucao e a pele, e com elas os limites das tomadas
    qualidade = a.get("qualidade") or "ugc"
    return rid, planos.com_qualidade(todas[rid], qualidade), qualidade


def regras_das_tomadas(a):
    rid, receita, qualidade = _receita(a)
    return [texto(planos.regras(rid, receita, qualidade))]


REVER_REGRAS = "Chame regras_das_tomadas para ver os limites desta receita."


def planejar_video(a):
    rid, receita, qualidade = _receita(a)
    formato = a.get("formato")
    if formato not in planos.FORMATOS:
        raise Erro(f"Formato desconhecido. Use um destes: {', '.join(planos.FORMATOS)}.")
    fixo = receita["ajustes"].get("proporcao")
    if fixo and fixo != planos.FORMATOS[formato]:
        raise Erro(f"A receita {rid} é sempre {next(k for k, v in planos.FORMATOS.items() if v == fixo)}. Peça de novo nesse formato.")
    pers, foto = None, None
    if receita["com_imagem"]:
        if a.get("personagem"):
            pers = {"id": _achar_personagem(a["personagem"])["id"]}
        if a.get("foto"):
            foto = nome_limpo(str(a["foto"]))
            if not foto or not (config.ENTRADA / foto).is_file():
                raise Erro("Foto não encontrada na entrada do estúdio. Envie a foto pela página ou use um personagem.", 404)
        if not pers and not foto:
            raise Erro("Esta receita precisa de um personagem. Chame listar_personagens.")
    elif a.get("personagem") or a.get("foto"):
        raise Erro(f"A receita {rid} não usa personagem nem foto. Para um personagem, use fala_camera, podcast ou anuncio_vertical.")
    if receita["ajustes"].get("pele"):
        # Antes das tomadas: sem os arquivos da pele natural nada adianta corrigir nelas
        faltam = validacao.faltam_pele()
        if faltam:
            raise Erro(f"Faltam arquivos da pele natural no ComfyUI: {', '.join(faltam)}. A receita {rid} usa a pele natural; "
                       "a qualidade rapido funciona sem ela.")
    mp = float(receita["ajustes"].get("megapixels", 0.4746))
    try:
        # A mesma conferencia da pagina; o preparar_imagem abaixo repete, mas aqui a mensagem ganha o lembrete das regras.
        # So nestes erros: os de foto, personagem ou ComfyUI nao se corrigem nas tomadas
        tomadas = validacao.validar_tomadas(a.get("tomadas"), DURACOES, True)
        validacao.validar_duracoes_h3(tomadas, mp)
    except Erro as e:
        raise Erro(f"{e.mensagem} {REVER_REGRAS}", e.codigo)
    # Com imagem, a cena e onde acontece (o lugar atras da pessoa na pele natural): a do agente, senao o lugar da receita,
    # senao vazia (o estudio usa um comodo claro). Sem imagem, e a cena inteira e e obrigatoria
    cena = " ".join(str(a.get("cena") or "").split())
    if receita["com_imagem"]:
        cena = cena or receita.get("lugar", "")
    elif not cena:
        raise Erro("Sem imagem, o campo cena é obrigatório: descreva em inglês o estilo, o lugar e a luz.")
    ajustes = {**receita["ajustes"], "proporcao": planos.FORMATOS[formato], "tomadas": tomadas, "cena": cena}
    # O sufixo evita repetir o nome com dois planos no mesmo segundo
    d = {"projeto": f"mcp_{rid}_{time.strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(2)}", "foto": foto, "ajustes": ajustes, "autorizacao": True}
    if pers:
        d["personagem"] = pers
    acoes.preparar_imagem(d)  # a mesma validacao da pagina, sem criar nada
    resumo = planos.resumo(d, qualidade)
    codigo = planos.planos.criar(d, resumo)
    return [texto(f"Plano {codigo} (vale {planos.VALIDADE // 60} min, projeto {d['projeto']}):\n{resumo}\n\n"
                  f"Mostre este resumo ao usuário e espere a resposta. Só chame confirmar_plano com codigo_plano \"{codigo}\" depois que ele aprovar.")]


def confirmar_plano(a):
    codigo = str(a.get("codigo_plano") or "")
    pedido = planos.planos.usar(codigo)
    try:
        acoes.acao_iniciar_imagem(pedido)
    except Exception:
        planos.planos.devolver(codigo)
        raise
    projeto = pedido["projeto"]
    fila = getattr(tarefa.tarefa, "fila", None)
    na_fila = bool(fila) and any(i["projeto"] == projeto for i in fila.resumo()["itens"])
    return [texto(f"Entrou na fila: {projeto}" if na_fila else f"Começou: {projeto}")]


registrar("listar_receitas",
          "Lista as receitas de vídeo: id, nome e para que serve. "
          "Quando usar: antes de planejar_video, para escolher a receita que combina com o pedido do usuário. "
          "Quando não usar: para saber o que está gerando (use ver_estado ou ver_andamento). "
          "Exemplo: listar_receitas {}.", SEM_ARGUMENTOS, AMBOS, listar_receitas)

QUALIDADE = {"type": "string", "enum": list(planos.QUALIDADES), "default": "ugc",
             "description": "\"ugc\" (padrão, 1,1 MP) ou \"rapido\" (teste a 0,47 MP, sem pele natural)."}

registrar("regras_das_tomadas",
          "Devolve as regras para você escrever as tomadas de um vídeo: o limite de segundos por tomada nesta qualidade, as durações "
          "e câmeras aceitas, o máximo de tomadas, o padrão do texto em inglês para o H3, a cena (obrigatória sem imagem; com imagem, "
          "opcional, é onde acontece, com o lugar padrão da receita) e um exemplo de tomadas "
          "pronto. Qualidade: \"ugc\" é o padrão (1,1 MP, pele natural nas receitas com personagem; demora mais e fica mais bonito); "
          "\"rapido\" é um teste a 0,47 MP sem pele natural, só quando o usuário pedir algo rápido, um teste ou um rascunho "
          "(\"faz um rápido só pra ver\" → \"rapido\"). "
          "Quando usar: depois de escolher a receita e antes de planejar_video, sempre que for escrever ou corrigir tomadas. "
          "Quando não usar: para gerar o vídeo (isso é planejar_video e depois confirmar_plano). "
          "Exemplo: {\"receita\": \"fala_camera\", \"qualidade\": \"ugc\"}.",
          {"type": "object", "properties": {
              "receita": {"type": "string", "enum": list(planos.receitas()), "description": "Id da receita (listar_receitas)."},
              "qualidade": QUALIDADE},
           "required": ["receita"]}, AMBOS, regras_das_tomadas)

registrar("planejar_video",
          "Planeja um vídeo sem gerar nada: você manda as tomadas que escreveu seguindo regras_das_tomadas e o estúdio confere com a mesma "
          "validação da página. Devolve um código de plano e um resumo, que você mostra ao usuário antes de confirmar. Nas receitas com "
          "imagem, informe o personagem (id de listar_personagens) ou uma foto já enviada; a cena, opcional, diz onde acontece (em "
          "inglês: lugar e luz) e, sem ela, vale o lugar da receita ou o padrão do estúdio. Na cena_texto, a cena é obrigatória. "
          "A duração do vídeo é a soma das tomadas. Use a mesma qualidade que pediu em regras_das_tomadas. Se recusar, corrija as "
          "tomadas pela mensagem e chame de novo. "
          "Quando usar: quando o usuário pedir um vídeo, depois de regras_das_tomadas. "
          "Quando não usar: antes de chamar regras_das_tomadas para esta receita e qualidade, para saber o que está gerando (use "
          "ver_estado) ou para começar a geração (isso é o confirmar_plano). "
          "Exemplo: {\"receita\": \"anuncio_vertical\", \"personagem\": \"ana\", \"formato\": \"9:16\", \"qualidade\": \"ugc\", "
          "\"tomadas\": [{\"acao\": \"The character smiles and waves at the camera while talking.\", \"fala\": \"A internet chegou!\", "
          "\"som\": \"soft room tone\", \"camera\": \"aproximar\", \"duracao\": 3.5}, {\"acao\": \"The character points to the side and nods.\", "
          "\"fala\": \"Agora é só aproveitar.\", \"som\": \"\", \"camera\": \"acompanhar\", \"duracao\": 3}]}.",
          {"type": "object", "properties": {
              "receita": {"type": "string", "enum": list(planos.receitas()), "description": "Id da receita (listar_receitas)."},
              "personagem": {"type": "string", "description": "Id ou nome do personagem da biblioteca (listar_personagens). Não vale em cena_texto."},
              "foto": {"type": "string", "description": "Nome de uma foto já enviada pela página, no lugar do personagem."},
              "formato": {"type": "string", "enum": list(planos.FORMATOS)},
              "qualidade": QUALIDADE,
              "tomadas": {"type": "array", "minItems": 1, "maxItems": validacao.MAX_TOMADAS,
                          "description": "As tomadas, na ordem, escritas seguindo regras_das_tomadas.",
                          "items": {"type": "object", "properties": {
                              "acao": {"type": "string", "maxLength": validacao.MAX_ACAO, "description": "O que acontece, em inglês, com \"the character\" como sujeito."},
                              "fala": {"type": "string", "maxLength": validacao.MAX_FALA, "description": "A fala em português, ou \"\" sem fala."},
                              "som": {"type": "string", "maxLength": validacao.MAX_SOM, "description": "O som ambiente, em inglês e curto, ou \"\"."},
                              "camera": {"type": "string", "enum": list(CAMERAS)},
                              "duracao": {"type": "number", "enum": list(DURACOES), "description": "Segundos; respeite o limite de regras_das_tomadas."}},
                                    "required": ["acao", "fala", "camera", "duracao"]}},
              "cena": {"type": "string", "maxLength": validacao.MAX_CENA, "description": "Em inglês. Com imagem (opcional): onde acontece, o lugar e a luz atrás da pessoa; "
                                                        "sem ela, o lugar da receita ou o padrão do estúdio. Na cena_texto (obrigatória): o estilo, "
                                                        "o lugar, a luz e quem aparece."}},
           "required": ["receita", "formato", "tomadas"]}, AMBOS, planejar_video)

registrar("confirmar_plano",
          "Começa a geração de um plano de planejar_video, ou põe na fila se já houver uma geração. Um plano vale 30 min e só pode ser "
          "confirmado uma vez. "
          "Quando usar: só depois que o usuário viu o resumo do plano e respondeu que aprova (\"ok\", \"pode gerar\"). "
          "Quando não usar: sem a resposta do usuário, nunca; nem para mudar o plano (chame planejar_video de novo). "
          "Exemplo: {\"codigo_plano\": \"a1b2c3\"}.",
          {"type": "object", "properties": {"codigo_plano": {"type": "string"}}, "required": ["codigo_plano"]}, AMBOS, confirmar_plano)


# --- Nivel completo (o Claude Code): so aparecem para a chave completa ---
COMPLETO = {"completo"}
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


def enviar_arquivo(a):
    import base64, binascii, io
    from envio import receber_arquivo
    b64 = a.get("conteudo_base64")
    if not isinstance(b64, str) or not b64.strip():
        raise Erro("Falta o conteúdo do arquivo em base64 (campo conteudo_base64).")
    # Antes de decodificar: 4 caracteres dao 3 bytes, entao um texto enorme ja passa do limite
    if len(b64) * 3 // 4 > LIMITE_ARQUIVO + 3:
        raise Erro("Arquivo grande demais para o MCP; envie pela página.")
    try:
        dados = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        raise Erro("O conteúdo não é base64 válido.")
    if len(dados) > LIMITE_ARQUIVO:
        raise Erro("Arquivo grande demais para o MCP; envie pela página.")
    r = receber_arquivo(io.BytesIO(dados), len(dados), a.get("tipo"), str(a.get("nome") or ""))
    return [texto(f"Arquivo recebido: {r.get('nome')} ({len(dados)} bytes).")]


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


registrar("chamar_api",
          "Chama uma rota POST /api/ do estúdio, a mesma que a página usa, com a mesma validação e as mesmas confirmações "
          "(para apagar de verdade, mande confirmar: true nos dados). Devolve o JSON da resposta; o erro do estúdio vira erro da ferramenta. "
          "Não liga nem desliga o estúdio (/api/desligar) e não envia arquivos (use enviar_arquivo). "
          "Exemplo: {\"rota\": \"/api/apagar\", \"dados\": {\"projeto\": \"mcp_podcast_20261121_153000\"}}.",
          {"type": "object", "properties": {
              "rota": {"type": "string", "enum": _rotas(), "description": "Rota POST da API do estúdio."},
              "dados": {"type": "object", "description": "Corpo JSON da chamada, como a página manda."}},
           "required": ["rota"]}, COMPLETO, chamar_api)

registrar("enviar_arquivo",
          "Envia uma foto, um vídeo MP4 ou um áudio para o estúdio (mesma validação do envio pela página). Até 20 MB depois de decodificar; "
          "acima disso, o usuário envia pela página. "
          "Exemplo: {\"tipo\": \"foto\", \"nome\": \"rosto.png\", \"conteudo_base64\": \"iVBORw0KGgo...\"}.",
          {"type": "object", "properties": {
              "tipo": {"type": "string", "enum": ["foto", "video", "audio"]},
              "nome": {"type": "string", "description": "Nome do arquivo, com a extensão."},
              "conteudo_base64": {"type": "string", "description": "Conteúdo do arquivo em base64."}},
           "required": ["tipo", "nome", "conteudo_base64"]}, COMPLETO, enviar_arquivo)

registrar("ver_log",
          "Mostra o fim do log do estúdio (logs/estudio.log), para achar o motivo de uma falha. "
          "Exemplo: {\"linhas\": 50}.",
          {"type": "object", "properties": {"linhas": {"type": "integer", "minimum": 1, "maximum": 200, "description": "Quantas linhas do fim."}},
           "required": ["linhas"]}, COMPLETO, ver_log)
