"""Ferramentas do MCP que planejam e confirmam geracoes: receitas, regras das tomadas, modo livre, imagem e confirmar_plano.
O agente escreve as tomadas seguindo regras_das_tomadas; o estudio so confere."""
import secrets, time

import acoes, ambiente, estilos, estimativas, loras as loras_arquivos, midias, palavras_lora, personagens, planos, tarefa, validacao, video_avancado
from erros import Erro
from imagem_para_video import DURACOES, PELE_MODELO, duracoes_permitidas
from texto_para_imagem import MODELOS_TEXTO
from mcp_servidor import texto
from mcp_midias import ERRO_AUDIO, ERRO_CENARIO, ERRO_FOTO, _achar_midia


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
    if rid in (None, ""):
        raise Erro(f"Falta a receita. Mande receita com uma destas: {', '.join(todas)}. É a mesma que você mandou em regras_das_tomadas.")
    if rid not in todas:
        raise Erro(f"Receita desconhecida. Use uma destas: {', '.join(todas)}. Chame listar_receitas se precisar.")
    # Sem qualidade, "ugc": a receita como esta. "rapido" troca a resolucao e a pele, e com elas os limites das tomadas
    qualidade = a.get("qualidade") or "ugc"
    # A resolucao (480p, 540p, 720p, maxima), quando vem, troca so os megapixels; a qualidade segue decidindo a pele natural
    return rid, planos.com_qualidade(todas[rid], qualidade, a.get("resolucao")), qualidade


AJUDA_MODELO = {PELE_MODELO: "luz e cor com mais cara de filme, cena mais rica; mesmo tempo do oficial e fala certa (testado em 20/11)"}
# A semente so vem quando o usuario pede (repetir um video ou uma imagem); sem ela, cada geracao sorteia a sua
MAX_SEMENTE = 2**48 - 10000  # o modo livre soma ate 10000 a semente (validacao.validar_avancado); o mesmo teto vale nos tres


def _semente(a):
    """A semente do pedido (inteiro de 0 a MAX_SEMENTE) ou None sem ela."""
    v = a.get("semente")
    if v in (None, ""):
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v < MAX_SEMENTE:
        raise Erro(f"A semente é um número inteiro de 0 a {MAX_SEMENTE - 1}. Sem pedido do usuário, não mande semente.")
    return v


ERRO_COMFY_OPCOES = "O ComfyUI não respondeu, então não consigo conferir os modelos e as LoRAs. Chame ver_estado e tente de novo."


def _opcoes_video() -> dict:
    """O que o planejar_video aceita, perguntado ao ComfyUI: {"tomada1", "seguintes", "loras"}. Na tomada 1 o ref2va oficial
    nao vale (o padrao dela e o fl2va; validacao.validar_imagem recusa). None se o ComfyUI nao respondeu."""
    o = ambiente.ler_opcoes()
    if not ambiente.opcoes_validas(o):
        return None
    modelos = o.get("modelos") or []
    return {"tomada1": [m for m in modelos if m != validacao.PADRAO["modelo"]], "seguintes": modelos, "loras": o.get("loras_estilo") or []}


def _sem_extensao(nome: str) -> str:
    return nome[:-len(".safetensors")] if nome.lower().endswith(".safetensors") else nome


def _escolher(nome, opcoes, o_que) -> str:
    """O arquivo de `opcoes` que o agente quis dizer: o nome do arquivo com ou sem .safetensors, ou o nome da pagina, sem diferenciar
    maiusculas. Fora da lista: Erro que manda para listar_modelos_video."""
    alvo = _sem_extensao(str(nome or "").strip()).casefold()
    nomes = planos.nomes_modelo()
    for arquivo in opcoes:
        if alvo and alvo in (_sem_extensao(arquivo).casefold(), str(nomes.get(arquivo, "")).casefold()):
            return arquivo
    raise Erro(f"{o_que} '{nome}' não está entre os instalados para isso. Chame listar_modelos_video e use um nome da lista.")


