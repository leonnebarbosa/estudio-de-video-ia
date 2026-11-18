"""Erro de validacao, limites e padroes de cada aba, e a conferencia do que a pagina envia."""
import re

import config
import ambiente, envio, extras
from imagem_para_video import CAMERAS, DURACAO_MAX_POR_MP, DURACAO_MAX_SEGUINTES, DURACOES, QUEM_PADRAO, VOZ_PADRAO, duracao_maxima, limpar
from wan_para_video import MODELOS_WAN, arquivos_que_faltam
from texto_para_imagem import MAX_LORAS_TEXTO, MODELOS_TEXTO, arquivos_que_faltam as faltam_texto, loras_compativeis


# Valores padrao do script: 107 quadros por rodada, 22 de sobreposicao, 85 novos, 24 quadros por segundo
FPS, QUADROS_RODADA, SOBREPOSICAO = 24, 107, 22
NOVOS = QUADROS_RODADA - SOBREPOSICAO
PROPORCOES = ["1:1 (Square)", "2:3 (Portrait Photo)", "3:2 (Photo)", "3:4 (Portrait Standard)", "4:3 (Standard)", "9:16 (Portrait Widescreen)", "16:9 (Widescreen)", "21:9 (Ultrawide)"]
PARAMETROS = "interface.json"
PADRAO = {"modelo": "minimax_h3_ref2va_pruned_int8_convrot.safetensors", "loras": [["minimax_h3_DMAD_4step_full_lora_avg_rank_39_bf16.safetensors", 1.0]], "sampler": "er_sde", "agendador": "beta",
          "passos": 6, "megapixels": 0.5, "proporcao": "16:9 (Widescreen)", "tentativas": 3, "semente": None}
QUALIDADES = (0.5, 0.65, 0.8)
# Configuracao validada em 05/11/2026; 5 s derrubou a placa, por isso o limite de duracao.
# A segunda passagem ("upscale") derrubou a placa 3 vezes seguidas em 11/11/2026, a 0,8 e a 0,5 MP; sem ela, ampliando
# depois com o ESRGAN do acabamento (fora do ComfyUI, ~1 GB), nunca caiu. Por isso o padrao virou "esrgan" e upscale desligado.
PADRAO_TROCA = {"modelo": "minimax_h3_ref2va_pruned_int8_convrot.safetensors", "troca": ["minimax_h3_character_swap_v1.1_ref2va_fro.safetensors", 1.0], "turbo": ["minimax_h3_dmd_ref2va_8step_turbo_pruned.safetensors", 1.0],
                "nitidez": ["minimax_h3_lms_v1.0_r64.safetensors", 0.7], "upscale": False, "upscale_mesma": False, "upscale_megapixels": 1.0, "upscaler": "h3_upscaler_lms_v0.1.safetensors", "megapixels": 0.2,
                # Agendador beta desde 16/11/2026: o perfil que o autor da Head Swap publica (Henge). No teste ficou igual ao simple
                "proporcao": "16:9 (Widescreen)", "passos": 8, "sampler": "euler", "agendador": "beta", "semente": None, "audio_original": True, "pouca_vram": False, "dividir_blocos": False,
                # De onde vem a roupa: "video" troca so a identidade (roupa, acessorios e trocas de roupa seguem o video); "foto" e o body_swap original
                "roupa": "video",
                # Ate 2 LoRAs de estilo [nome, forca], da mesma lista do Imagem para video (ambiente.lora_de_estilo), nas duas passagens
                "loras": [],
                # Amplia o final.mp4 com o ESRGAN depois da troca, sem a segunda passagem (as duas nao vao juntas)
                "esrgan": True,
                # Roupa do video: a Head Swap recebe so a cabeca da foto (SAM 3.1), senao a roupa da foto vaza a 0,5 MP (17/11/2026)
                "recortar_cabeca": True,
                # Borra o rosto de quem esta no video-guia (source_blur do autor da Head Swap): o formato do rosto original
                # vazava. Em teste desde 17/11/2026, por isso desligado
                "borrar_rosto": False,
                # Quem faz a troca: "estudio" (Head Swap/Character Swap no ComfyUI) ou "wangp" (Viggle Remake no WanGP, troca_wangp.py)
                "motor": "estudio"}
