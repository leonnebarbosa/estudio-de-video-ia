"""O que cada botao da pagina faz. Cada funcao confere o pedido, grava o projeto e, se for o caso, inicia a tarefa."""
import json, os, re, shutil, subprocess, threading, time
from pathlib import Path

from PIL import Image

import caminhos, config, entrada
import ambiente, ficha_personagem, lmstudio, personagens, projetos, rostos_video, tarefa, video_avancado
import texto_para_imagem as t2i
from continuar_video import PROIBIDO
from trocar_personagem import quadros_usados
from envio import destino_livre, examinar_video, nome_limpo
from projetos import alvos_apagar, alvos_apagar_imagem, resumo_apagar
from validacao import DURACAO_MAX_EDITAR, validar_editar, validar_avancado
from validacao import DURACAO_MAX_TROCA, DURACAO_MAX_TROCA_WANGP, QUADROS_MIN_WANGP, Erro, FPS, MAX_EXPRESSOES, MAX_REFERENCIAS, PARAMETROS, duracao_max_troca_total, modelos_imagem, pasta_projeto, validar_acabamento, validar_ajustes, validar_duracoes_h3, validar_imagem, validar_texto, validar_tomadas, validar_troca, validar_troca_foto


def modelo_do_projeto(p):
    """O modelo de um projeto de imagem para video; projeto antigo, sem a chave, e do H3."""
    modelos = modelos_imagem()
    return next((m for m in modelos if m["id"] == p.get("modelo", "h3")), modelos[0])



def na_fila(projeto):
    f = getattr(tarefa.tarefa, "fila", None)
    return bool(f and f.tem(projeto))


def exigir_comfy_livre(pintando_ok=False):
    # O Editar vídeo pinta no ComfyUI com pausas entre os passos (cortar o trecho, a IA, o Klein): nessas pausas o ComfyUI
    # parece livre, e uma geração começava junto, as duas na placa. Quem pinta passa pintando_ok=True.
    if not pintando_ok and _editando.locked():
        raise Erro("Uma imagem está sendo pintada (Editar vídeo ou a frente de um personagem). Espere terminar (1 a 2 min) e gere de novo.", 409)
    # Com uma geração rodando (ou a fila andando), o pedido vai para a fila, que espera o ComfyUI ficar livre
    f = getattr(tarefa.tarefa, "fila", None)
    if tarefa.tarefa.rodando() or (f and f.ativa()):
        return
    c = ambiente.ler_comfy()
    if not c["ligado"]:
        raise Erro("O ComfyUI está desligado. Esperando o ComfyUI ficar pronto.", 409)
    if c["ocupado"]:
        raise Erro("O ComfyUI está ocupado com outra tarefa. Espere terminar.", 409)


def preparar_imagem(d):
    """Toda a validacao do Imagem para video, sem criar a pasta, sem gravar nada e sem olhar o ComfyUI
    (acao_iniciar_imagem e o planejar_video usam a mesma conta)."""
    projeto = d.get("projeto", "")
    pasta = pasta_projeto(projeto)
    if pasta.exists():
        raise Erro(f"Já existe um projeto chamado {projeto}. Escolha outro nome.", 409)
    # Sem imagem, o H3 faz a tomada 1 so pelo texto (MiniMaxH3ImageToVideo sem first_frame, testado em 10/11/2026)
    foto = nome_limpo(d.get("foto") or "") if d.get("foto") else None
    ajustes = dict(d.get("ajustes") or {})
    pers = d.get("personagem")
    if pers:
        # Personagem da biblioteca: a frente e os ângulos viram as imagens extras do personagem; a imagem de partida
        # continua sendo a cena escolhida (sem ela, a frente)
        try:
            frente, angulos = personagens.para_entrada(pers.get("id") or "", modo="corpo")
        except ValueError as e:
            raise Erro(str(e), 409 if "Aprove a frente" in str(e) else 404)
        except AttributeError:
            raise Erro("Personagem não encontrado.", 404)
        ajustes["referencias"] = ([frente] + angulos)[:MAX_REFERENCIAS]
        foto = foto or frente
    if foto and not entrada.existe(foto):
        raise Erro("Envie a imagem de novo: o arquivo não foi encontrado.")
    parametros = {"tipo": "imagem", **validar_imagem(ajustes), **({"personagem_id": pers["id"]} if pers else {})}
    if foto:
        parametros["autorizado_em"] = time.strftime("%Y-%m-%d %H:%M:%S")
    elif not modelo_do_projeto(parametros)["fala"]:
        raise Erro("O Wan precisa de uma imagem de partida. Escolha a imagem ou use o MiniMax H3.")
    elif not parametros["cena"]:
        raise Erro("Sem imagem, descreva a cena no campo Como é a cena: estilo, lugar e luz, em inglês.")
    if parametros.get("audio") and not foto:
        raise Erro("O áudio da fala precisa de uma imagem de partida: é dela que sai cada tomada.")
    return {"projeto": projeto, "pasta": pasta, "foto": foto, "parametros": parametros, "pers": pers}


def acao_iniciar_imagem(d):
    p = preparar_imagem(d)
    exigir_comfy_livre()
    projeto, pasta, foto, parametros = p["projeto"], p["pasta"], p["foto"], p["parametros"]
    pasta.mkdir()
    if parametros.get("audio"):
        # O audio fica copiado no projeto: a retomada depois de uma queda nao depende da pasta input
        parametros["audio_arquivo"] = "audio_fala" + Path(parametros["audio"]).suffix.lower()
        shutil.copy2(entrada.caminho(parametros["audio"]), pasta / parametros["audio_arquivo"])
    (pasta / PARAMETROS).write_text(json.dumps(parametros, ensure_ascii=False, indent=1), encoding="utf-8")
    caminhos.gravar_json((pasta / "estado.json"), {"tipo": "imagem", "personagem": foto, "sem_imagem": not foto, "tomadas": []})
    tarefa.tarefa.iniciar_imagem(projeto)


def acao_audio_tomadas(d):
    """Modo audio do Imagem para video: como o audio enviado se divide em tomadas nesta resolucao (a mesma conta da validacao).
    Devolve a duracao, os cortes [[inicio, fim]] e, em cada um, onde ha voz."""
    import audio_fala
    from validacao import cortes_do_audio, max_tomada_audio
    try:
        mp = float(d.get("megapixels") or 0.8)
    except (TypeError, ValueError):
        raise Erro("Resolução inválida.")
    pcm, cortes = cortes_do_audio(d.get("audio") or "", mp)
    voz = [audio_fala.trechos_de_voz(pcm, a, b) for a, b in cortes]
    return {"duracao": round(len(pcm) / audio_fala.TAXA, 2), "maximo": max_tomada_audio(mp), "cortes": cortes,
            "voz": [[float(v[0]), float(v[1])] if v else None for v in voz]}


_lendo_exemplo = threading.Lock()


def acao_descrever_video(d):
    """Video de exemplo no modo audio do Imagem para video (descrever_video.py): tira o som do video (ja enviado) para a entrada do
    ComfyUI, onde vira o audio da fala, e escreve para cada tomada a fala transcrita e as expressoes do rosto com o seu momento.
    Roda na CPU, na hora, e leva em torno de um minuto: nao usa a placa nem a fila. O video nao vai para o modelo."""
    import audio_fala, descrever_video
    from validacao import MAX_ACAO, MAX_FALA, cortes_do_audio
    video = config.ENVIOS / nome_limpo(d.get("video") or "")
    if not video.is_file():
        raise Erro("Envie o vídeo de novo: o arquivo não foi encontrado.", 404)
    try:
        mp = float(d.get("megapixels") or 0.8)
    except (TypeError, ValueError):
        raise Erro("Resolução inválida.")
    if not _lendo_exemplo.acquire(blocking=False):
        raise Erro("Já estou lendo um vídeo de exemplo. Espere terminar.", 409)
    try:
        inicio = time.time()
        info = examinar_video(video)
        audio = entrada.novo(f"exemplo_{video.stem}.wav")
        if not info.get("audio") or not descrever_video.som_do_video(video, audio):
            raise Erro("Este vídeo não tem som. O vídeo de exemplo precisa da fala que o vídeo novo vai seguir.")
        pcm, cortes = cortes_do_audio(audio.name, mp)
        r = descrever_video.descrever(video, float(info.get("fps") or FPS), cortes, audio, MAX_ACAO, MAX_FALA)
        return {"audio": {"arquivo": audio.name, "duracao": round(len(pcm) / audio_fala.TAXA, 2)}, "tomadas": r["tomadas"], "avisos": r["avisos"],
                "segundos": round(time.time() - inicio)}
    finally:
        _lendo_exemplo.release()