def _modelo_e_loras(a, receita, rid) -> dict:
    """Os ajustes primeira, seguintes e loras do pedido (so os que vieram). A pele natural troca os modelos pelo Singularity em
    todas as tomadas (imagem_para_video.PELE_MODELO): escolher modelo com ela seria ignorado, entao recusa."""
    m1, m2, lista = a.get("modelo_tomada1"), a.get("modelo_seguintes"), a.get("loras")
    if not (m1 or m2 or lista):
        return {}
    if (m1 or m2) and receita["ajustes"].get("pele"):
        raise Erro(f"Nesta receita e qualidade ({rid}, com a pele natural) o estúdio usa o Singularity V2 em todas as tomadas, no lugar "
                   "do modelo escolhido. Para escolher o modelo, use qualidade rapido; as LoRAs de estilo valem nas duas.")
    o = _opcoes_video()
    if o is None:
        raise Erro(ERRO_COMFY_OPCOES)
    saida = {}
    if m1:
        saida["primeira"] = _escolher(m1, o["tomada1"], "O modelo da tomada 1")
    if m2:
        saida["seguintes"] = _escolher(m2, o["seguintes"], "O modelo das tomadas seguintes")
    if lista:
        if not isinstance(lista, list) or len(lista) > validacao.MAX_LORAS_VIDEO:
            raise Erro(f"Use até {validacao.MAX_LORAS_VIDEO} LoRAs de estilo.")
        loras = []
        for item in lista:
            if not isinstance(item, dict):
                raise Erro("Cada LoRA vai como {\"nome\": ..., \"forca\": ...}.")
            forca, arquivo = item.get("forca"), _escolher(item.get("nome"), o["loras"], "A LoRA de estilo")
            # Sem força: a recomendada pelo autor (a mesma que a página põe ao escolher a LoRA), ou 0,8
            loras.append([arquivo, loras_arquivos.forca_recomendada(arquivo) if forca in (None, "") else forca])
        saida["loras"] = loras  # nomes repetidos e forca fora de 0,05 a 1,5: validacao.validar_loras_video, no preparar_imagem
    return saida


def listar_modelos_video(_argumentos):
    o = _opcoes_video()
    if o is None:
        raise Erro(ERRO_COMFY_OPCOES)
    nomes = planos.nomes_modelo()

    def linha(arquivo):
        extra = " · ".join(x for x in (nomes.get(arquivo), AJUDA_MODELO.get(arquivo)) if x)
        return f"- {_sem_extensao(arquivo)}" + (f" ({extra})" if extra else "")

    palavras = {}
    try:
        palavras = {i["nome"]: i for i in palavras_lora.listar()}
    except Exception:
        pass  # sem o cadastro das palavras-chave a lista sai sem elas

    def linha_lora(arquivo):
        p = palavras.get(arquivo) or {}
        chave = ", ".join(p.get("palavras") or [])
        notas = [f"força {loras_arquivos.forca_recomendada(arquivo):g}".replace(".", ",")]
        if chave and p.get("modo") == "fixa":
            notas.append(f"palavra-chave fixa, entra sozinha: {chave}")
        elif chave and p.get("modo") != "nenhuma":
            notas.append(f"frases que combinam com ela; escreva na cena se fizer sentido: {chave}")
        return f"- {_sem_extensao(arquivo)} ({'; '.join(notas)})"

    partes = ["Modelos e LoRAs para o planejar_video (campos modelo_tomada1, modelo_seguintes e loras). Sem eles vale o padrão.",
              "Tomada 1 (modelo_tomada1). Padrão: o fl2va oficial.", *(map(linha, o["tomada1"]) if o["tomada1"] else ["- nenhum outro instalado"]),
              "Tomadas 2 em diante (modelo_seguintes). Padrão: o ref2va oficial.", *map(linha, o["seguintes"]),
              f"LoRAs de estilo (loras, até {validacao.MAX_LORAS_VIDEO}, força de 0,05 a 1,5). Ao lado de cada uma, a força que vale sem "
              "mandar forca: a recomendada pelo autor, ou 0,8 quando ele não recomenda. Com duas juntas, baixe um pouco cada. "
              "Valem em todas as tomadas.", *(map(linha_lora, o["loras"]) if o["loras"] else ["- nenhuma instalada"]),
              "Com a pele natural (qualidade ugc com personagem ou foto, e sempre com audio_fala) o modelo é o Singularity V2 em todas as "
              "tomadas: modelo_tomada1 e modelo_seguintes só valem na qualidade rapido ou na cena_texto. As LoRAs valem sempre.",
              "Exemplo: {\"modelo_tomada1\": \"Minimax-h3_Singularity_ref2va_v2_pruned_int8\", \"loras\": [{\"nome\": \"H3-Cinematic-V2\", \"forca\": 0.8}]}"]
    return [texto("\n".join(partes))]