ROUPAS_TROCA = ("video", "foto")
MOTORES_TROCA = ("estudio", "wangp")
# WanGP (Viggle Remake): uma janela tem ate 345 quadros (14,4 s). Mais que isso o WanGP faria janelas com um prompt para
# cada uma, e o troca_wangp escreve um so. Gera no minimo 90 quadros (3,75 s) e corta no tamanho pedido.
DURACAO_MAX_TROCA_WANGP = 14
QUADROS_MIN_WANGP = 90
# Texto para imagem (Chroma1-HD-Flash): 0,9 MP medido em 09/11/2026, ~40 s por imagem e 9,5 GB de pico na 3080
NEGATIVO_TEXTO = ("blurry, low quality, jpeg artifacts, watermark, text, logo, signature, deformed, extra limbs, extra fingers, bad hands, "
                  "bad anatomy, mutated, disfigured")
# Padrao de fabrica: o Z-Image Turbo, que vem no pacote inicial do instalador (todo mundo tem); o Chroma fica como opcao
PADRAO_TEXTO = {"modelo": "z_image_turbo", "prompt": "", "negativo": NEGATIVO_TEXTO, "proporcao": "2:3 (Portrait Photo)", "megapixels": 0.9, "quantidade": 1, "passos": 8, "semente": None,
                # Ate 2 LoRAs [nome, forca], so as que servem para o modelo escolhido (texto_para_imagem.familia_lora)
                "loras": [],
                # Img2img: arquivo da imagem de partida na entrada do ComfyUI (None: parte do zero) e quanto o modelo refaz (denoise)
                "partida": None, "forca_partida": 0.6,
                # So no Editar imagem: uma segunda imagem de onde a instrucao tira algo (roupa, objeto, fundo)
                "referencia": None}
QUALIDADES_TEXTO = (0.5, 0.9, 1.3)
MAX_IMAGENS_TEXTO = 4
# Desde 16/11/2026 a troca passa disso em janelas com emenda (trocar_personagem.janelas): cada janela tem no maximo o
# tamanho que ja rodou numa passada so (DURACAO_MAX_TROCA_POR_MP), entao a carga na placa e a mesma. 15 s como no
# Imagination Studio, de onde veio a receita. Com a segunda passagem (upscale) nao ha janelas: vale o limite da passada.
DURACAO_MAX_TROCA = 15
# Por resolucao da primeira passagem: (ate quantos MP, ate quantos segundos) numa passada so, que e tambem o tamanho de
# cada janela. Em 11/11/2026 uma troca de 5 s a 0,8 MP caiu na primeira passagem; as de 2 a 3,5 s a 0,8 MP passaram. A
# 0,5 MP, 5 s seguem valendo.
DURACAO_MAX_TROCA_POR_MP = ((0.5, 5), (0.8, 3.5))


def duracao_max_troca(megapixels):
    """O maximo numa passada so (o tamanho de uma janela)."""
    return next((s for mp, s in DURACAO_MAX_TROCA_POR_MP if float(megapixels) <= mp + 1e-9), min(s for _, s in DURACAO_MAX_TROCA_POR_MP))


def duracao_max_troca_total(megapixels, upscale=False):
    """O maximo da troca: em janelas ate DURACAO_MAX_TROCA; com a segunda passagem, so o de uma passada."""
    return duracao_max_troca(megapixels) if upscale else DURACAO_MAX_TROCA
QUALIDADES_TROCA = (0.2, 0.3, 0.5, 0.8)
QUALIDADES_UPSCALE = (0.6, 1.0)
PADRAO_IMAGEM = {"modelo": "h3", "proporcao": "3:2 (Photo)", "megapixels": 0.4746, "semente": None, "quem": "", "voz": "", "referencias": [], "acabamento": "nenhum",
                 "negativo": "blurry, low quality, jpeg artifacts, watermark, text, static image, deformed, extra limbs",
                 # So no Wan: o RIFE leva o video de 16 para 32 quadros por segundo no fim (ligado por padrao, pedido do usuario em 09/11)
                 "fluidez": True,
                 # So no H3: o modelo ref2va das tomadas 2 em diante (None: o oficial do grafo da continuacao). A tomada 1 e sempre o fl2va oficial
                 "seguintes": None,
                 # So no H3: o modelo da tomada 1 (None: o fl2va oficial). Um H3 ref2va da comunidade tambem parte da imagem (teste de 09/11/2026)
                 "primeira": None,
                 # Ate 2 LoRAs de estilo [nome, forca], em todas as tomadas. H3: as de H3 da pasta loras menos as tecnicas (ambiente.lora_de_estilo);
                 # Wan: os pares HIGH/LOW (loras.pares_wan), pelo nome da metade HIGH
                 "loras": [],
                 # So no H3 sem imagem (texto para video na tomada 1, testado em 10/11/2026): estilo, lugar e luz, em ingles
                 "cena": ""}