def acao_iniciar_avancado(d):
    pasta = pasta_projeto(d.get("projeto", ""))
    if pasta.exists():
        raise Erro(f"Já existe um projeto chamado {pasta.name}. Escolha outro nome.", 409)
    parametros = validar_avancado(d)
    exigir_comfy_livre()
    faltam = video_avancado.faltam()
    if faltam:
        raise Erro(f"Faltam arquivos do MiniMax H3 ref2va no ComfyUI: {', '.join(faltam)}.")
    refs = parametros["avancado"]["referencias"]
    capa = next((ref["arquivo"] for ref in refs if ref["tipo"] == "foto"), None)
    parametros["autorizado_em"] = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        pasta.mkdir()
    except FileExistsError:
        raise Erro(f"Já existe um projeto chamado {pasta.name}. Escolha outro nome.", 409)
    caminhos.gravar_json(pasta / PARAMETROS, parametros)
    caminhos.gravar_json(pasta / "estado.json", {"tipo": "imagem", "personagem": capa, "tomadas": []})
    tarefa.tarefa.iniciar_imagem(pasta.name)


def preparar_texto(d, antes_de_validar=None):
    """O que acao_iniciar_texto confere, sem criar nada: o nome do projeto, a pasta que ja existe (409) e validar_texto.
    `antes_de_validar` roda entre a pasta e a validacao (a acao poe ali o exigir_comfy_livre); sozinha, nao olha o ComfyUI."""
    projeto = d.get("projeto", "")
    if pasta_projeto(projeto).exists():
        raise Erro(f"Já existe um projeto chamado {projeto}. Escolha outro nome.", 409)
    if antes_de_validar:
        antes_de_validar()
    return {"tipo": "texto", **validar_texto(d.get("ajustes") or {})}


def acao_iniciar_texto(d):
    projeto = d.get("projeto", "")
    pasta = pasta_projeto(projeto)
    parametros = preparar_texto(d, exigir_comfy_livre)
    pasta.mkdir()
    (pasta / PARAMETROS).write_text(json.dumps(parametros, ensure_ascii=False, indent=1), encoding="utf-8")
    caminhos.gravar_json((pasta / "estado.json"), {"tipo": "texto", "imagens": []})
    tarefa.tarefa.iniciar_texto(projeto)


def acao_iniciar_troca_foto(d):
    """Troca em foto: um projeto de texto com troca_foto (ver validacao.validar_troca_foto); quem roda e o texto_para_imagem."""
    projeto = d.get("projeto", "")
    pasta = pasta_projeto(projeto)
    if pasta.exists():
        raise Erro(f"Já existe um projeto chamado {projeto}. Escolha outro nome.", 409)
    exigir_comfy_livre()
    parametros = {"tipo": "texto", **validar_troca_foto(d.get("ajustes") or {}), "autorizado_em": time.strftime("%Y-%m-%d %H:%M:%S")}
    pasta.mkdir()
    (pasta / PARAMETROS).write_text(json.dumps(parametros, ensure_ascii=False, indent=1), encoding="utf-8")
    caminhos.gravar_json((pasta / "estado.json"), {"tipo": "texto", "imagens": []})
    tarefa.tarefa.iniciar_texto(projeto)


_descrevendo = threading.Lock()


def acao_descrever_imagem(d):
    """A LLM de visao escreve um prompt para a imagem (ja enviada para a entrada do ComfyUI). Leva de 15 a 40 s."""
    if tarefa.tarefa.rodando():
        raise Erro("Espere a geração atual terminar para descrever a imagem.", 409)
    arquivo = nome_limpo(d.get("arquivo") or "")
    if not arquivo or not entrada.existe(arquivo):
        raise Erro("Imagem não encontrada. Envie a imagem de novo.", 404)
    if not _descrevendo.acquire(blocking=False):
        raise Erro("Já estou descrevendo uma imagem. Espere terminar.", 409)
    try:
        exigir_comfy_livre()
        # A LLM roda no ComfyUI: o modelo de conversa do LM Studio sai da placa antes (ver lmstudio.py)
        lmstudio.descarregar()
        inicio = time.time()
        try:
            texto = t2i.descrever(arquivo)
        except RuntimeError as e:
            raise Erro(f"A LLM não conseguiu descrever a imagem: {e}", 500)
        if not texto:
            raise Erro("A LLM devolveu um texto vazio. Tente de novo.", 500)
        return {"prompt": texto, "segundos": round(time.time() - inicio)}
    finally:
        _descrevendo.release()


def acao_usar_imagem(d):
    """Copia uma imagem gerada para a entrada do ComfyUI, para virar o primeiro quadro de um vídeo."""
    pasta = pasta_projeto(d.get("projeto", ""))
    arquivo = nome_limpo(d.get("arquivo") or "")
    origem = pasta / arquivo
    if not arquivo.startswith("imagem_") or origem.suffix.lower() != ".png" or not origem.is_file():
        raise Erro("Imagem não encontrada.", 404)
    nome = nome_limpo(f"texto_{pasta.name}_{arquivo}")
    shutil.copy2(origem, entrada.novo(nome))
    with Image.open(origem) as im:
        largura, altura = im.size
    return {"arquivo": nome, "largura": largura, "altura": altura}


def acao_refazer_imagem(d):
    """Refaz de uma tomada em diante, com o texto editado. As anteriores ficam como estao."""
    pasta = pasta_projeto(d.get("projeto", ""))
    arq_p, arq_e = pasta / PARAMETROS, pasta / "estado.json"
    if not arq_p.exists() or not arq_e.exists():
        raise Erro("Projeto não encontrado.", 404)
    exigir_comfy_livre()
    p, e = json.loads(arq_p.read_text(encoding="utf-8")), json.loads(arq_e.read_text(encoding="utf-8"))
    if e.get("tipo") != "imagem":
        raise Erro("Este projeto não é de imagem para vídeo.")
    if p.get("avancado"):
        raise Erro("Para editar o prompt ou as referências, use Usar de novo.")
    desde = d.get("desde")
    if not isinstance(desde, int) or not 1 <= desde <= len(p["tomadas"]):
        raise Erro("Tomada desconhecida.")
    m = modelo_do_projeto(p)
    if p.get("audio"):
        # Modo audio: a duracao de cada tomada vem do corte do audio e nao muda; muda so a acao, a camera, o olhar e o som
        enviadas = d.get("tomadas")
        if not isinstance(enviadas, list) or len(enviadas) != len(p["tomadas"]):
            raise Erro("O número de tomadas não pode mudar aqui. Use Usar de novo.")
        if not all(isinstance(t, dict) for t in enviadas):
            raise Erro("Uma das tomadas veio incompleta.")
        # validar_tomadas pede acao ou fala; no modo audio a acao pode ficar vazia (a marca "-" so passa pela validacao)
        base = [{**t, "duracao": 5, "fala": str(t.get("fala") or ""), "acao": str(t.get("acao") or "").strip() or "-"} for t in enviadas]
        novas = [{**v, "acao": "" if v["acao"] == "-" else v["acao"], "duracao": t["duracao"]} for v, t in zip(validar_tomadas(base, [5], True), p["tomadas"])]
    else:
        novas = validar_tomadas(d.get("tomadas"), m["duracoes"], m["fala"])
        if m["fala"]:
            validar_duracoes_h3(novas, float(p.get("megapixels", 0)))
    if len(novas) != len(p["tomadas"]):
        raise Erro("O número de tomadas não pode mudar aqui. Use Usar de novo.")
    p["tomadas"] = p["tomadas"][:desde - 1] + novas[desde - 1:]
    e["tomadas"] = e.get("tomadas", [])[:desde - 1]
    if (e.get("voz_tomada") or 0) >= desde:
        e.pop("voz", None), e.pop("voz_tomada", None)
    if (pasta / "final.mp4").exists():
        shutil.copy2(pasta / "final.mp4", pasta / "final_anterior.mp4")
    arq_p.write_text(json.dumps(p, ensure_ascii=False, indent=1), encoding="utf-8")
    caminhos.gravar_json(arq_e, e)
    tarefa.tarefa.iniciar_imagem(pasta.name)