def _exigir_pele():
    """O modo audio usa a pele natural em qualquer qualidade: sem os arquivos dela, nada adianta corrigir."""
    faltam = validacao.faltam_pele()
    if faltam:
        raise Erro(f"Faltam arquivos da pele natural no ComfyUI: {', '.join(faltam)}. O audio_fala sempre usa a pele natural.")


def _cortes_do_audio(nome, mp):
    """Os cortes do audio nesta resolucao (validacao.cortes_do_audio); os erros de tamanho ganham o proximo passo."""
    try:
        return validacao.cortes_do_audio(nome, mp)[1]
    except Erro as e:
        if "Use até" in e.mensagem:
            raise Erro(f"{e.mensagem} Encurte o áudio e envie de novo (pedir_envio).", e.codigo)
        if "tomadas, mais que" in e.mensagem:
            # So vale sugerir a resolucao menor quando ela de fato da tomadas mais longas
            passo = "Encurte o áudio e envie de novo (pedir_envio)."
            if validacao.max_tomada_audio(0.1) > validacao.max_tomada_audio(mp):
                passo = "Encurte o áudio ou tente baixar a resolução (resolucao 720p, 540p ou 480p: tomadas mais longas)."
            raise Erro(f"{e.mensagem.split(' Encurte')[0]} {passo}", e.codigo)
        raise


def _erro_audio_sem_imagem(rid):
    return Erro(f"O audio_fala só vale nas receitas com imagem (fala_camera, podcast, anuncio_vertical), não na {rid}.")


def _audio_das_regras(a, rid, receita):
    """Para regras_das_tomadas com audio_fala: {"nome", "cortes"} (receita ja com a pele ligada)."""
    if not receita["com_imagem"]:
        raise _erro_audio_sem_imagem(rid)
    nome = _achar_midia(a["audio_fala"], "audio", ERRO_AUDIO)
    return {"nome": nome, "cortes": _cortes_do_audio(nome, receita["ajustes"].get("megapixels", 0.4746))}


def regras_das_tomadas(a):
    rid, receita, qualidade = _receita(a)
    audio = None
    if a.get("audio_fala"):
        _exigir_pele()
        receita = planos.com_audio(receita)
        audio = _audio_das_regras(a, rid, receita)
    return [texto(planos.regras(rid, receita, qualidade, audio, a.get("resolucao")))]


REVER_REGRAS = "Chame regras_das_tomadas para ver os limites desta receita."