MAX_CENA = 1000
MAX_LORAS_VIDEO = 2
# 0,7 testada em 08/11/2026 em duas tomadas (640x1152, pico 9,7 GB, sem queda). 0,8 testada e aprovada em 11/11/2026 em 5 e 10 s
# (672x1216, pico 9,7 GB, sem queda). 1 MP: 3 e 4,25 s passaram; 10 s derrubou a placa (ver DURACAO_MAX_POR_MP)
QUALIDADES_IMAGEM = (0.3, 0.4746, 0.6, 0.7, 0.8, 1.0)
# esrgan: Full HD quadro a quadro; refino: segunda passagem do H3 em pedacos e depois Full HD (ver acabamento.py)
ACABAMENTOS = ("nenhum", "esrgan", "refino")
MAX_MP_REFINO = 0.7  # o refino vai ate 1 MP: acima disso quase nao amplia
MODELO_ESRGAN = config.MODELOS / "upscale_models" / "RealESRGAN_x2plus.pth"
MAX_TOMADAS = 6
# Modelos Wan na aba Imagem para video: 0,475 MP (576x864) e 5 s testados em 09/11/2026 nos dois (230 a 387 s por tomada, pico 9,8 GB)
QUALIDADES_WAN = (0.3, 0.475, 0.6)
DURACOES_WAN = (2, 3, 4, 5)
MAX_REFERENCIAS = 4
# Limites por tomada, em caracteres. Nao vem do modelo (o Qwen3-VL do H3 aceita bem mais): 1000 na acao barrava descricoes
# reais (pedido do usuario em 09/11/2026). A fala fica em 300, uns 20 s em portugues, ja muito alem dos 5 s de uma tomada
MAX_ACAO, MAX_FALA, MAX_SOM = 2000, 300, 300


from erros import Erro  # noqa: E402 (fica em erros.py para o instalador usar sem as dependencias daqui)


def pasta_projeto(nome):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,60}", nome or ""):
        raise Erro("Use só letras, números, - e _ no nome do projeto.")
    return config.PROJETOS / nome


def validar_ajustes(a):
    """Aceita so o que esta instalado e dentro dos limites; o que faltar fica no padrao testado."""
    o = ambiente.ler_opcoes()
    r = {**PADRAO, **{k: v for k, v in a.items() if k in PADRAO}}
    if r["modelo"] not in o["modelos"]:
        raise Erro("Modelo não encontrado no ComfyUI.")
    if r["sampler"] not in o["samplers"] or r["agendador"] not in o["agendadores"]:
        raise Erro("Sampler ou agendador desconhecido.")
    if r["proporcao"] not in PROPORCOES:
        raise Erro("Formato desconhecido.")
    try:
        r["megapixels"] = float(r["megapixels"])
        r["passos"] = int(r["passos"])
        r["tentativas"] = int(r["tentativas"])
        r["semente"] = None if r["semente"] in (None, "") else int(r["semente"])
        r["loras"] = [[str(n), round(float(f), 2)] for n, f in r["loras"]]
    except (TypeError, ValueError):
        raise Erro("Um dos ajustes não é um número válido.")
    if r["megapixels"] not in QUALIDADES:
        raise Erro("Qualidade desconhecida.")
    if not 2 <= r["passos"] <= 12:
        raise Erro("Use de 2 a 12 passos.")
    if not 1 <= r["tentativas"] <= 5:
        raise Erro("Use de 1 a 5 tentativas.")
    if r["semente"] is not None and not 0 <= r["semente"] < 2**48:
        raise Erro("Semente fora do limite.")
    nomes = [n for n, _ in r["loras"]]
    if len(nomes) > 2 or len(set(nomes)) != len(nomes):
        raise Erro("Escolha até duas LoRAs diferentes.")
    for n, f in r["loras"]:
        if n not in o["loras"]:
            raise Erro(f"LoRA não disponível nesta página: {n}")
        if not 0 <= f <= 1.5:
            raise Erro("Use força de LoRA entre 0 e 1,5.")
    return r