def _apagar_de_vez(pastas, arquivos):
    """Apaga o que alvos_apagar conferiu. Devolve o que nao saiu (arquivo aberto em outro programa, por exemplo)."""
    falhas = []
    for f in arquivos:
        try:
            f.unlink()
        except OSError as e:
            falhas.append(f"{f.name}: {e.strerror}")
    for p in pastas:
        shutil.rmtree(p, onexc=lambda _f, caminho, e: falhas.append(f"{Path(caminho).name}: {getattr(e, 'strerror', e)}"))
    return falhas


def acao_apagar(d):
    """Sem confirmar, so diz o que seria apagado. Com confirmar, apaga de vez (nao vai para a Lixeira)."""
    nome = d.get("projeto", "")
    if tarefa.tarefa.rodando() and tarefa.tarefa.projeto == nome:
        raise Erro("Este projeto está gerando agora. Pare a geração antes de apagar.", 409)
    if na_fila(nome):
        raise Erro("Este projeto está na fila. Tire ele da fila antes de apagar.", 409)
    pastas, arquivos = alvos_apagar(nome)
    resumo = resumo_apagar(pastas, arquivos)
    if d.get("confirmar") is not True:
        return resumo
    falhas = _apagar_de_vez(pastas, arquivos)
    projetos._ultimos.pop(nome, None)
    if falhas:
        raise Erro("Parte não foi apagada (algum arquivo pode estar aberto em outro programa): " + "; ".join(falhas[:5]), 500)
    return {**resumo, "apagado": True}


def acao_apagar_imagem(d):
    """Uma imagem de um projeto de texto com varias. Sem confirmar, so diz o que sairia; com confirmar, apaga de vez
    (nao vai para a Lixeira) e marca a imagem como descartada no estado, para o projeto nao pedir que ela seja gerada de novo."""
    nome, arquivo = d.get("projeto", ""), d.get("arquivo", "")
    if tarefa.tarefa.rodando() and tarefa.tarefa.projeto == nome:
        raise Erro("Este projeto está gerando agora. Espere terminar para descartar uma imagem.", 409)
    e, arquivos = alvos_apagar_imagem(nome, arquivo)
    resumo = {**resumo_apagar([], arquivos), "arquivo": arquivo}
    if d.get("confirmar") is not True:
        return resumo
    falhas = _apagar_de_vez([], arquivos)
    if (pasta_projeto(nome) / arquivo).exists():
        raise Erro("A imagem não foi apagada (pode estar aberta em outro programa): " + "; ".join(falhas[:5]), 500)
    for r in e.get("imagens", []):
        if r.get("arquivo") == arquivo:
            r["descartada"] = True
    arq = pasta_projeto(nome) / "estado.json"
    # A data do estado.json e a data do projeto (ordem em Projetos e no historico): descartar nao a muda
    datas = arq.stat()
    caminhos.gravar_json(arq, e)
    os.utime(arq, ns=(datas.st_atime_ns, datas.st_mtime_ns))
    projetos._ultimos.pop(nome, None)
    return {**resumo, "apagado": True, "falhas": falhas}


def acao_apagar_varios(d):
    """Mesma coisa que acao_apagar, para uma lista de projetos. Todos sao conferidos antes de apagar o primeiro:
    se um nao existe ou esta gerando, nada e apagado."""
    nomes = d.get("projetos")
    if not isinstance(nomes, list) or not nomes or not all(isinstance(n, str) and n for n in nomes):
        raise Erro("Escolha os projetos que quer apagar.")
    nomes = list(dict.fromkeys(nomes))
    if tarefa.tarefa.rodando() and tarefa.tarefa.projeto in nomes:
        raise Erro(f"{tarefa.tarefa.projeto} está gerando agora. Pare a geração ou tire ele da seleção.", 409)
    enfileirados = [n for n in nomes if na_fila(n)]
    if enfileirados:
        raise Erro(f"{', '.join(enfileirados)} está na fila. Tire da fila ou da seleção antes de apagar.", 409)
    alvos = {}
    for nome in nomes:
        try:
            alvos[nome] = alvos_apagar(nome, junto=nomes)
        except Erro as e:
            raise Erro(f"{nome}: {e.mensagem}", e.codigo) from None
    pastas = [p for ps, _ in alvos.values() for p in ps]
    arquivos = list(dict.fromkeys(f for _, fs in alvos.values() for f in fs))
    resumo = {**resumo_apagar(pastas, arquivos), "projetos": nomes}
    if d.get("confirmar") is not True:
        return resumo
    falhas = []
    for nome, (ps, fs) in alvos.items():
        falhas += _apagar_de_vez(ps, [f for f in fs if f.exists()])
        projetos._ultimos.pop(nome, None)
    if falhas:
        raise Erro("Parte não foi apagada (algum arquivo pode estar aberto em outro programa): " + "; ".join(falhas[:5]), 500)
    return {**resumo, "apagado": True}


def acao_acabar_imagem(d):
    """Faz ou refaz o final_hd.mp4 de um video pronto, sem gerar as tomadas de novo."""
    pasta = pasta_projeto(d.get("projeto", ""))
    arq_p, arq_e = pasta / PARAMETROS, pasta / "estado.json"
    if not arq_p.exists() or not arq_e.exists():
        raise Erro("Projeto não encontrado.", 404)
    p, e = json.loads(arq_p.read_text(encoding="utf-8")), json.loads(arq_e.read_text(encoding="utf-8"))
    if e.get("tipo", p.get("tipo")) != "imagem":
        raise Erro("Este projeto não é de imagem para vídeo.")
    if len(e.get("tomadas", [])) < len(p.get("tomadas", [])) or not (pasta / "final.mp4").exists():
        raise Erro("Termine todas as tomadas antes de ampliar.")
    modo = d.get("acabamento")
    if modo == "nenhum":
        raise Erro("Escolha um acabamento.")
    if modo not in modelo_do_projeto(p)["acabamentos"]:
        raise Erro("Este acabamento não vale para o modelo deste projeto.")
    validar_acabamento(modo, float(p.get("megapixels", 0)))
    if modo == "refino" and (p.get("audio") or p.get("avancado")):
        raise Erro("Use o Full HD com ESRGAN para preservar o vídeo e o áudio desta geração.")
    if modo == "refino":
        exigir_comfy_livre()
    p["acabamento"] = modo
    arq_p.write_text(json.dumps(p, ensure_ascii=False, indent=1), encoding="utf-8")
    tarefa.tarefa.iniciar_imagem(pasta.name, ["--so-acabar"])