def planejar_video(a):
    rid, receita, qualidade = _receita(a)
    audio_fala, cenario = a.get("audio_fala") or None, a.get("cenario") or None
    if audio_fala:
        _exigir_pele()  # antes de qualquer outra conferencia: o modo audio usa a pele natural em qualquer qualidade
        receita = planos.com_audio(receita)
    elif cenario:
        raise Erro("A foto do lugar (cenario) só vale junto com audio_fala. Sem áudio, descreva o lugar no campo cena.")
    formato = a.get("formato")
    if formato not in planos.FORMATOS:
        raise Erro(f"Formato desconhecido. Use um destes: {', '.join(planos.FORMATOS)}.")
    fixo = receita["ajustes"].get("proporcao")
    if fixo and fixo != planos.FORMATOS[formato]:
        raise Erro(f"A receita {rid} é sempre {next(k for k, v in planos.FORMATOS.items() if v == fixo)}. Peça de novo nesse formato.")
    if audio_fala and not receita["com_imagem"]:
        raise _erro_audio_sem_imagem(rid)
    pers, foto = None, None
    if receita["com_imagem"]:
        if a.get("personagem"):
            pers = {"id": _achar_personagem(a["personagem"])["id"]}
        if a.get("foto"):
            foto = _achar_midia(a["foto"], "foto", ERRO_FOTO)
        if not pers and not foto:
            raise Erro("Esta receita precisa de um personagem ou de uma foto. Chame listar_personagens ou listar_midias.")
    elif a.get("personagem") or a.get("foto"):
        raise Erro(f"A receita {rid} não usa personagem nem foto. Para um personagem, use fala_camera, podcast ou anuncio_vertical.")
    if receita["ajustes"].get("pele"):
        # Antes das tomadas: sem os arquivos da pele natural nada adianta corrigir nelas
        faltam = validacao.faltam_pele()
        if faltam:
            raise Erro(f"Faltam arquivos da pele natural no ComfyUI: {', '.join(faltam)}. A receita {rid} usa a pele natural; "
                       "a qualidade rapido funciona sem ela.")
    escolha = _modelo_e_loras(a, receita, rid)  # antes das tomadas: um modelo errado nao se corrige nelas
    semente = _semente(a)
    mp = float(receita["ajustes"].get("megapixels", 0.4746))
    if audio_fala:
        # As tomadas sao os cortes do audio (sem duracao); a conferencia delas fica com o preparar_imagem (validar_modo_audio)
        audio_fala = _achar_midia(audio_fala, "audio", ERRO_AUDIO)
        if cenario:
            cenario = _achar_midia(cenario, "foto", ERRO_CENARIO)
        n = len(_cortes_do_audio(audio_fala, mp))
        tomadas = a.get("tomadas")
        if not isinstance(tomadas, list) or len(tomadas) != n:
            um = f"{n} tomada" if n == 1 else f"{n} tomadas"
            raise Erro(f"Este áudio vira {um} nesta resolução; mande {um}. Chame regras_das_tomadas com o audio_fala.")
    else:
        for i, t in enumerate(a.get("tomadas") if isinstance(a.get("tomadas"), list) else [], 1):
            if isinstance(t, dict) and t.get("duracao") in (None, ""):
                raise Erro(f"Falta a duracao na tomada {i}. {REVER_REGRAS}")
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
    ajustes = {**receita["ajustes"], "proporcao": planos.FORMATOS[formato], "tomadas": tomadas, "cena": cena, "semente": semente, **escolha}
    if audio_fala:
        ajustes.update(audio=audio_fala, cenario=cenario)
    # O sufixo evita repetir o nome com dois planos no mesmo segundo
    d = {"projeto": f"mcp_{rid}_{time.strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(2)}", "foto": foto, "ajustes": ajustes, "autorizacao": True}
    if pers:
        d["personagem"] = pers
    try:
        preparado = acoes.preparar_imagem(d)  # a mesma validacao da pagina, sem criar nada
    except Erro as e:
        if audio_fala and e.mensagem.startswith(("Tomada ", "A tomada ")):
            raise Erro(f"{e.mensagem} Chame regras_das_tomadas com o audio_fala.", e.codigo)
        raise
    # No modo audio a duracao de cada tomada vem do corte: o resumo usa as tomadas ja validadas
    mostrar = {**d, "ajustes": {**ajustes, "tomadas": preparado["parametros"]["tomadas"]}} if audio_fala else d
    resumo = planos.resumo(mostrar, qualidade)
    codigo = planos.planos.criar(d, resumo)
    return [texto(f"Plano {codigo} (vale {planos.VALIDADE // 60} min, projeto {d['projeto']}):\n{resumo}\n{estimativas.fila()}\n\n"
                  f"Mostre este resumo ao usuário e espere a resposta. Só chame confirmar_plano com codigo_plano \"{codigo}\" depois que ele aprovar.")]