def validar_troca(a):
    """Aceita so o que esta instalado, na lista do modo e dentro dos limites."""
    o = ambiente.ler_opcoes()
    r = {**PADRAO_TROCA, **{k: v for k, v in a.items() if k in PADRAO_TROCA}}
    if r["modelo"] not in o["modelos"]:
        raise Erro("Modelo não encontrado no ComfyUI.")
    if r["sampler"] not in o["samplers"] or r["agendador"] not in o["agendadores"]:
        raise Erro("Sampler ou agendador desconhecido.")
    if r["proporcao"] not in PROPORCOES:
        raise Erro("Formato desconhecido.")
    if r["upscaler"] not in o["upscalers"]:
        raise Erro("Modelo de upscale não encontrado no ComfyUI.")
    try:
        r["megapixels"] = float(r["megapixels"])
        r["upscale_megapixels"] = float(r["upscale_megapixels"])
        r["passos"] = int(r["passos"])
        r["semente"] = None if r["semente"] in (None, "") else int(r["semente"])
        for chave in ("troca", "turbo", "nitidez"):
            if r[chave]:
                r[chave] = [str(r[chave][0]), round(float(r[chave][1]), 2)]
    except (TypeError, ValueError, IndexError):
        raise Erro("Um dos ajustes não é um número válido.")
    for chave in ("upscale", "upscale_mesma", "audio_original", "pouca_vram", "dividir_blocos", "esrgan", "recortar_cabeca", "borrar_rosto"):
        r[chave] = r[chave] is True
    if r["esrgan"]:
        # Ampliar com o ESRGAN substitui a segunda passagem
        r["upscale"] = False
        if not MODELO_ESRGAN.is_file():
            raise Erro(f"Falta o modelo do ESRGAN: {MODELO_ESRGAN.name} em models/upscale_models.")
    if not r["troca"]:
        raise Erro("Escolha a LoRA de troca de personagem.")
    for chave in ("troca", "turbo", "nitidez"):
        if r[chave]:
            if r[chave][0] not in o["loras_troca"][chave]:
                raise Erro(f"LoRA não disponível neste modo: {r[chave][0]}")
            if not 0 <= r[chave][1] <= 1.5:
                raise Erro("Use força de LoRA entre 0 e 1,5.")
    if r["megapixels"] not in QUALIDADES_TROCA or r["upscale_megapixels"] not in QUALIDADES_UPSCALE:
        raise Erro("Resolução desconhecida.")
    if r["upscale"] and not r["upscale_mesma"] and r["upscale_megapixels"] <= r["megapixels"]:
        raise Erro("A resolução final do upscale precisa ser maior que a da primeira passagem.")
    if not 2 <= r["passos"] <= 12:
        raise Erro("Use de 2 a 12 passos.")
    if r["semente"] is not None and not 0 <= r["semente"] < 2**48:
        raise Erro("Semente fora do limite.")
    if r["roupa"] not in ROUPAS_TROCA:
        raise Erro("Escolha de onde vem a roupa: do vídeo ou da foto.")
    if r["motor"] not in MOTORES_TROCA:
        raise Erro("Escolha quem faz a troca: o estúdio ou o WanGP.")
    if r["motor"] == "wangp":
        if not config.WANGP_PYTHON.is_file():
            raise Erro(f"O WanGP não está instalado em {config.WANGP}.")
        if r["upscale"]:
            raise Erro("A segunda passagem do H3 não vai com o WanGP. Use o ESRGAN para ampliar.")
        if r["loras"]:
            raise Erro("As LoRAs de estilo ainda não vão com o WanGP. Tire as LoRAs ou use o motor do estúdio.")
    validar_loras_video(r, {"fala": True})
    return r