def acao_iniciar_troca(d):
    projeto = d.get("projeto", "")
    pasta = pasta_projeto(projeto)
    if pasta.exists():
        raise Erro(f"Já existe um projeto chamado {projeto}. Escolha outro nome.", 409)
    exigir_comfy_livre()
    video = config.ENVIOS / nome_limpo(d.get("video", ""))
    if not video.is_file():
        raise Erro("Envie o vídeo de novo: o arquivo não foi encontrado.")
    ajustes = validar_troca(d.get("ajustes") or {})
    # Motores Viggle (troca_wangp.py) e Wan Animate 2 (troca_wan.py): sem marcar pessoa nem ângulos extras
    wangp = ajustes.get("motor") in ("wangp", "viggle", "wan")
    if wangp and d.get("marca") is not None:
        raise Erro("Marcar quem trocar ainda não vai com o Viggle Remake nem com o Wan Animate 2. Tire a marca ou use o motor do estúdio.")
    if ajustes.get("motor") == "wan":
        import troca_wan
        faltam_wan = troca_wan.faltam()
        if faltam_wan:
            raise Erro("Faltam arquivos do Wan Animate 2 na pasta de modelos do ComfyUI: " + ", ".join(faltam_wan) + ". Baixe o pacote do Wan Animate 2 em Modelos.")
    # Um personagem da biblioteca: a frente vira a foto; os outros ângulos só vão como referências extras se pedidos.
    # Desligado por padrão: no A/B de 17/11/2026 (Bruno no guia_giro, mesma semente) eles puseram cabelo comprido na nuca
    # de um homem de cabeça raspada (a barba vista por trás virou cabelo); sem eles a nuca saiu certa. No segundo (Cida no
    # guia_cozinha_v) os cachos ficaram mais fiéis com eles (+42 s). Resultado misto: fica como opção.
    angulos, pers = [], d.get("personagem")
    if pers:
        try:
            foto, angulos = personagens.para_entrada(pers.get("id") or "", pers.get("angulos") is True and not wangp,
                                                     ajustes["roupa"] == "video", "cabeca" if ajustes["roupa"] == "video" else "corpo")
        except ValueError as e:
            raise Erro(str(e), 409 if "Aprove a frente" in str(e) else 404)
        except AttributeError:
            raise Erro("Personagem não encontrado.", 404)
    else:
        foto = nome_limpo(d.get("foto") or "")
        if not entrada.existe(foto):
            raise Erro("Envie a foto de novo: o arquivo não foi encontrado.")
    # Fotos de expressão da mesma pessoa (motores viggle e wan, roupa do vídeo): as enviadas na aba e as guardadas no
    # personagem. Cada quadro pintado leva a de expressão mais perto do quadro original (troca_wangp.escolher_cabecas)
    expressoes = []
    if wangp and ajustes["roupa"] == "video":
        enviadas = d.get("expressoes") or []
        if not isinstance(enviadas, list):
            raise Erro("As fotos de expressão vieram num formato inválido.")
        for e in enviadas:
            e = nome_limpo(str(e))
            if not entrada.existe(e):
                raise Erro("Envie a foto de expressão de novo: o arquivo não foi encontrado.")
            expressoes.append(e)
        if pers:
            expressoes += personagens.expressoes_para_entrada(pers["id"])
        expressoes = list(dict.fromkeys(expressoes))[:MAX_EXPRESSOES]
    info = examinar_video(video)
    try:
        duracao = float(d.get("duracao"))
    except (TypeError, ValueError):
        raise Erro("A duração precisa ser um número.")
    maximo = DURACAO_MAX_TROCA_WANGP if wangp else duracao_max_troca_total(ajustes["megapixels"], ajustes["upscale"])
    if not 1 <= duracao <= maximo:
        # Com a segunda passagem nao ha janelas; a 0,8 MP uma passada de 5 s caiu em 11/11/2026
        raise Erro(f"Use uma duração de 1 a {str(maximo).replace('.', ',')} s" + (f" a {str(ajustes['megapixels']).replace('.', ',')} MP com o upscale (a segunda passagem não vai em janelas)." if maximo < DURACAO_MAX_TROCA else "."))
    # Numa passada o fluxo arredonda a duracao para cima, para o numero de quadros que o modelo aceita; em janelas usa
    # os quadros pedidos e completa a ultima janela repetindo o ultimo quadro
    # O Viggle gera no minimo 90 quadros e corta no tamanho pedido: o video precisa ter esses quadros a partir do inicio
    usados = (round(duracao * FPS) if ajustes.get("motor") == "wan" else max(QUADROS_MIN_WANGP, round(duracao * FPS)) if wangp
              else quadros_usados(duracao, ajustes["megapixels"]))
    # De onde o trecho comeca (editor do trecho da interface nova, como no Henge); sem o campo, do comeco
    try:
        inicio = round(float(d.get("inicio") or 0), 3)
    except (TypeError, ValueError):
        raise Erro("O início do trecho precisa ser um número.")
    if not 0 <= inicio < info["duracao"]:
        raise Erro("O início do trecho fica fora do vídeo.")
    # Pelo numero de quadros: int(duracao * fps) arredonda para baixo e recusava um video de 73 quadros para 3 s
    disponiveis = (info.get("quadros") or int(info["duracao"] * FPS)) / (info.get("fps") or FPS) * FPS - inicio * FPS
    if usados > disponiveis + 0.5:
        resto = str(round(disponiveis / FPS, 2)).replace('.', ',')
        raise Erro(f"Com {str(duracao).replace('.', ',')} s o fluxo usa {str(round(usados / FPS, 2)).replace('.', ',')} s de vídeo, mas " + (f"a partir de {str(inicio).replace('.', ',')} s sobram {resto} s." if inicio else f"o seu tem {str(info['duracao']).replace('.', ',')} s.") + " Reduza a duração.")
    # Marcar quem trocar: o ponto clicado na pessoa, no primeiro quadro do trecho (0 a 1); sem ele, o quadro inteiro
    marca = d.get("marca")
    if marca is not None:
        try:
            marca = {"x": round(float(marca["x"]), 4), "y": round(float(marca["y"]), 4)}
        except (TypeError, ValueError, KeyError):
            raise Erro("A marcação da pessoa veio num formato desconhecido. Marque de novo.")
        if not (0 <= marca["x"] <= 1 and 0 <= marca["y"] <= 1):
            raise Erro("A marcação ficou fora do vídeo. Marque de novo.")
        if ajustes["upscale"]:
            raise Erro("Marcar quem trocar não vai com o upscale (a segunda passagem). Use o ESRGAN.")
    # Fundo novo (Henge): uma foto que vira o cenario, andando com a camera (fundo.py)
    fundo = nome_limpo(d["fundo"]) if d.get("fundo") else None
    if fundo and not entrada.existe(fundo):
        raise Erro("Envie a foto do fundo de novo: o arquivo não foi encontrado.")
    parametros = {"tipo": "troca", "duracao": duracao, "inicio": inicio, **({"marca": marca} if marca else {}), **({"fundo": fundo} if fundo else {}), **({"expressoes": expressoes} if expressoes else {}), **ajustes,
                  **({"personagem_id": pers["id"], "angulos": angulos} if pers else {}), "autorizado_em": time.strftime("%Y-%m-%d %H:%M:%S")}
    if not info["audio"]:
        parametros["audio_original"] = False
    pasta.mkdir()
    (pasta / PARAMETROS).write_text(json.dumps(parametros, ensure_ascii=False, indent=1), encoding="utf-8")
    estado = {"tipo": "troca", "origem": caminhos.guardar_envio(video), "personagem": foto, "quadros_origem": info["quadros"]}
    caminhos.gravar_json((pasta / "estado.json"), estado)
    tarefa.tarefa.iniciar_troca(projeto)


def acao_iniciar_editar(d):
    """Editar video (editar_video.py): o trecho, o quadro pinado e a pintura escolhida na pagina."""
    import editar_video
    projeto = d.get("projeto", "")
    pasta = pasta_projeto(projeto)
    if pasta.exists():
        raise Erro(f"Já existe um projeto chamado {projeto}. Escolha outro nome.", 409)
    exigir_comfy_livre()
    video = config.ENVIOS / nome_limpo(d.get("video", ""))
    if not video.is_file():
        raise Erro("Envie o vídeo de novo: o arquivo não foi encontrado.")
    pedido = d.get("pedido")
    if not isinstance(pedido, str) or not pedido.strip():
        raise Erro("Escreva o que mudar no vídeo.")
    if len(pedido) > 2000:
        raise Erro("O pedido ficou grande demais (até 2000 caracteres).")
    ajustes = validar_editar(d.get("ajustes") or {})
    pintura = entrada.caminho(nome_limpo(d.get("pintura") or ""))
    if not d.get("pintura") or not pintura.is_file():
        raise Erro("Pinte o quadro de novo: a pintura não foi encontrada.")
    info = examinar_video(video)
    try:
        duracao = float(d.get("duracao"))
        inicio = round(float(d.get("inicio") or 0), 3)
    except (TypeError, ValueError):
        raise Erro("A duração e o início do trecho precisam ser números.")
    if not 1 <= duracao <= DURACAO_MAX_EDITAR:
        raise Erro(f"Use uma duração de 1 a {DURACAO_MAX_EDITAR} s.")
    if not 0 <= inicio < info["duracao"]:
        raise Erro("O início do trecho fica fora do vídeo.")
    # O Viggle gera no minimo 90 quadros e corta no tamanho pedido (mesma conta da troca pelo Viggle)
    usados = max(QUADROS_MIN_WANGP, round(duracao * FPS))
    disponiveis = (info.get("quadros") or int(info["duracao"] * FPS)) / (info.get("fps") or FPS) * FPS - inicio * FPS
    if usados > disponiveis + 0.5:
        resto = str(round(disponiveis / FPS, 2)).replace('.', ',')
        raise Erro(f"O Viggle Remake usa pelo menos {str(round(usados / FPS, 2)).replace('.', ',')} s de vídeo, mas a partir de {str(inicio).replace('.', ',')} s sobram {resto} s. "
                   "Comece o trecho mais cedo ou reduza a duração.")
    quadro = d.get("quadro", editar_video.QUADRO_PADRAO)
    if not isinstance(quadro, int) or isinstance(quadro, bool) or not 0 <= quadro < round(duracao * FPS):
        raise Erro("O quadro a pintar fica fora do trecho.")
    parametros = {"tipo": "editar", "duracao": duracao, "inicio": inicio, "quadro": quadro, "pedido": pedido.strip(), **ajustes,
                  "autorizado_em": time.strftime("%Y-%m-%d %H:%M:%S")}
    if not info["audio"]:
        parametros["audio_original"] = False
    pasta.mkdir()
    shutil.copyfile(pintura, pasta / "pintado.png")
    (pasta / PARAMETROS).write_text(json.dumps(parametros, ensure_ascii=False, indent=1), encoding="utf-8")
    estado = {"tipo": "editar", "origem": caminhos.guardar_envio(video), "pintura": "pintado.png", "quadros_origem": info["quadros"]}
    caminhos.gravar_json(pasta / "estado.json", estado)
    tarefa.tarefa.iniciar_editar(projeto)