def _resolucao_livre(a):
    """(nome, megapixels) da resolucao do modo livre; sem ela, 540p."""
    nome = a.get("resolucao") or "540p"
    if nome not in planos.RESOLUCOES:
        raise Erro(f"Resolução desconhecida. Use uma destas: {', '.join(planos.RESOLUCOES)}.")
    return nome, planos.RESOLUCOES[nome]


def regras_do_modo_livre(a):
    nome, _ = _resolucao_livre(a)
    return [texto(planos.regras_livre(nome))]


def _referencias_livres(lista):
    """As referencias do planejar_video_livre no formato do video_avancado: o tipo vem do registro das midias."""
    if not isinstance(lista, list) or not 1 <= len(lista) <= sum(video_avancado.LIMITES.values()):
        raise Erro("Mande de 1 a 15 referências, cada uma com nome e midia. Chame regras_do_modo_livre.")
    saida = []
    for ref in lista:
        if not isinstance(ref, dict) or not isinstance(ref.get("nome"), str) or not isinstance(ref.get("midia"), str):
            raise Erro("Cada referência precisa de nome e midia (texto). Chame regras_do_modo_livre.")
        arquivo = _achar_midia(ref["midia"], None, f"A mídia '{ref['midia']}' não foi encontrada. Chame listar_midias, ou pedir_envio para enviar uma.")
        saida.append({"tipo": midias.tipo_de(arquivo), "nome": ref["nome"], "arquivo": arquivo})
    return saida


def planejar_video_livre(a):
    formato = a.get("formato")
    if formato not in planos.FORMATOS:
        raise Erro(f"Formato desconhecido. Use um destes: {', '.join(planos.FORMATOS)}.")
    _, mp = _resolucao_livre(a)
    semente = _semente(a)
    aceitas = duracoes_permitidas(mp)
    try:
        duracao = float(a.get("duracao"))
    except (TypeError, ValueError):
        duracao = None
    if duracao not in aceitas:
        lista = ', '.join(f"{x:g}".replace('.', ',') for x in aceitas)
        raise Erro(f"Duração não aceita nesta resolução. Use uma destas (s): {lista}. "
                   "Chame regras_do_modo_livre.")
    d = {"projeto": "", "prompt": a.get("prompt"), "referencias": _referencias_livres(a.get("referencias")),
         "proporcao": planos.FORMATOS[formato], "megapixels": mp, "duracao": duracao, "semente": semente, "autorizacao": True}
    try:
        validacao.validar_avancado(d)  # a mesma validacao da pagina
    except Erro as e:
        raise Erro(f"{e.mensagem} Chame regras_do_modo_livre se precisar.", e.codigo)
    # So no MCP (a pagina aceita texto solto): o agente precisa do formato de seis partes e de citar o que enviou
    problema = planos.erro_seis_partes(d["prompt"])
    if problema:
        raise Erro(problema)
    citadas = {m.lower() for m in video_avancado.MENCAO.findall(d["prompt"])}
    soltas = [r for r in d["referencias"] if r["nome"].strip().lower() not in citadas]
    if soltas:
        voz = next((r["nome"] for r in soltas if r["tipo"] == "audio"), None)
        como = (f" A voz entra na frase da fala: Speaking in the exact same voice as @{voz}, with the same pitch and energy, "
                "<Subject 1> (S1) says: <d>[Portuguese (Brazil)] ...</d>." if voz else "")
        raise Erro(f"Referência enviada e não citada no prompt: {', '.join('@' + r['nome'] for r in soltas)}. "
                   f"Cite cada uma como @nome no ponto em que ela entra, ou tire-a de referencias.{como}")
    faltam = video_avancado.faltam()
    if faltam:
        raise Erro(f"Faltam arquivos do MiniMax H3 ref2va no ComfyUI: {', '.join(faltam)}.")
    # O sufixo evita repetir o nome com dois planos no mesmo segundo; projeto que ja existe ganha outro sufixo
    for _ in range(5):
        d["projeto"] = f"mcp_livre_{time.strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(2)}"
        if not validacao.pasta_projeto(d["projeto"]).exists():
            break
    resumo = planos.resumo_livre(d)
    codigo = planos.planos.criar(d, resumo, tipo="livre")
    return [texto(f"Plano {codigo} (vale {planos.VALIDADE // 60} min, projeto {d['projeto']}):\n{resumo}\n{estimativas.fila()}\n\n"
                  f"Mostre este resumo ao usuário e espere a resposta. Só chame confirmar_plano com codigo_plano \"{codigo}\" depois que ele aprovar.")]