def modelos_texto():
    """Os modelos do seletor da aba Texto para imagem, com os arquivos que faltam."""
    return [{"id": k, "nome": m["nome"], "ajuda": m["ajuda"], "passos": m["passos"], "familia": m["familia"], "edicao": bool(m.get("edicao")), "faltam": faltam_texto(k),
             "loras": loras_compativeis(k)} for k, m in MODELOS_TEXTO.items()]


def validar_texto(a):
    r = {**PADRAO_TEXTO, **{k: v for k, v in a.items() if k in PADRAO_TEXTO}}
    if r["modelo"] not in MODELOS_TEXTO:
        raise Erro("Modelo desconhecido.")
    faltam = faltam_texto(r["modelo"])
    if faltam:
        raise Erro(f"Faltam arquivos deste modelo no ComfyUI: {', '.join(faltam)}")
    r["prompt"] = limpar(r["prompt"])[:2000]
    if not r["prompt"]:
        raise Erro("Escreva o que deve aparecer na imagem.")
    r["negativo"] = limpar(r["negativo"])[:1000]
    if r["proporcao"] not in PROPORCOES:
        raise Erro("Formato desconhecido.")
    try:
        r["megapixels"] = float(r["megapixels"])
        r["quantidade"], r["passos"] = int(r["quantidade"]), int(r["passos"])
        r["semente"] = None if r["semente"] in (None, "") else int(r["semente"])
    except (TypeError, ValueError):
        raise Erro("Um dos ajustes não é um número válido.")
    if r["megapixels"] not in QUALIDADES_TEXTO:
        raise Erro("Resolução desconhecida.")
    if not 1 <= r["quantidade"] <= MAX_IMAGENS_TEXTO:
        raise Erro(f"Gere de 1 a {MAX_IMAGENS_TEXTO} imagens por vez.")
    if not 4 <= r["passos"] <= 24:
        raise Erro("Use de 4 a 24 passos.")
    if r["semente"] is not None and not 0 <= r["semente"] < 2**48:
        raise Erro("Semente fora do limite.")
    try:
        r["loras"] = [[str(n), round(float(f), 2)] for n, f in (r["loras"] or [])]
    except (TypeError, ValueError):
        raise Erro("A força de uma LoRA não é um número válido.")
    if MODELOS_TEXTO[r["modelo"]].get("edicao") and not r["partida"]:
        raise Erro("Escolha a imagem que vai ser editada (Imagem de partida).")
    if r["partida"]:
        r["partida"] = envio.nome_limpo(str(r["partida"]))
        if not (config.ENTRADA / r["partida"]).is_file():
            raise Erro("Envie a imagem de partida de novo: o arquivo não foi encontrado.")
        try:
            r["forca_partida"] = round(float(r["forca_partida"]), 2)
        except (TypeError, ValueError):
            raise Erro("A força da imagem de partida não é um número válido.")
        if not 0.05 <= r["forca_partida"] <= 1:
            raise Erro("Use força da imagem de partida entre 0,05 e 1.")
    else:
        r["partida"], r["forca_partida"] = None, PADRAO_TEXTO["forca_partida"]
    if r["referencia"] and MODELOS_TEXTO[r["modelo"]].get("edicao"):
        r["referencia"] = envio.nome_limpo(str(r["referencia"]))
        if not (config.ENTRADA / r["referencia"]).is_file():
            raise Erro("Envie a segunda imagem de novo: o arquivo não foi encontrado.")
    else:
        r["referencia"] = None
    nomes = [n for n, _ in r["loras"]]
    if len(nomes) > MAX_LORAS_TEXTO or len(set(nomes)) != len(nomes):
        raise Erro(f"Escolha até {MAX_LORAS_TEXTO} LoRAs diferentes.")
    if nomes:
        servem = loras_compativeis(r["modelo"])
        for n, f in r["loras"]:
            if n not in servem:
                raise Erro(f"Esta LoRA não serve para o modelo escolhido: {n}")
            if not 0 < f <= 2:
                raise Erro("Use força de LoRA entre 0 e 2.")
    return r


def situacao_troca_foto():
    """O que falta para a troca em foto: os arquivos do Klein (pacote Editar imagem) e, para o rosto, a LoRA de troca de cabeca."""
    import loras, troca_foto
    return {"faltam": faltam_texto("klein_edit"), "falta_lora_rosto": troca_foto.LORA_ROSTO.lower() not in loras.mapa(),
            "segundos_passada": troca_foto.SEGUNDOS_PASSADA}