_editando = threading.Lock()
CODIGO_EDITAR = re.compile(r"[0-9a-f]{8}")


def _placa_livre_para_pintar():
    f = getattr(tarefa.tarefa, "fila", None)
    if tarefa.tarefa.rodando() or (f and f.ativa()):
        raise Erro("Pintar só com a placa livre. Espere a geração atual terminar.", 409)


def _codigo_editar(d):
    import secrets
    codigo = d.get("codigo") or secrets.token_hex(4)
    if not isinstance(codigo, str) or not CODIGO_EDITAR.fullmatch(codigo):
        raise Erro("Código de pintura desconhecido. Pinte de novo.")
    return codigo


def _pedido_editar(d):
    pedido = d.get("pedido")
    if not isinstance(pedido, str) or not pedido.strip():
        raise Erro("Escreva o que mudar no vídeo.")
    if len(pedido) > 2000:
        raise Erro("O pedido ficou grande demais (até 2000 caracteres).")
    return pedido.strip()


def acao_editar_pintar(d):
    """Editar video: o Klein pinta o quadro escolhido do trecho em 2 opcoes (editar_video.pintar). Leva ~1 min.
    Sem o pedido do Klein, a IA de visao o escreve a partir do pedido em portugues."""
    import editar_video as ev
    _placa_livre_para_pintar()
    video = config.ENVIOS / nome_limpo(d.get("video", ""))
    if not video.is_file():
        raise Erro("Envie o vídeo de novo: o arquivo não foi encontrado.")
    pedido = _pedido_editar(d)
    try:
        inicio = round(float(d.get("inicio") or 0), 3)
    except (TypeError, ValueError):
        raise Erro("O início do trecho precisa ser um número.")
    quadro = d.get("quadro", ev.QUADRO_PADRAO)
    if not isinstance(quadro, int) or isinstance(quadro, bool) or not 0 <= quadro < DURACAO_MAX_EDITAR * FPS:
        raise Erro("O quadro a pintar fica fora do trecho.")
    codigo = _codigo_editar(d)
    pedido_klein = d.get("pedido_klein") or ""
    if not isinstance(pedido_klein, str) or len(pedido_klein) > 6000:
        raise Erro("O pedido da pintura ficou grande demais.")
    if not _editando.acquire(blocking=False):
        raise Erro("Já estou pintando. Espere terminar.", 409)
    try:
        exigir_comfy_livre(pintando_ok=True)
        # A IA e o Klein rodam no ComfyUI: o modelo de conversa do LM Studio sai da placa antes (ver lmstudio.py)
        lmstudio.descarregar()
        info = examinar_video(video)
        if inicio >= info["duracao"]:
            raise Erro("O início do trecho fica fora do vídeo.")
        t0 = time.time()
        try:
            quadro_png = ev.extrair_quadro(video, inicio, quadro, codigo)
        except (RuntimeError, subprocess.CalledProcessError) as e:
            raise Erro(f"Não consegui tirar o quadro do vídeo: {e}", 500)
        ia = True
        if not pedido_klein.strip():
            pedido_klein, ia = ev.escrever_pedido_klein(pedido, quadro_png)
        largura, altura = ev.tamanho_editar(info["largura"], info["altura"], "melhor")
        import random
        sementes = [random.randrange(2**31) for _ in range(ev.OPCOES_PINTURA)]
        try:
            pinturas = ev.pintar(quadro_png, pedido_klein.strip(), codigo, largura, altura, sementes)
        except RuntimeError as e:
            raise Erro(f"O Klein não pintou o quadro: {e}", 500)
        return {"codigo": codigo, "quadro": quadro_png, "pinturas": pinturas, "pedido_klein": pedido_klein.strip(), "ia": ia, "segundos": round(time.time() - t0)}
    finally:
        _editando.release()


def acao_editar_roteiro(d):
    """Editar video: a IA de visao escreve o roteiro do Viggle olhando o quadro original e a pintura escolhida (~30 s)."""
    import editar_video as ev
    _placa_livre_para_pintar()
    codigo = _codigo_editar(d)
    pedido = _pedido_editar(d)
    quadro_png, pintura = nome_limpo(d.get("quadro_png") or ""), nome_limpo(d.get("pintura") or "")
    if not quadro_png or not pintura or not entrada.existe(quadro_png) or not entrada.existe(pintura):
        raise Erro("Pinte o quadro de novo: a pintura não foi encontrada.", 404)
    try:
        quadro, duracao = int(d.get("quadro")), float(d.get("duracao"))
    except (TypeError, ValueError):
        raise Erro("O quadro e a duração precisam ser números.")
    if not _editando.acquire(blocking=False):
        raise Erro("Já estou pintando ou escrevendo. Espere terminar.", 409)
    try:
        exigir_comfy_livre(pintando_ok=True)
        lmstudio.descarregar()
        t0 = time.time()
        roteiro, ia = ev.escrever_roteiro(pedido, str(d.get("pedido_klein") or ""), quadro_png, pintura, quadro, duracao, codigo)
        return {"roteiro": roteiro, "ia": ia, "segundos": round(time.time() - t0)}
    finally:
        _editando.release()


def acao_editar_imagem_minha(d):
    """Editar video: uma imagem do usuario no lugar da pintura. Tem de ser o mesmo quadro editado (vai pinada), entao a
    proporcao precisa bater com a do video."""
    import editar_video as ev
    video = config.ENVIOS / nome_limpo(d.get("video", ""))
    arquivo = entrada.caminho(nome_limpo(d.get("arquivo") or ""))
    if not video.is_file():
        raise Erro("Envie o vídeo de novo: o arquivo não foi encontrado.")
    if not d.get("arquivo") or not arquivo.is_file():
        raise Erro("Envie a imagem de novo: o arquivo não foi encontrado.")
    codigo = _codigo_editar(d)
    info = examinar_video(video)
    with Image.open(arquivo) as im:
        proporcao = im.width / im.height
        alvo = info["largura"] / info["altura"]
        if abs(proporcao - alvo) / alvo > ev.TOLERANCIA_PROPORCAO:
            raise Erro("A imagem precisa ser o mesmo quadro do vídeo, no mesmo enquadramento.")
        largura, altura = ev.tamanho_editar(info["largura"], info["altura"], "melhor")
        nome = f"editar_pintura_{codigo}_minha.png"
        im.convert("RGB").resize((largura, altura), Image.LANCZOS).save(entrada.novo(nome))
    return {"pintura": nome, "codigo": codigo}


def acao_plano(d):
    """Corrige os passos antes da primeira rodada, com a mesma regra de termos do script."""
    pasta = pasta_projeto(d.get("projeto", ""))
    arq = pasta / "estado.json"
    if not arq.exists():
        raise Erro("Projeto não encontrado.", 404)
    if tarefa.tarefa.rodando() and tarefa.tarefa.projeto == pasta.name:
        raise Erro("Espere a tarefa deste projeto terminar.", 409)
    e = json.loads(arq.read_text(encoding="utf-8"))
    if not e.get("plano") or e.get("rodadas"):
        raise Erro("O plano só pode ser alterado antes da primeira rodada.", 409)
    passos = d.get("passos")
    if not isinstance(passos, list) or len(passos) != len(e["plano"]["beats"]) or not all(isinstance(b, str) and b.strip() for b in passos):
        raise Erro("Preencha todos os passos do plano.")
    passos = [b.strip() for b in passos]
    achado = PROIBIDO.search(" ".join(passos))
    if achado:
        raise Erro(f"O plano tem um termo recusado pelo script: {achado.group(0)}")
    e["plano"]["beats"] = passos
    caminhos.gravar_json(arq, e)
    (pasta / "plano.json").write_text(json.dumps(e["plano"], ensure_ascii=False, indent=1), encoding="utf-8")