CAMPOS_DE_FOTO_DE_OUTRAS = ("foto", "fotos", "imagem", "partida", "referencia", "referencias")


def _plano_de_imagem(a):
    """(pedido, resumo) do planejar_imagem: confere os argumentos, escolhe o modelo pelo numero de imagens e valida com a pagina."""
    # As outras ferramentas usam foto e imagem: um modelo local mandou "foto" aqui e o plano saiu como GERAR do texto, sem a foto
    if any(campo in a for campo in CAMPOS_DE_FOTO_DE_OUTRAS):
        raise Erro("As fotos vão no campo imagens (uma lista de nomes de listar_midias). Chame planejar_imagem de novo com imagens.")
    estilo = a.get("estilo") or None
    if estilo is not None and (not isinstance(estilo, str) or estilo not in estilos.ESTILOS):
        raise Erro(f"Estilo desconhecido. Use um destes: {', '.join(estilos.ESTILOS)}.")
    prompt = a.get("prompt", "") if estilo else a.get("prompt")
    if not isinstance(prompt, str) or (not prompt.strip() and not estilo):
        raise Erro("Escreva o que deve aparecer na imagem (campo prompt).")
    qualidade_alta = a.get("qualidade_alta")
    if qualidade_alta is not None and not isinstance(qualidade_alta, bool):
        raise Erro("qualidade_alta é true ou false.")
    if estilo and qualidade_alta is None:
        # Como na pagina: o realista liga a qualidade alta sozinho quando o Klein 9B esta instalado
        qualidade_alta = estilo == "realista" and not validacao.faltam_texto(estilos.MOTOR_ALTO)
    formato = a.get("formato") or "2:3"
    if formato not in planos.FORMATOS_IMAGEM:
        raise Erro(f"Formato desconhecido. Use um destes: {', '.join(planos.FORMATOS_IMAGEM)}.")
    quantidade = a.get("quantidade", 1)
    if isinstance(quantidade, float) and quantidade.is_integer():
        quantidade = int(quantidade)
    if isinstance(quantidade, bool) or not isinstance(quantidade, int) or not 1 <= quantidade <= 4:
        raise Erro("Gere de 1 a 4 imagens por vez (campo quantidade).")
    lista = a.get("imagens") or []
    if not isinstance(lista, list) or len(lista) > 4 or not all(isinstance(n, str) for n in lista):
        raise Erro("Mande de 0 a 4 nomes de foto em imagens (nomes de listar_midias).")
    fotos = [_achar_midia(n, "foto", f"A foto '{n}' não foi encontrada entre as mídias. Chame listar_midias, ou pedir_envio para enviar uma.") for n in lista]
    if estilo and len(fotos) != 1:
        raise Erro("O estilo muda uma foto só: mande exatamente uma foto em imagens.")
    # Sem imagens gera do texto; com uma edita; com duas a quatro junta (o Qwen cita image 1, image 2... na ordem)
    modelo = "z_image_turbo" if not fotos else "klein_edit" if len(fotos) == 1 else "qwen21_edit"
    ajustes = {"modelo": modelo, "prompt": prompt, "proporcao": planos.FORMATOS_IMAGEM[formato], "megapixels": 0.9, "quantidade": quantidade,
               "passos": MODELOS_TEXTO[modelo]["passos"], "partida": fotos[0] if fotos else None,
               "referencia": fotos[1] if len(fotos) > 1 else None, "referencias": fotos[2:],
               "estilo": estilo, "qualidade_alta": bool(qualidade_alta), "semente": _semente(a)}
    d = {"projeto": "", "ajustes": ajustes}
    for _ in range(5):
        d["projeto"] = f"mcp_imagem_{time.strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(2)}"
        if not validacao.pasta_projeto(d["projeto"]).exists():
            break
    try:
        acoes.preparar_texto(d)  # a mesma conferencia da pagina, sem criar nada nem olhar o ComfyUI
    except Erro as e:
        if e.mensagem.startswith("Faltam arquivos"):
            raise Erro("O modelo desta imagem não está instalado neste estúdio. Diga isso ao usuário; não tente de novo.", e.codigo)
        raise Erro(f"{e.mensagem} Corrija e chame planejar_imagem de novo.", e.codigo)
    return d, planos.resumo_imagem(d)