def validar_troca_foto(a):
    """A troca em foto vira um projeto de texto (galeria, semente, Transformar em video): parte da foto da pessoa e troca o rosto,
    a roupa ou os dois, cada um vindo de outra foto (ver troca_foto). Devolve os parametros do projeto."""
    s = situacao_troca_foto()
    if s["faltam"]:
        raise Erro(f"Faltam arquivos do Editar imagem (FLUX.2 Klein) no ComfyUI: {', '.join(s['faltam'])}")
    fotos = {}
    for chave, oque in (("partida", "a foto da pessoa"), ("rosto", "a foto do rosto"), ("roupa", "a foto da roupa")):
        nome = a.get(chave)
        if not nome:
            fotos[chave] = None
            continue
        nome = envio.nome_limpo(str(nome))
        if not (config.ENTRADA / nome).is_file():
            raise Erro(f"Envie {oque} de novo: o arquivo não foi encontrado.")
        fotos[chave] = nome
    if not fotos["partida"]:
        raise Erro("Escolha a foto da pessoa que vai mudar.")
    if not fotos["rosto"] and not fotos["roupa"]:
        raise Erro("Escolha a foto do rosto novo, a da roupa nova ou as duas.")
    if fotos["rosto"] and s["falta_lora_rosto"]:
        raise Erro("Falta a LoRA de troca de rosto (bfs_head_v1_flux-klein_4b.safetensors). Baixe o pacote Editar imagem de novo.")
    try:
        quantidade = int(a.get("quantidade", 1))
        semente = None if a.get("semente") in (None, "") else int(a["semente"])
    except (TypeError, ValueError):
        raise Erro("Um dos ajustes não é um número válido.")
    if not 1 <= quantidade <= MAX_IMAGENS_TEXTO:
        raise Erro(f"Gere de 1 a {MAX_IMAGENS_TEXTO} imagens por vez.")
    if semente is not None and not 0 <= semente < 2**48:
        raise Erro("Semente fora do limite.")
    trocas = " e ".join(k for k in ("rosto", "roupa") if fotos[k])
    # O prompt so descreve o projeto (Projetos e o historico mostram); os pedidos de verdade sao os fixos de troca_foto
    return {**PADRAO_TEXTO, "modelo": "klein_edit", "prompt": f"Troca em foto: {trocas}", "negativo": "", "passos": MODELOS_TEXTO["klein_edit"]["passos"],
            "quantidade": quantidade, "semente": semente, "partida": fotos["partida"], "referencia": None,
            "troca_foto": {"rosto": fotos["rosto"], "roupa": fotos["roupa"]}}


def validar_tomadas(tomadas, duracoes=DURACOES, com_fala=True):
    """com_fala=False (Wan): a fala e o som ficam guardados, mas cada tomada precisa da acao."""
    if not isinstance(tomadas, list) or not 1 <= len(tomadas) <= MAX_TOMADAS:
        raise Erro(f"Use de 1 a {MAX_TOMADAS} tomadas.")
    saida = []
    for i, t in enumerate(tomadas, 1):
        if not isinstance(t, dict):
            raise Erro(f"A tomada {i} veio incompleta.")
        acao, fala, som = (limpar(t.get(k)) for k in ("acao", "fala", "som"))
        if not acao and (not fala or not com_fala):
            raise Erro(f"Tomada {i}: escreva o que acontece." if not com_fala else f"Tomada {i}: escreva o que acontece ou a fala.")
        if len(acao) > MAX_ACAO:
            raise Erro(f"Tomada {i}: a ação passou de {MAX_ACAO} caracteres ({len(acao)}).")
        if len(fala) > MAX_FALA or len(som) > MAX_SOM:
            raise Erro(f"Tomada {i}: a fala ou os sons passaram de {MAX_FALA} caracteres.")
        if t.get("camera") not in CAMERAS:
            raise Erro(f"Tomada {i}: movimento de câmera desconhecido.")
        try:
            duracao = float(t.get("duracao"))
        except (TypeError, ValueError):
            raise Erro(f"Tomada {i}: duração inválida.")
        if duracao not in duracoes:
            raise Erro(f"Tomada {i}: duração fora das opções.")
        saida.append({"acao": acao, "fala": fala, "som": som, "camera": t["camera"], "olhar": t.get("olhar") is True, "duracao": duracao})
    return saida