def acao_reusar(d):
    """Prepara o formulario com o video, a foto e os ajustes de um projeto."""
    pasta = pasta_projeto(d.get("projeto", ""))
    e = json.loads((pasta / "estado.json").read_text(encoding="utf-8"))
    if e.get("tipo") == "imagem":
        p = json.loads((pasta / PARAMETROS).read_text(encoding="utf-8"))
        if p.get("avancado"):
            if d.get("aceita_video_avancado") is not True:
                raise Erro("Atualize a página do Estúdio (Ctrl+R) e clique em Usar de novo para abrir este vídeo avançado.", 409)
            return {"tipo": "avancado", "config": p}
        # Sem imagem, o personagem e um quadro da tomada 1: usar de novo volta a gerar so pelo texto
        foto = None if e.get("sem_imagem") else e.get("personagem")
        info = None
        if foto and entrada.existe(foto):
            with Image.open(entrada.caminho(foto)) as im:
                info = {"arquivo": foto, "largura": im.size[0], "altura": im.size[1]}
        # Modo audio: o audio sumido da entrada volta da copia guardada no projeto; a foto do lugar sumida volta vazia
        if p.get("audio") and not entrada.existe(nome_limpo(p["audio"])):
            if p.get("audio_arquivo") and (pasta / p["audio_arquivo"]).is_file():
                shutil.copy2(pasta / p["audio_arquivo"], entrada.novo(nome_limpo(p["audio"])))
            else:
                p["audio"] = None
        if p.get("cenario") and not entrada.existe(nome_limpo(p["cenario"])):
            p["cenario"] = None
        return {"tipo": "imagem", "foto": info, "config": p, "sem_imagem": bool(e.get("sem_imagem"))}
    if e.get("tipo") == "texto":
        p = json.loads((pasta / PARAMETROS).read_text(encoding="utf-8")) if (pasta / PARAMETROS).exists() else {}
        cfg = {k: v for k, v in p.items() if k != "tipo"}
        # A imagem de partida pode ter sido apagada da entrada do ComfyUI: aí o formulário volta sem ela
        if cfg.get("partida") and not entrada.existe(nome_limpo(cfg["partida"])):
            cfg["partida"] = None
        if cfg.get("referencia") and not entrada.existe(nome_limpo(cfg["referencia"])):
            cfg["referencia"] = None
        if cfg.get("referencias"):
            cfg["referencias"] = [n for n in cfg["referencias"] if entrada.existe(nome_limpo(n))]
        # Modelo que saiu do seletor (o Qwen 2511): o formulário volta com o que entrou no lugar dele, e os passos dele
        if cfg.get("modelo") in t2i.MODELOS_SUBSTITUIDOS:
            cfg["modelo"] = t2i.MODELOS_SUBSTITUIDOS[cfg["modelo"]]
            cfg["passos"] = t2i.MODELOS_TEXTO[cfg["modelo"]]["passos"]
        # Troca em foto: as fotos do rosto e da roupa que sumiram da entrada voltam vazias
        for chave, nome in (cfg.get("troca_foto") or {}).items():
            if nome and not entrada.existe(nome_limpo(nome)):
                cfg["troca_foto"][chave] = None
        cfg.pop("autorizado_em", None)
        return {"tipo": "texto", "config": cfg}
    if e.get("tipo") == "wan":
        p = json.loads((pasta / PARAMETROS).read_text(encoding="utf-8")) if (pasta / PARAMETROS).exists() else {}
        foto = e.get("personagem")
        info = None
        if foto and entrada.existe(foto):
            with Image.open(entrada.caminho(foto)) as im:
                info = {"arquivo": foto, "largura": im.size[0], "altura": im.size[1]}
        return {"tipo": "wan", "foto": info, "config": {k: v for k, v in p.items() if k not in ("tipo", "autorizado_em")}}
    if e.get("tipo") == "editar":
        # O video volta inteiro (o inicio do trecho vem junto na config) e a pintura usada volta escolhida
        p = json.loads((pasta / PARAMETROS).read_text(encoding="utf-8")) if (pasta / PARAMETROS).exists() else {}
        origem = caminhos.abrir_envio(e.get("origem", ""))
        if not origem.is_file():
            raise Erro("O vídeo original deste projeto não foi encontrado. Escolha o vídeo de novo.", 404)
        config.ENVIOS.mkdir(exist_ok=True)
        destino = destino_livre(config.ENVIOS, nome_limpo(Path(e.get("origem") or origem.name).name), origem)
        if not destino.exists():
            shutil.copy2(origem, destino)
        pintura = None
        if (pasta / "pintado.png").is_file():
            pintura = f"editar_pintura_{pasta.name}_reuso.png"
            shutil.copyfile(pasta / "pintado.png", entrada.novo(pintura))
        return {"tipo": "editar", "video": {**examinar_video(destino), "arquivo": destino.name}, "pintura": pintura,
                "config": {k: v for k, v in p.items() if k not in ("tipo", "autorizado_em")}}
    origem = entrada.caminho(f"troca_{pasta.name}.mp4" if e.get("tipo") == "troca" else f"cont_{pasta.name}_r00.mp4")
    if not origem.is_file():
        origem = caminhos.abrir_envio(e.get("origem", ""))
    if not origem.is_file():
        raise Erro("O vídeo original deste projeto não foi encontrado. Escolha o vídeo de novo.", 404)
    entradas = config.ENVIOS
    entradas.mkdir(exist_ok=True)
    destino = destino_livre(entradas, nome_limpo(Path(e.get("origem") or origem.name).name), origem)
    if not destino.exists():
        shutil.copy2(origem, destino)
    foto = e.get("personagem")
    p = json.loads((pasta / PARAMETROS).read_text(encoding="utf-8")) if (pasta / PARAMETROS).exists() else None
    return {"tipo": e.get("tipo"), "video": {**examinar_video(destino), "arquivo": destino.name}, "foto": foto if foto and entrada.existe(foto) else None, "ideia": e.get("ideia", ""), "config": p}


def acao_abrir_pasta(d):
    pasta = pasta_projeto(d.get("projeto", ""))
    final = pasta / "final.mp4"
    subprocess.Popen(f'explorer /select,"{final}"' if final.exists() else f'explorer "{pasta}"', creationflags=config.SEM_JANELA)


def acao_iniciar(d):
    projeto = d.get("projeto", "")
    pasta = pasta_projeto(projeto)
    if pasta.exists():
        raise Erro(f"Já existe um projeto chamado {projeto}. Escolha outro nome.", 409)
    exigir_comfy_livre()
    video = config.ENVIOS / nome_limpo(d.get("video", ""))
    if not video.is_file():
        raise Erro("Envie o vídeo de novo: o arquivo não foi encontrado.")
    info = examinar_video(video)
    if not info["audio"]:
        raise Erro("O vídeo precisa ter áudio, porque o fluxo usa a faixa original.")
    ideia = (d.get("ideia") or "").strip()
    if not ideia or len(ideia) > 2000:
        raise Erro("Escreva o que acontece, em até 2.000 caracteres.")
    try:
        duracao = float(d.get("duracao"))
    except (TypeError, ValueError):
        raise Erro("A duração precisa ser um número.")
    if not info["duracao"] < duracao <= 300:
        raise Erro(f"A duração final precisa ser maior que o vídeo ({str(info['duracao']).replace('.', ',')} s) e no máximo 300 s.")
    parametros = {"duracao": duracao, **validar_ajustes(d.get("ajustes") or {})}
    extras = ["--video", str(video), "--ideia", ideia]
    foto = d.get("foto")
    if foto:
        foto = nome_limpo(foto)
        if not entrada.existe(foto):
            raise Erro("Envie a foto de novo: o arquivo não foi encontrado.")
        extras += ["--personagem", foto]
    pasta.mkdir()
    (pasta / PARAMETROS).write_text(json.dumps(parametros, ensure_ascii=False, indent=1), encoding="utf-8")
    tarefa.tarefa.iniciar(projeto, "plano" if d.get("so_plano") else "gerar", extras)


def acao_refazer_janela(d):
    """Refaz uma janela da troca em diante, ate o fim do plano dela, com outra semente (Refazer uma janela, do Henge).
    As outras janelas ficam como estavam (trocar_personagem.trocar_em_janelas)."""
    pasta = pasta_projeto(d.get("projeto", ""))
    arq_e = pasta / "estado.json"
    if not arq_e.exists() or not (pasta / "janelas_feitas" / "janelas.json").exists():
        raise Erro("Este projeto não tem as janelas guardadas. Gere a troca de novo para poder refazer uma janela.", 404)
    janelas = json.loads(arq_e.read_text(encoding="utf-8")).get("janelas") or []
    n = d.get("janela")
    if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= len(janelas):
        raise Erro("Janela desconhecida.")
    exigir_comfy_livre()
    tarefa.tarefa.iniciar_troca(pasta.name, ["--refazer", str(n)])