def planejar_imagem(a):
    d, resumo = _plano_de_imagem(a)
    codigo = planos.planos.criar(d, resumo, tipo="imagem")
    return [texto(f"Plano {codigo} (vale {planos.VALIDADE // 60} min, projeto {d['projeto']}):\n{resumo}\n{estimativas.fila()}\n\n"
                  f"Mostre este resumo ao usuário e espere a resposta. Só chame confirmar_plano com codigo_plano \"{codigo}\" depois que ele aprovar.")]


def confirmar_plano(a):
    codigo = str(a.get("codigo_plano") or "")
    tipo = planos.planos.tipo_de(codigo)
    if tipo not in planos.TIPOS:
        # Um plano gravado por uma versao mais nova do estudio: cair na acao das receitas geraria o que o usuario nao aprovou
        raise Erro("Este plano é de uma versão diferente do estúdio. Planeje de novo.")
    pedido = planos.planos.usar(codigo)
    # Cada tipo de plano inicia a sua geracao: o do modo livre nunca passa pela acao das receitas, e vice-versa
    iniciar = {"livre": acoes.acao_iniciar_avancado, "imagem": acoes.acao_iniciar_texto, "receita": acoes.acao_iniciar_imagem}[tipo]
    try:
        iniciar(pedido)
    except Erro as e:
        # Um agente local leu "Espere terminar" como sucesso e foi buscar o resultado: a mensagem diz que nada comecou
        planos.planos.devolver(codigo)
        raise Erro(f"{e.mensagem} Nada começou: {'a imagem' if tipo == 'imagem' else 'o vídeo'} não está sendo gerad{'a' if tipo == 'imagem' else 'o'} e não existe projeto novo. Diga isso ao usuário. "
                   f"Não chame confirmar_plano de novo agora: espere ele pedir. O plano {codigo} continua valendo até "
                   f"{planos.planos.vale_ate(codigo)}; quando ele pedir, chame ver_estado e, com o ComfyUI livre, confirmar_plano "
                   "com o mesmo codigo_plano.", e.codigo)
    except Exception:
        planos.planos.devolver(codigo)
        raise
    projeto = pedido["projeto"]
    fila = getattr(tarefa.tarefa, "fila", None)
    resumo = fila.resumo() if fila else {"itens": [], "pausada": False}
    itens = [i["projeto"] for i in resumo["itens"]]
    if projeto in itens:
        entrou = f"Entrou na fila: {projeto} (posição {itens.index(projeto) + 1})"
        if resumo.get("pausada"):
            # parar_geracao pausa a fila: sem isto o agente dizia "ja vai comecar" e o pedido ficava parado
            entrou += ". A fila está pausada: só começa depois de retomar_fila; pergunte ao usuário."
        return [texto(entrou)]
    return [texto(f"Começou: {projeto}")]