def validar_duracoes_h3(tomadas, megapixels):
    """No H3, cada tomada respeita o limite da resolucao (imagem_para_video.DURACAO_MAX_POR_MP); da segunda em diante, ate
    DURACAO_MAX_SEGUINTES. Chamada depois de validar_tomadas, com as duracoes ja convertidas."""
    for i, t in enumerate(tomadas, 1):
        limite = duracao_maxima(megapixels, i == 1)
        if t["duracao"] <= limite:
            continue
        br = lambda x: f"{x:g}".replace(".", ",")
        if i > 1 and t["duracao"] <= duracao_maxima(megapixels):
            raise Erro(f"Tomada {i}: tomadas de mais de {DURACAO_MAX_SEGUINTES} s só valem na tomada 1. As seguintes recebem mais 2 s da anterior "
                       f"e assim ainda não foram testadas. Use até {DURACAO_MAX_SEGUINTES} s ou junte a fala na tomada 1.")
        raise Erro(f"Tomada {i}: {br(t['duracao'])} s passa do limite de {br(limite)} s a {br(megapixels)} MP. 10 s só foi aprovado até 0,8 MP; "
                   f"a 1 MP, 10 s derrubou a placa. Reduza a duração ou a resolução.")


def validar_acabamento(modo, megapixels):
    if modo not in ACABAMENTOS:
        raise Erro("Acabamento desconhecido.")
    if modo != "nenhum" and not MODELO_ESRGAN.is_file():
        raise Erro(f"Falta o modelo do ESRGAN: {MODELO_ESRGAN.name} em models/upscale_models.")
    if modo == "refino" and megapixels > MAX_MP_REFINO:
        raise Erro("O refino do H3 só vale até 0,7 MP: acima disso ele quase não amplia. Use só o ESRGAN.")


def modelos_imagem():
    """Os modelos da aba Imagem para video, na ordem do seletor, com o que cada um aceita. O H3 vem sempre instalado
    (as outras abas dependem dele); os do Wan dizem os arquivos que faltam."""
    h3 = {"id": "h3", "nome": "MiniMax H3", "ajuda": "Com fala, som e a mesma voz em todas as tomadas. 24 quadros por segundo.",
          "fala": True, "fps": 24, "qualidades": list(QUALIDADES_IMAGEM), "duracoes": list(DURACOES), "acabamentos": list(ACABAMENTOS),
          # A pagina mostra so as duracoes permitidas na resolucao escolhida: [ate MP, ate s] e o limite das tomadas seguintes
          "duracao_max_por_mp": [list(x) for x in DURACAO_MAX_POR_MP], "duracao_max_seguintes": DURACAO_MAX_SEGUINTES,
          "padrao": {"megapixels": 0.4746}, "fluidez": False, "faltam": []}
    ajuda = {"wan22": "Sem som. O Wan 2.2 oficial, com a LoRA de 4 passos. 16 quadros por segundo.", **extras.secao("ajuda_wan")}
    wans = [{"id": k, "nome": m["nome"], "ajuda": ajuda.get(k, ""), "fala": False, "fps": 16, "qualidades": list(QUALIDADES_WAN), "duracoes": list(DURACOES_WAN),
             "acabamentos": ["nenhum", "esrgan"], "padrao": {"megapixels": 0.475}, "fluidez": True, "faltam": arquivos_que_faltam(k)} for k, m in MODELOS_WAN.items()]
    return [h3, *wans]