def acao_continuar(d):
    pasta = pasta_projeto(d.get("projeto", ""))
    if not (pasta / PARAMETROS).exists():
        raise Erro("Este projeto foi feito fora da página, então ela não sabe a duração pedida para continuar.", 409)
    modo = "juntar" if d.get("modo") == "juntar" else "gerar"
    if modo == "gerar":
        exigir_comfy_livre()
    tipo = json.loads((pasta / PARAMETROS).read_text(encoding="utf-8")).get("tipo")
    if tipo == "troca":
        tarefa.tarefa.iniciar_troca(pasta.name)
    elif tipo == "imagem":
        tarefa.tarefa.iniciar_imagem(pasta.name)
    elif tipo == "texto":
        tarefa.tarefa.iniciar_texto(pasta.name)
    elif tipo == "wan":
        tarefa.tarefa.iniciar_wan(pasta.name)
    elif tipo == "editar":
        tarefa.tarefa.iniciar_editar(pasta.name)
    else:
        tarefa.tarefa.iniciar(pasta.name, modo, [])


# Biblioteca de personagens (personagens.py): criar com uma foto enviada ou uma imagem de um projeto, gerar os ângulos, apagar.

def _origem_personagem(d):
    """A foto de frente: uma imagem de projeto (projeto + imagem) ou uma foto enviada (foto, na input do ComfyUI)."""
    if d.get("projeto"):
        imagem = d.get("imagem") or "imagem_1.png"
        if not isinstance(imagem, str) or not re.fullmatch(r"imagem_\d{1,2}\.png", imagem):
            raise Erro("Imagem desconhecida.")
        origem = pasta_projeto(d["projeto"]) / imagem
    else:
        origem = entrada.caminho(nome_limpo(d.get("foto") or ""))
    if not origem.is_file():
        raise Erro("A foto do personagem não foi encontrada. Envie de novo.", 404)
    return origem


def acao_personagem_criar(d):
    ficha, angulos = d.get("ficha") is True, d.get("angulos") is True
    usar_base = ficha and d.get("usar_base") is True
    if ficha and angulos:
        raise Erro("Escolha a ficha ou os ângulos separados.")
    if ficha and not usar_base:
        exigir_modelo_ficha()
    origem = _origem_personagem(d)
    # Fotos reais dos outros ângulos (opcionais): entram no lugar do que o Klein geraria
    fotos = d.get("fotos") or {}
    if not isinstance(fotos, dict):
        raise Erro("As fotos dos ângulos vieram num formato desconhecido.")
    fotos = {a: entrada.caminho(nome_limpo(f)) for a, f in fotos.items() if isinstance(f, str) and f}
    lados = d.get("lados") if isinstance(d.get("lados"), dict) else {}
    lados = {a: v for a, v in lados.items() if a in personagens.ROSTO and isinstance(v, bool)}
    # Os ângulos precisam do ComfyUI: conferir antes de criar. Depois, um 409 deixava o personagem criado e as fotos (rostos do
    # vídeo, opções da frente) já apagadas, e o segundo clique em Criar dava "foto não encontrada" (revisão de 19/11/2026)
    if (ficha and not usar_base) or angulos:
        exigir_comfy_livre()
    try:
        pid = personagens.criar(d.get("nome"), d.get("descricao"), origem, fotos, lados)
    except ValueError as e:
        raise Erro(str(e))
    # Os rostos já foram copiados para a input: a pasta de rostos do vídeo (~18 MB) não serve mais; as antigas também saem
    for nome in {rostos_video.pasta_da_foto(f.name) for f in [origem, *fotos.values()]} - {None}:
        rostos_video.apagar_pasta_de_rostos(nome)
    rostos_video.limpar_antigas()
    # Uma frente preparada já foi copiada para o personagem: as opções desse preparo (a escolhida e as outras) saem da input
    m = re.match(rf"{personagens.PREFIXO_FRENTE}([0-9a-f]{{8}})_", origem.name)
    if m:
        for pasta_frente in (entrada.pasta_envios(), config.ENTRADA):
            for f in pasta_frente.glob(f"{personagens.PREFIXO_FRENTE}{m.group(1)}_*.png"):
                f.unlink(missing_ok=True)
    personagens.limpar_frentes_antigas()
    if ficha:
        if usar_base:
            pasta = personagens.pasta_de(pid)
            ficha_personagem.copiar(pasta / "frente.png", pasta / ficha_personagem.ARQUIVOS["frente"])
            return {"id": pid, "fila": 0}
        return {"id": pid, **tarefa.tarefa.iniciar_ficha(pid)}
    if angulos and personagens.faltam(pid):
        tarefa.tarefa.iniciar_personagem(pid)
    return {"id": pid}


def acao_personagem_frente(d):
    """Preparar a frente: o Klein troca a roupa e/ou põe o fundo cinza na foto de frente, em 2 opções (personagens.preparar_frente).
    Leva ~1 min e roda na hora, como a pintura do Editar vídeo (a mesma trava: nenhuma geração começa no meio)."""
    import random
    _placa_livre_para_pintar()
    origem = _origem_personagem(d)
    roupa = d.get("roupa") or ""
    if not isinstance(roupa, str) or len(roupa) > 300:
        raise Erro("A roupa ficou grande demais (até 300 caracteres).")
    roupa = roupa.strip()
    fundo = d.get("fundo") or "cinza"
    if fundo not in ("cinza", "manter"):
        raise Erro("Fundo desconhecido.")
    if not roupa and fundo == "manter":
        raise Erro("Escreva a roupa ou escolha o fundo cinza: do jeito que está, a foto não muda.")
    codigo = _codigo_editar(d)
    if not _editando.acquire(blocking=False):
        raise Erro("Já estou pintando uma imagem. Espere terminar.", 409)
    try:
        exigir_comfy_livre(pintando_ok=True)
        # A IA (tradução da roupa) e o Klein rodam no ComfyUI: o modelo de conversa do LM Studio sai da placa antes
        lmstudio.descarregar()
        personagens.limpar_frentes_antigas()
        t0 = time.time()
        try:
            r = personagens.preparar_frente(origem, roupa, fundo == "cinza", codigo, [random.randrange(2**31) for _ in range(2)])
        except RuntimeError as e:
            raise Erro(f"O Klein não preparou a frente: {e}", 500)
        return {"codigo": codigo, "opcoes": [{"arquivo": n, "url": f"/entrada/foto/{n}"} for n in r["opcoes"]], "roupa_en": r["roupa_en"], "ia": r["ia"],
                "segundos": round(time.time() - t0)}
    finally:
        _editando.release()


def acao_personagem_angulos(d):
    """Gera os ângulos que faltam. Com `angulo`, apaga esse e gera de novo (refazer um ângulo que saiu ruim)."""
    pid = d.get("id") or ""
    try:
        if d.get("angulo"):
            personagens.apagar_angulo(pid, d["angulo"])
        if not personagens.faltam(pid):
            raise Erro("Esse personagem já tem todos os ângulos.", 409)
    except ValueError as e:
        raise Erro(str(e), 404)
    exigir_comfy_livre()
    tarefa.tarefa.iniciar_personagem(pid)


def exigir_modelo_ficha():
    if t2i.arquivos_que_faltam("klein_edit"):
        raise Erro("Instale o FLUX.2 Klein na aba Modelos para gerar a ficha.", 409)


def acao_personagem_ficha(d):
    pid = d.get("id") or ""
    etapa = d.get("etapa") or "frente"
    if etapa not in (*ficha_personagem.VISTAS, "aprovar", "completar", "usar-base", "roupa", "h3"):
        raise Erro("Etapa da ficha desconhecida.")
    try:
        pasta = personagens.pasta_de(pid)
    except ValueError as e:
        raise Erro(str(e), 404)
    marca, aprovada = ficha_personagem.estado(pasta)
    if etapa in ("completar", "rosto", "perfil", "costas", "h3") and not aprovada:
        raise Erro("Aprove a frente de corpo inteiro primeiro.", 409)
    if etapa == "aprovar" and ("frente" not in marca or d.get("marca") != marca["frente"]):
        raise Erro("Confira a versão atual da frente antes de aprovar.", 409)
    foto = d.get("foto")
    if foto or etapa == "usar-base":
        if etapa not in (*ficha_personagem.VISTAS, "usar-base", "roupa"):
            raise Erro("Essa etapa não aceita uma foto.")
        t = tarefa.tarefa
        with t.trava:
            if (t.rodando() and t.projeto == pid) or t.fila.tem(pid):
                raise Erro("Espere a geração deste personagem terminar.", 409)
            origem = pasta / "frente.png" if etapa == "usar-base" else _origem_personagem({"foto": foto})
            arquivo = ficha_personagem.ROUPA if etapa == "roupa" else ficha_personagem.ARQUIVOS["frente" if etapa == "usar-base" else etapa]
            try:
                ficha_personagem.copiar(origem, pasta / arquivo)
                if etapa != "roupa":
                    ficha_personagem.montar(pasta)
            except OSError as e:
                raise Erro("Não foi possível usar essa foto na ficha.") from e
        return {"fila": 0}
    if etapa == "roupa":
        raise Erro("Envie uma foto da roupa.")
    if etapa == "h3":
        faltam = ficha_personagem.faltam_h3()
        if faltam:
            raise Erro(f"Para a ficha pelo H3 faltam no ComfyUI: {', '.join(faltam)}.", 409)
    else:
        exigir_modelo_ficha()
    exigir_comfy_livre()
    return tarefa.tarefa.iniciar_ficha(pid, etapa)