def validar_loras_video(r, m):
    """LoRAs de estilo. No H3, so as que o ComfyUI lista e ambiente.lora_de_estilo aceita. No Wan, so os pares HIGH/LOW
    (loras.pares_wan), guardados pelo nome da metade HIGH; a LOW e achada na hora de gerar."""
    if not isinstance(r["loras"], list) or len(r["loras"]) > MAX_LORAS_VIDEO:
        raise Erro(f"Use até {MAX_LORAS_VIDEO} LoRAs de estilo.")
    try:
        r["loras"] = [[str(n), round(float(f), 2)] for n, f in r["loras"]]
    except (TypeError, ValueError):
        raise Erro("A força de uma LoRA de estilo não é um número válido.")
    nomes = [n for n, _ in r["loras"]]
    if len(set(nomes)) != len(nomes):
        raise Erro("Escolha LoRAs de estilo diferentes.")
    if not nomes:
        return
    o = ambiente.ler_opcoes()
    aprovadas = o["loras_estilo"] if m["fala"] else [x["alta"] for x in o.get("loras_wan", [])]
    for n, f in r["loras"]:
        if n not in aprovadas:
            raise Erro(f"Esta LoRA não é uma LoRA de estilo de H3 instalada: {n}" if m["fala"] else f"Esta LoRA não é um par HIGH + LOW de Wan instalado: {n}")
        if not 0 < f <= 1.5:
            raise Erro("Use força de LoRA de estilo entre 0,05 e 1,5.")


def validar_imagem(a):
    """Aceita so o que esta na lista do modelo escolhido e dentro dos limites."""
    r = {**PADRAO_IMAGEM, **{k: v for k, v in a.items() if k in PADRAO_IMAGEM}}
    m = next((x for x in modelos_imagem() if x["id"] == r["modelo"]), None)
    if m is None:
        raise Erro("Modelo desconhecido.")
    if m["faltam"]:
        raise Erro(f"Faltam arquivos deste modelo no ComfyUI: {', '.join(m['faltam'])}")
    if r["proporcao"] not in PROPORCOES:
        raise Erro("Formato desconhecido.")
    try:
        r["megapixels"] = float(r["megapixels"])
        r["semente"] = None if r["semente"] in (None, "") else int(r["semente"])
    except (TypeError, ValueError):
        raise Erro("Um dos ajustes não é um número válido.")
    if r["megapixels"] not in m["qualidades"]:
        raise Erro("Resolução desconhecida para este modelo.")
    if r["semente"] is not None and not 0 <= r["semente"] < 2**48 - 10000:
        raise Erro("Semente fora do limite.")
    if r["acabamento"] not in m["acabamentos"]:
        raise Erro("Este acabamento não vale para este modelo.")
    validar_acabamento(r["acabamento"], r["megapixels"])
    r["negativo"] = limpar(r["negativo"])[:1000]
    r["fluidez"] = r["fluidez"] is True and m["fluidez"]
    if not m["fala"] or not r["seguintes"]:
        r["seguintes"] = None
    elif r["seguintes"] not in ambiente.ler_opcoes()["modelos"]:
        raise Erro("O modelo das tomadas seguintes não está instalado no ComfyUI.")
    if not m["fala"] or not r["primeira"]:
        r["primeira"] = None
    elif r["primeira"] not in ambiente.ler_opcoes()["modelos"] or r["primeira"] == PADRAO["modelo"]:
        raise Erro("O modelo da tomada 1 não está instalado no ComfyUI.")
    validar_loras_video(r, m)
    r["quem"], r["voz"] = limpar(r["quem"])[:200] or QUEM_PADRAO, limpar(r["voz"])[:200] or VOZ_PADRAO
    r["cena"] = limpar(r["cena"])[:MAX_CENA] if m["fala"] else ""
    if not m["fala"]:
        # O Wan parte so da imagem principal: os outros angulos nao entram
        r["referencias"] = []
    if not isinstance(r["referencias"], list) or len(r["referencias"]) > MAX_REFERENCIAS:
        raise Erro(f"Use até {MAX_REFERENCIAS} imagens extras do personagem.")
    r["referencias"] = [envio.nome_limpo(str(x)) for x in r["referencias"]]
    if len(set(r["referencias"])) != len(r["referencias"]):
        raise Erro("A mesma imagem extra foi escolhida duas vezes.")
    for x in r["referencias"]:
        if not (config.ENTRADA / x).is_file():
            raise Erro(f"Envie de novo a imagem extra: {x}")
    r["tomadas"] = validar_tomadas(a.get("tomadas"), m["duracoes"], m["fala"])
    if m["fala"]:
        validar_duracoes_h3(r["tomadas"], r["megapixels"])
    return r