def acao_personagem_nova_roupa(d):
    """Nova roupa: cria outro personagem com a mesma foto de frente e a roupa nova (texto e/ou foto) e já prepara a frente
    da ficha com ela. O personagem original fica como está."""
    roupa = d.get("roupa") or ""
    if not isinstance(roupa, str) or len(roupa) > 300:
        raise Erro("A roupa ficou grande demais (até 300 caracteres).")
    foto = _origem_personagem({"foto": d["foto"]}) if d.get("foto") else None
    exigir_modelo_ficha()
    exigir_comfy_livre()
    try:
        pid = personagens.criar_com_nova_roupa(d.get("id") or "", d.get("nome"), roupa, foto, d.get("visual") or "")
    except ValueError as e:
        raise Erro(str(e))
    return {"id": pid, **tarefa.tarefa.iniciar_ficha(pid)}


def acao_personagem_expressao(d):
    """Guarda (`foto`, ja enviada para a entrada do ComfyUI) ou apaga (`apagar`, o nome do arquivo) uma foto de expressao do
    personagem (personagens.gravar_expressao). Devolve a lista atual. As fotos valem para a pessoa: os visuais dela usam as mesmas."""
    pid = d.get("id") or ""
    try:
        if d.get("apagar"):
            personagens.apagar_expressao(pid, str(d["apagar"]))
        else:
            foto = nome_limpo(d.get("foto") or "")
            if not foto or not entrada.existe(foto):
                raise Erro("Envie a foto de novo: o arquivo não foi encontrado.")
            personagens.gravar_expressao(pid, entrada.caminho(foto))
        return {"expressoes": personagens.ler(pid)["expressoes"]}
    except ValueError as e:
        raise Erro(str(e), 409 if "Apague uma" in str(e) else 404)
    except OSError:
        raise Erro("Não consegui ler essa imagem. Envie um PNG, JPG ou WebP.")


def acao_personagem_apagar(d):
    pid = d.get("id") or ""
    if d.get("confirmar") is not True:
        raise Erro("Confirme para apagar o personagem.", 409)
    parte = d.get("parte")
    # Apagar a pessoa leva todos os visuais: qualquer pasta dela gerando ou na fila trava
    try:
        grupos = personagens_agrupados()
    except (OSError, ValueError):
        grupos = {}
    alvo = grupos.get(pid, (pid, ""))[0]
    ids = {i for i, (p, _) in grupos.items() if p == alvo} | {pid} if parte is None else {pid}
    if tarefa.tarefa.rodando() and tarefa.tarefa.tipo == "personagem" and tarefa.tarefa.projeto in ids:
        raise Erro("Esse personagem está sendo gerado. Pare a geração antes.", 409)
    fila = getattr(tarefa.tarefa, "fila", None)
    if fila and any(i["tipo"] == "personagem" and i["projeto"] in ids for i in fila.resumo()["itens"]):
        raise Erro("Esse personagem está na fila. Retire o pedido da fila antes de apagar.", 409)
    try:
        if parte is None:
            personagens.apagar_pessoa(pid)
        elif parte == "visual":
            personagens.apagar_visual(pid)
        elif parte in ficha_personagem.PARTES:
            ficha_personagem.apagar_parte(personagens.pasta_de(pid), parte)
        else:
            raise Erro("Parte do personagem desconhecida.")
    except ValueError as e:
        raise Erro(str(e), 404)


def personagens_agrupados():
    return personagens.visuais.agrupar(personagens.listar())


def acao_personagem_rostos(d):
    """Os melhores rostos de cada ângulo de um vídeo enviado (rostos_video.py). Roda na CPU, na hora: não usa a placa nem a fila."""
    nome = d.get("video") or ""
    video = config.ENVIOS / nome_limpo(nome)
    if not nome or nome_limpo(nome) != nome or video.suffix.lower() != ".mp4" or not video.is_file():
        raise Erro("O vídeo não foi encontrado. Envie de novo.", 404)
    pasta = rostos_video.pasta_do_video(video)
    try:
        r = rostos_video.extrair(video, pasta)
    except rostos_video.Ocupado as e:
        raise Erro(str(e), 409)
    except ValueError as e:
        raise Erro(f"Não consegui ler o vídeo ({e}).")
    for a in rostos_video.ANGULOS:
        for c in r[a]:
            c["url"] = f"/rostos/{pasta.name}/{c['arquivo']}"
            if c.get("quadro"):
                c["url_quadro"] = f"/rostos/{pasta.name}/{c['quadro']}"
    return {**r, "pasta": pasta.name}


def acao_personagem_rosto_usar(d):
    """Copia o rosto escolhido para a input do ComfyUI; a página o usa como a foto de um ângulo (como /api/enviar faria)."""
    try:
        origem = rostos_video.caminho_candidato(d.get("pasta") or "", d.get("arquivo") or "")
    except ValueError:
        raise Erro("Imagem não encontrada.", 404)
    nome = f"{origem.parent.name}_{origem.name}"
    shutil.copyfile(origem, entrada.novo(nome))
    with Image.open(origem) as im:
        largura, altura = im.size
    r = {"arquivo": nome, "largura": largura, "altura": altura}
    # O lado medido no vídeo (quadro inteiro) vale mais que detectar de novo no recorte: num perfil o YuNet muitas vezes não acha o rosto
    try:
        lista = json.loads((origem.parent / "candidatos.json").read_text(encoding="utf-8"))
        c = next((c for a in rostos_video.ANGULOS for c in lista.get(a, []) if c.get("arquivo") == origem.name), None)
        if c is not None:
            r["direita"] = c["giro"] > 0
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return r


def acao_fila(d):
    """Os botões do painel da fila: pausar, continuar, tirar um pedido, subir ou descer."""
    f, acao = tarefa.tarefa.fila, d.get("acao")
    try:
        if acao == "pausar":
            with tarefa.tarefa.trava:
                f.pausar("Você pausou a fila.")
        elif acao == "continuar":
            # A fila retomada começa a próxima geração assim que o ComfyUI parece livre, e quem pinta (Editar vídeo, a frente de
            # um personagem) deixa o ComfyUI livre entre um passo e outro: as duas iriam juntas para a placa
            if _editando.locked():
                raise Erro("Uma imagem está sendo pintada (Editar vídeo ou a frente de um personagem). Continue a fila quando terminar (1 a 2 min).", 409)
            f.continuar()
        elif acao == "tirar":
            f.tirar(d.get("id"))
        elif acao in ("subir", "descer"):
            f.mover(d.get("id"), -1 if acao == "subir" else 1)
        else:
            raise Erro("Ação da fila desconhecida.")
    except KeyError:
        raise Erro("Esse pedido não está mais na fila.", 404)
    return f.resumo()


def acao_personagem_usar(d):
    """A página escolhe um personagem na Trocar ou no Imagem para vídeo: copia a frente e os ângulos para a input do
    ComfyUI e devolve os nomes, que a página usa como foto e como outros ângulos."""
    try:
        f = personagens.ler(d.get("id") or "")
        foto, angulos = personagens.para_entrada(f["id"], sem_costas=d.get("sem_costas") is True,
                                                 modo="cabeca" if d.get("modo") == "cabeca" else "corpo")
    except ValueError as e:
        # visual sem a frente aprovada é conflito de estado, não personagem inexistente
        raise Erro(str(e), 409 if "Aprove a frente" in str(e) else 404)
    return {"id": f["id"], "nome": f["nome"], "foto": foto, "angulos": angulos}
