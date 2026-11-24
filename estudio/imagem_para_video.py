"""Transforma uma imagem em video, uma tomada por vez, com falas e a mesma voz do comeco ao fim.

Uso, normalmente pela interface:
  python -I imagem_para_video.py --projeto nome

Os ajustes vem de <projeto>/interface.json e a imagem de <projeto>/estado.json. As tomadas prontas ficam
guardadas no estado: se a placa cair, a geracao continua da tomada seguinte.
A primeira tomada usa o modelo fl2va, que parte da imagem. As outras usam o fluxo da continuacao, com ref2va.
Sem imagem (so no H3), a tomada 1 sai so do texto e um quadro dela vira o personagem das seguintes.
Saidas em projetos\\<projeto>: final.mp4, tomadaN_vK.mp4, progresso.json, gpu.csv
Codigos de saida: 0 ok, 3 servidor caiu, 4 falha da geracao, 5 temperatura.
"""
import argparse, json, math, os, random, re, shutil, subprocess, sys, time, types
from pathlib import Path

import av
import imageio_ffmpeg
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import caminhos, config, entrada, entrada_temp, loras, video_avancado
from continuar_video import FPS, Monitor, aplicar_ganho, cor_fundo, ganho_na_emenda, grafo_geracao, juntar, ler_quadros, medir_emenda, rodar, salvar_quadro
from trocar_personagem import acompanhar, arquivo_de_saida
from detalhe_comfy import Detalhe
import wan_para_video as wan

# Com 22 quadros de sobreposicao, o inicio de cada fala sumia: nessa faixa o audio vem da tomada anterior
SOBREPOSICAO = 5
CONTEXTO = 2.0
PASSOS_PRIMEIRA, PASSOS_CONTINUACAO = 8, 6
# Modelo ref2va ja destilado (um Turbo da comunidade): sem a LoRA de aceleracao do grafo, 8 passos e euler/simple, como o autor recomenda
PASSOS_TURBO, SAMPLER_TURBO, AGENDADOR_TURBO = 8, "euler", "simple"
# LoRA de aceleracao de um ref2va da comunidade na tomada 1 (o fl2va oficial usa a turbo do fl2v). Testado em 20/11/2026 com o Singularity V2
# (testes_troca/singularity_2026-11-20): mesma semente, 233 s contra 235 s do ref2va oficial, fala certa, visual com mais cara de filme
TURBO_REF2V = "minimax_h3_ref2v_turbo_8step_v1.1_768p_comfyui_bf16.safetensors"

# Pele natural: a receita do video do Willian IA (youtu.be/t33USkc8ll8), testada em 20/11/2026 em testes_troca/pele_2026-11-20 (close 9:16 a
# 0,8 MP, 5 s, mesma semente) e escolhida pelo usuario como a mais realista: Singularity ref2va + a LoRA de aceleracao EMA-600 + a Realism
# People a 0,8, euler/beta, 8 passos, desvio de sigma 12/3, e um paragrafo de pele no prompt. 350 s contra 312 s do modelo turbo, pico de 9,9 GB.
# A tomada 1 usa a foto como referencia (<Picture 1>), como no teste: o video nao comeca exatamente no quadro da foto.
PELE_MODELO = "Minimax-h3_Singularity_ref2va_v2_pruned_int8.safetensors"
PELE_LORAS = (("minimax_h3_turbo_v4_step600_ema.safetensors", 1.0), ("h3-realism-people-t2v-i2v-r2v.safetensors", 0.8))
PELE_PASSOS, PELE_SAMPLER, PELE_AGENDADOR, PELE_DESVIO = 8, "euler", "beta", (12.0, 3.0)
# So palavras positivas: "glow", "dewy", "flawless" e negacoes como "not plastic" trazem o efeito que citam. A versao leve (sem sardas nem
# desigualdade de tom): com elas o modelo pos manchas que a foto nao tinha
PELE_TEXTO = ("<Subject 1>'s skin is real unretouched skin with a dry, velvety matte surface, visible fine pores across the cheeks and nose, "
              "fine peach fuzz along the cheeks and jawline softly catching the light. Individual eyelashes crisp, natural moisture in the eyes.")
PELE_LUZ = "<Subject 1>'s face is lit by a large, soft, diffused key light from the front, slightly above the lens, even across the cheeks, forehead and nose."
PELE_RETER = "<Subject 1>'s skin: fully_preserved - dry matte natural surface with visible pores for the whole video."
# Sem dizer o enquadramento, o primeiro teste pelo estudio (20/11, foto de busto) saiu com o rosto enchendo a tela e a testa cortada; "o mesmo
# enquadramento de <Picture 1>" nao mudou nada. No teste aprovado o prompt dizia o plano com todas as letras, como aqui
PELE_LUGAR_PADRAO = "A simple, bright room; behind <Subject 1>, softly blurred, the walls and a few objects of the room are clearly visible."
PELE_ENQUADRAR = ("Framing: a medium close-up from the chest up, <Subject 1>'s whole head and hair in frame with a little space above the head, "
                  "the shoulders visible, eye-level camera at a comfortable conversational distance.")


def loras_estilo(p):
    """As LoRAs [nome, forca] de todas as tomadas: as escolhidas e, com a pele natural, antes delas as da receita (a da receita vale
    sobre a mesma escolhida a mao)."""
    escolhidas = [list(x) for x in p.get("loras") or []]
    if not p.get("pele"):
        return escolhidas
    da_pele = {n for n, _ in PELE_LORAS}
    return [list(x) for x in PELE_LORAS] + [x for x in escolhidas if x[0] not in da_pele]


def modelo_turbo(nome):
    """O modelo escolhido (tomada 1 ou seguintes) ja traz a aceleracao embutida (o nome diz turbo)."""
    return bool(nome) and "turbo" in Path(nome).name.lower()


# Duracoes de uma tomada do H3, em segundos. O modelo aceita de 4 a 15 s por geracao (quadros na grade 17k+5, a 24 por
# segundo; ver total_quadros), e 3 s tambem roda. Uma tomada longa com a fala inteira evita os defeitos das emendas: a frase
# repetida no comeco da tomada seguinte, falas sobrepostas e a voz mudando de uma tomada para outra.
# Medido em 11/11/2026 na 3080, num take unico de 10 s (243 quadros): a 0,4746 MP (544x928) 714 s, ~73 s por passo, pico de
# 10.024 MiB; a 0,8 MP (672x1216) 1.180 s, ~134 s por passo, pico de 9.713 MiB; nenhum caiu. 10 s a 1 MP (768x1376) DERRUBOU a
# placa (pico de 9.949 MiB): a 1 MP, no maximo 5 s (3 e 4,25 s a 1 MP passaram em 11/11, com um ref2va da comunidade e LoRA, de 305 a 979 s).
# 6, 7 e 8 s ficam entre os pontos medidos (5 e 10 s).
DURACOES = (3, 3.5, 4.25, 5, 6, 7, 8, 10)
# Duracao maxima por resolucao: (ate quantos MP, ate quantos segundos), da menor para a maior. 1 MP subiu de 5 para 6 s em 20/11/2026, a pedido
# do usuario: tomadas de 124 e 141 quadros (5 e 6 s) a 1 MP passaram tres vezes sem queda com a placa limitada a 80% (256 W) no MSI
# Afterburner, todas com o ref2va da pele natural; o fl2va da tomada 1 padrao ainda nao rodou 6 s a 1 MP
# 1,1 e 1,2 MP entraram em 20/11/2026, a pedido do usuario, ainda em teste: o limite mantem a carga da placa perto da de 6 s a 1 MP
# (141 quadros a 1 MP ~ 124 quadros a 1,1 MP ~ 107 quadros a 1,2 MP em tokens)
# 1,1 MP subiu para 7 s em 20/11, a pedido do usuario: 175 quadros a 1,1 MP pesam o mesmo que os 158 a 1,2 MP que rodaram bem (83 s por passo)
# 21/11/2026 (medir_tempos.py, placa sem limite de 80%): o que conta e a carga, quadros x MP. Ate ~150 cabe na placa; acima disso o
# ComfyUI passa parte para a RAM (memoria compartilhada) e cada passo fica mais lento, sem cair. 1 MP 10 s (243) passou em 18 min,
# 1,2 MP 7 s (210) em 12 min e 1,2 MP 10 s (292) em 24 min, mas 1,1 MP 10 s (267) passou dos 30 min de espera. Limite: carga ate ~245
DURACAO_MAX_POR_MP = ((1.0, 10), (1.2, 8))
# As tomadas 2 em diante usam o fluxo da continuacao, que recebe mais 2 s (CONTEXTO) do fim da anterior e gera tudo junto:
# uma tomada seguinte de 10 s seriam 12 s de video na placa, o que ninguem mediu. Por isso as longas so valem na tomada 1.
DURACAO_MAX_SEGUINTES = 5


def duracao_maxima(megapixels, primeira=True):
    """Quantos segundos uma tomada do H3 pode ter nesta resolucao (a tomada 1 pode ser longa; as seguintes, ate 5 s)."""
    limite = next((s for mp, s in DURACAO_MAX_POR_MP if float(megapixels) <= mp + 1e-9), min(s for _, s in DURACAO_MAX_POR_MP))
    return limite if primeira else min(limite, DURACAO_MAX_SEGUINTES)


def duracoes_permitidas(megapixels, primeira=True):
    return [d for d in DURACOES if d <= duracao_maxima(megapixels, primeira)]
CAMERAS = {"parada": "The camera stays still, locked off at the same distance.",
           "aproximar": "The camera slowly pushes in toward the character.",
           "afastar": "The camera slowly pulls back from the character.",
           "acompanhar": "The camera follows the character smoothly, tracking alongside it as it moves, so the background keeps sliding past and new parts of the place come into view.",
           # Selfie na mao, do teste UGC de 20/11/2026 (aprovado pelo usuario): o celular na mao esticada, nunca parado
           "selfie": "Handheld selfie: the character holds the phone in an outstretched hand, the arm visible at the edge of the frame; the frame sways gently with the arm and shakes a little all the time, never static."}
# Usados quando o campo fica vazio. A voz era "playful, natural cartoon voice" (feita para um mascote de desenho); para uma foto qualquer
# soava errada, entao o padrao virou uma voz natural (analise de UX de 13/11/2026). Quem quiser outra, escreve no campo
QUEM_PADRAO, VOZ_PADRAO = "the main character", "natural, friendly voice"
GANHO_MIN, GANHO_MAX = 0.6, 2.0


def total_quadros(segundos):
    """O modelo so aceita 17k+5 quadros: 3 s = 73, 3,5 s = 90, 4,25 s = 107, 5 s = 124, 6 s = 141, 7 s = 175, 8 s = 192, 10 s = 243."""
    return round(segundos * FPS / 17) * 17 + 5


def quadros_novos(segundos, primeira):
    return total_quadros(segundos) - (0 if primeira else SOBREPOSICAO)


def tamanho(proporcao, megapixels):
    """A mesma conta do no ResolutionSelector, usado nas tomadas seguintes."""
    m = re.match(r"(\d+):(\d+)", proporcao)
    w, h = int(m.group(1)), int(m.group(2))
    escala = math.sqrt(megapixels * 1024 * 1024 / (w * h))
    return round(w * escala / 32) * 32, round(h * escala / 32) * 32


# Idioma da fala. Com so "[Portuguese]" o H3 trocou o "p" de "roupa" por "b"; com a etiqueta brasileira e o sotaque na voz, o
# mesmo take (mesma semente) saiu com "roupa" e um "p" limpo (teste ap7_idioma, 11/11/2026, a pedido do usuario)
IDIOMA = "[Brazilian Portuguese]"
SOTAQUE = "with a natural Brazilian Portuguese accent"


def com_sotaque(voz):
    """A descricao da voz com o sotaque brasileiro no fim, se quem escreveu ainda nao citou o Brasil."""
    return voz if "brazil" in voz.lower() else f"{voz}, {SOTAQUE}"


def limpar(texto):
    """Os sinais < e > marcam referencias e falas no prompt, entao nao podem vir de quem escreve."""
    return " ".join(re.sub(r"[<>]", "", str(texto or "")).split())


def frase(texto):
    texto = limpar(texto)
    if not texto:
        return ""
    return texto[0].upper() + texto[1:] + ("" if texto[-1] in ".!?" else ".")


def _partes(t):
    return " ".join(x for x in (CAMERAS[t["camera"]], "The character looks straight at the camera." if t["olhar"] else "", frase(t["acao"])) if x)


def _som(t):
    return frase(t["som"]) or "The room is quiet."


def prompt_primeira(p, t):
    quem = limpar(p["quem"]) or QUEM_PADRAO
    voz = com_sotaque(limpar(p["voz"]) or VOZ_PADRAO)
    fala = f" The {voz} (S1) says: <d>{IDIOMA} {limpar(t['fala'])}</d>" if limpar(t["fala"]) else ""
    return (f"For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.\n\n"
            f"integrated_multimodal_description: [Shot 1] {quem[0].upper() + quem[1:]} shown in <Picture 1> keeps its appearance{'' if t['camera'] == 'acompanhar' else ', and the place stays the same'}. {_partes(t)}{fala}\n\n"
            f"overall_soundscape: {_som(t)}\n\n"
            f"non_diegetic_music: N/A")


def prompt_texto(p, t):
    """Tomada 1 sem imagem: a cena inteira sai do texto, no formato do fluxo oficial de texto para video do H3."""
    quem = limpar(p["quem"])
    voz = com_sotaque(limpar(p["voz"]) or VOZ_PADRAO)
    personagem = f" The main character is {quem}." if quem and quem != QUEM_PADRAO else ""
    fala = f" The {voz} (S1) says: <d>{IDIOMA} {limpar(t['fala'])}</d>" if limpar(t["fala"]) else ""
    return (f"integrated_multimodal_description: [Shot 1] {frase(p.get('cena'))}{personagem} {_partes(t)}{fala}\n\n"
            f"overall_soundscape: {_som(t)}\n\n"
            f"non_diegetic_music: N/A")


# Como abre a descricao de toda tomada seguinte: continuando o que ja acontecia, e so depois a camera e a acao novas. Vem das regras
# do guia Motion Context (19/11/2026): texto que descreve um comeco diferente dos quadros herdados vira salto na emenda, e a
# palavra "cut" nao pode aparecer nem negada
ABERTURA_CONTINUACAO = "The video opens already in progress, continuing the previous moment: at the start the character keeps the pose, the motion and the pace it already has, under the same light."


def prompt_continuacao(p, t, com_voz):
    quem = limpar(p["quem"]) or QUEM_PADRAO
    voz = com_sotaque(limpar(p["voz"]) or VOZ_PADRAO)
    fala = ""
    if limpar(t["fala"]):
        como = "Speaking in the exact same voice as <Audio 1>, with the same pitch and energy, the character" if com_voz else f"Speaking with a {voz}, the character"
        fala = f" {como} (S1) says: <d>{IDIOMA} {limpar(t['fala'])}</d>"
    camera = "Locked-off camera, same distance." if t["camera"] == "parada" else CAMERAS[t["camera"]]
    # Com a camera acompanhando, pedir o mesmo lugar e os mesmos objetos seguraria o cenario parado
    cenario = "" if t["camera"] == "acompanhar" else " Keep the same place, objects and lighting."
    extras = len(p.get("referencias") or [])
    if extras:
        vistas = ", ".join(f"<Picture {i}>" for i in range(1, extras + 1))
        sujeito = f"<Subject 1> is {quem}, shown from different angles in {vistas}. The plain background of those pictures is not part of the scene."
        reter = "Keep <Subject 1>'s body shape, proportions, details and materials identical to the references from every angle."
    else:
        sujeito = f"<Subject 1> is {quem} in <Picture 1>."
        reter = "Keep <Subject 1>'s appearance identical to the reference."
    # Pele natural: a linha de retencao e o paragrafo de pele da receita, depois da abertura em andamento
    pele_reter, pele_texto = (f"\n{PELE_RETER}", f" {PELE_LUZ} {PELE_TEXTO}") if p.get("pele") else ("", "")
    return (f"subject_definitions:\n{sujeito} The place, the lighting and where the character is at the start of this shot are the ones in <Picture {max(extras, 1) + 1}>.\n\n"
            f"summary:\nA single continuous shot from beginning to end. {frase(t['acao']) or 'The character speaks to the camera.'}\n\n"
            f"retention_analysis:\n[reference generation] {reter}{cenario} {camera} Keep the character in frame.{pele_reter}\n\n"
            f"detailed_description:\n{ABERTURA_CONTINUACAO}{pele_texto} {_partes(t)}{fala}\n\n"
            f"overall_soundscape:\n{_som(t)}\n\n"
            f"non_diegetic_music:\nN/A")


def com_gatilho(p, prompt):
    """A palavra-chave fixa das LoRAs de estilo escolhidas (loras.com_gatilho, ex. r34l1sm da Realism People) no começo do prompt."""
    return loras.com_gatilho(loras_estilo(p), prompt)


def grafo_primeira(p, t, foto, prefixo, semente):
    largura, altura = tamanho(p["proporcao"], p["megapixels"])
    g = {
        "1": {"class_type": "LoadImage", "inputs": {"image": foto}},
        "2": {"class_type": "ImageScale", "inputs": {"image": ["1", 0], "upscale_method": "lanczos", "width": largura, "height": altura, "crop": "center"}},
        "10": {"class_type": "UNETLoader", "inputs": {"unet_name": "minimax_h3_fl2va_pruned_int8_convrot.safetensors", "weight_dtype": "default"}},
        "11": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["10", 0], "lora_name": "minimax_h3_fl2v_turbo_8step_v1.0_768p_comfyui_bf16.safetensors", "strength_model": 1.0}},
        "14": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors", "type": "minimax", "device": "default"}},
        "15": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_video_vae_int8_convrot.safetensors"}},
        "16": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_audio_vae_fp32.safetensors"}},
        "20": {"class_type": "MiniMaxH3ImageToVideo", "inputs": {"clip": ["14", 0], "vae": ["15", 0], "prompt": com_gatilho(p, prompt_primeira(p, t)), "width": largura, "height": altura, "length": total_quadros(t["duracao"]), "first_frame": ["2", 0]}},
        "21": {"class_type": "KSampler", "inputs": {"model": ["11", 0], "seed": semente, "steps": PASSOS_PRIMEIRA, "cfg": 1.0, "sampler_name": "res_multistep", "scheduler": "simple", "positive": ["20", 0], "negative": ["20", 0], "latent_image": ["20", 1], "denoise": 1.0}},
        "22": {"class_type": "LTXVSeparateAVLatent", "inputs": {"av_latent": ["21", 0]}},
        "23": {"class_type": "VAEDecode", "inputs": {"samples": ["22", 0], "vae": ["15", 0]}},
        "24": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["22", 1], "vae": ["16", 0]}},
        "25": {"class_type": "CreateVideo", "inputs": {"images": ["23", 0], "audio": ["24", 0], "fps": FPS}},
        "26": {"class_type": "SaveVideo", "inputs": {"video": ["25", 0], "filename_prefix": prefixo, "format": "auto", "codec": "auto"}},
    }
    if not foto:
        # Texto para video: o mesmo no sem first_frame (fluxo oficial video_minimax_h3_t2v; 240 s em 3 s a 928x512, testado em 10/11/2026)
        del g["1"], g["2"], g["20"]["inputs"]["first_frame"]
        g["20"]["inputs"]["prompt"] = com_gatilho(p, prompt_texto(p, t))
    # Outro modelo na tomada 1 (um H3 ref2va da comunidade): o autor diz que fl2va e ref2va sao em parte intercambiaveis. Testado em 09/11/2026 com o
    # ref2va Turbo no mesmo no: parte da imagem e fala como o oficial, 220 s contra 243 s. O Turbo ja vem acelerado: sem a LoRA, euler/simple
    modelo = ["11", 0]
    if p.get("primeira"):
        g["10"]["inputs"]["unet_name"] = p["primeira"]
        # Um ref2va sem aceleracao embutida leva a LoRA turbo da mesma familia (Singularity, teste de 20/11/2026)
        g["11"]["inputs"]["lora_name"] = TURBO_REF2V
        if modelo_turbo(p["primeira"]):
            del g["11"]
            modelo = ["10", 0]
            g["21"]["inputs"].update(steps=PASSOS_TURBO, sampler_name=SAMPLER_TURBO, scheduler=AGENDADOR_TURBO)
    # LoRAs de estilo depois da de aceleracao
    for i, (nome, forca) in enumerate(p.get("loras") or []):
        g[f"3{i}"] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": modelo, "lora_name": nome, "strength_model": forca}}
        modelo = [f"3{i}", 0]
    # A mesma atencao da troca e da continuacao (a INT8 do comfy kitchen), no fim da cadeia do modelo. Medido em 19/11/2026 (texto para
    # video, 5 s a 928x544, mesma semente, uma rodada de cada): 25,1 s por passo, contra 29,6 s sem no de atencao e 26,8 s com o
    # SageAttention; VRAM e potencia iguais. A mesma semente passa a dar outro video. Sem o backend, o no usa a atencao do PyTorch
    g["12"] = {"class_type": "ModelAttentionBackend", "inputs": {"model": modelo, "attention": "comfy kitchen attention"}}
    g["21"]["inputs"]["model"] = ["12", 0]
    return g


def formato(proporcao):
    """"9:16 (Portrait Widescreen)" -> "vertical 9:16"; "16:9 (Widescreen)" -> "widescreen 16:9"; "1:1 (Square)" -> "square 1:1"."""
    w, h = (int(x) for x in re.match(r"(\d+):(\d+)", proporcao).groups())
    return f"{'vertical' if h > w else 'widescreen' if w > h else 'square'} {w}:{h}"


def prompt_pele(p, t):
    """Tomada 1 com a pele natural: a foto entra como referencia, nas secoes do modo referencia, com a luz e o paragrafo de pele da receita."""
    quem = limpar(p["quem"]) or QUEM_PADRAO
    voz = com_sotaque(limpar(p["voz"]) or VOZ_PADRAO)
    fala = f" The {voz} (S1) says: <d>{IDIOMA} {limpar(t['fala'])}</d>" if limpar(t["fala"]) else ""
    # Nada que prenda o quadro a foto: com "o lugar fica o de <Picture 1>" e a camera "a mesma distancia", quatro sementes sairam em close
    # fechado (a foto era um recorte de busto), enquanto o prompt do teste, que descrevia o fundo a parte, saiu do peito para cima (20/11/2026)
    cenario = "" if t["camera"] == "acompanhar" else " The background stays softly blurred and exactly the same for the whole video."
    # O lugar atras da pessoa: foi o que abriu o quadro (teste_pele_lugar1, 21/11/2026, do peito para cima como no teste aprovado). Vem do
    # campo "Onde acontece" (chave cena); vazio, uma frase generica que pede o comodo visivel
    lugar = f"Setting: {frase(p.get('cena')) or PELE_LUGAR_PADRAO}"
    camera = "The camera stays completely steady." if t["camera"] == "parada" else CAMERAS[t["camera"]]
    partes = " ".join(x for x in (camera, "The character looks straight at the camera." if t["olhar"] else "", frase(t["acao"])) if x)
    return (f"subject_definitions:\n<Subject 1> is {quem} from <Picture 1>. <Subject 1>'s face, hair, makeup and outfit must match <Picture 1> exactly.\n\n"
            f"summary:\n[reference generation] The target video is a {t['duracao']:g}-second {formato(p['proporcao'])} medium close-up of <Subject 1>, "
            f"one continuous shot made to showcase real skin texture. {lugar} {frase(t['acao']) or 'The character speaks to the camera.'}\n\n"
            f"retention_analysis:\n<Subject 1>: fully_preserved - same face, hair, makeup and outfit throughout.\n{PELE_RETER}\n\n"
            f"detailed_description:\n{PELE_ENQUADRAR} {lugar} {PELE_LUZ}{cenario}\n\n{PELE_TEXTO}\n\n{partes}{fala}\n\n"
            f"overall_soundscape:\n{_som(t)}\n\n"
            f"non_diegetic_music:\nN/A")


def grafo_referencia(p, duracao, prompt, prefixo, semente, modelo, loras_modelo, tamanho_ref):
    """Base ref2va. Os nós 20, 21 e 26 mantêm os números usados pelo acompanhamento."""
    largura, altura = tamanho(p["proporcao"], p["megapixels"])
    g = {
        "10": {"class_type": "UNETLoader", "inputs": {"unet_name": modelo, "weight_dtype": "default"}},
        "11": {"class_type": "MiniMaxH3SigmaShift", "inputs": {"model": ["10", 0], "shift_video": PELE_DESVIO[0], "shift_audio": PELE_DESVIO[1]}},
        "14": {"class_type": "CLIPLoader", "inputs": {"clip_name": video_avancado.CLIP, "type": "minimax", "device": "default"}},
        "15": {"class_type": "VAELoader", "inputs": {"vae_name": video_avancado.VAE}},
        "16": {"class_type": "VAELoader", "inputs": {"vae_name": video_avancado.AUDIO_VAE}},
        "20": {"class_type": "MiniMaxH3ReferenceToVideo", "inputs": {"clip": ["14", 0], "vae": ["15", 0], "audio_vae": ["16", 0], "width": largura, "height": altura,
                                                                   "prompt": prompt, "length": total_quadros(duracao), "ref_image_size": tamanho_ref}},
        "21": {"class_type": "KSampler", "inputs": {"seed": semente, "steps": PELE_PASSOS, "cfg": 1.0, "sampler_name": PELE_SAMPLER, "scheduler": PELE_AGENDADOR,
                                                    "positive": ["20", 0], "negative": ["20", 0], "latent_image": ["20", 1], "denoise": 1.0}},
        "22": {"class_type": "LTXVSeparateAVLatent", "inputs": {"av_latent": ["21", 0]}},
        "23": {"class_type": "VAEDecode", "inputs": {"samples": ["22", 0], "vae": ["15", 0]}},
        "24": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["22", 1], "vae": ["16", 0]}},
        "25": {"class_type": "CreateVideo", "inputs": {"images": ["23", 0], "audio": ["24", 0], "fps": FPS}},
        "26": {"class_type": "SaveVideo", "inputs": {"video": ["25", 0], "filename_prefix": prefixo, "format": "auto", "codec": "auto"}},
    }
    modelo = ["11", 0]
    for i, (nome, forca) in enumerate(loras_modelo):
        g[f"3{i}"] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": modelo, "lora_name": nome, "strength_model": forca}}
        modelo = [f"3{i}", 0]
    g["12"] = {"class_type": "ModelAttentionBackend", "inputs": {"model": modelo, "attention": "comfy kitchen attention"}}
    g["21"]["inputs"]["model"] = ["12", 0]
    return g


def grafo_pele(p, t, foto, prefixo, semente):
    estilo = loras_estilo(p)
    prompt = loras.com_gatilho(estilo, prompt_pele(p, t), "\n\n")
    g = grafo_referencia(p, t["duracao"], prompt, prefixo, semente, PELE_MODELO, estilo, "max")
    g["1"] = {"class_type": "LoadImage", "inputs": {"image": foto}}
    g["20"]["inputs"]["ref_images.ref_image_0"] = ["1", 0]
    return g


def grafo_avancado(p, refs, prefixo, semente):
    prompt = video_avancado.resolver_prompt(p["avancado"]["prompt"], refs)
    g = grafo_referencia(p, p["tomadas"][0]["duracao"], prompt, prefixo, semente,
                         video_avancado.MODELO, [(video_avancado.TURBO, 1.0)], "match")
    entradas = g["20"]["inputs"]
    for ref, numero in video_avancado.numerar(refs):
        i = numero - 1
        arquivo = ref["arquivo"]
        if ref["tipo"] == "foto":
            no = str(100 + i)
            g[no] = {"class_type": "LoadImage", "inputs": {"image": arquivo}}
            entradas[f"ref_images.ref_image_{i}"] = [no, 0]
        elif ref["tipo"] == "video":
            carga, no = str(110 + i), str(115 + i)
            g[carga] = {"class_type": "LoadVideo", "inputs": {"file": arquivo}}
            g[no] = {"class_type": "GetVideoComponents", "inputs": {"video": [carga, 0]}}
            entradas[f"ref_videos.ref_video_{i}"] = [no, 0]
        else:
            no = str(120 + i)
            g[no] = {"class_type": "LoadAudio", "inputs": {"audio": arquivo}}
            entradas[f"ref_audios.ref_audio_{i}"] = [no, 0]
    return g


def grafo_continuacao(p, t, video, inicio, referencias, voz, prefixo, semente, n):
    pele = bool(p.get("pele"))
    seguintes = PELE_MODELO if pele else p.get("seguintes")
    turbo = modelo_turbo(seguintes)
    if pele:
        # A receita da pele: a EMA-600 e a aceleracao, entao a LoRA de aceleracao do fluxo sai (nunca duas juntas)
        sampler, agendador, passos = PELE_SAMPLER, PELE_AGENDADOR, PELE_PASSOS
    elif turbo:
        sampler, agendador, passos = SAMPLER_TURBO, AGENDADOR_TURBO, PASSOS_TURBO
    else:
        sampler, agendador, passos = None, None, PASSOS_CONTINUACAO
    a = types.SimpleNamespace(modelo=seguintes, sampler=sampler, agendador=agendador, lora=None, sem_lora=turbo or pele,
                              trecho=total_quadros(t["duracao"]) / FPS, passos=passos, proporcao=p["proporcao"], megapixels=p["megapixels"], sobreposicao=SOBREPOSICAO, semente=semente)
    tem_voz = bool(voz and limpar(t["fala"]))
    g = grafo_geracao(a, video, inicio, com_gatilho(p, prompt_continuacao(p, t, tem_voz)), prefixo, referencias, n * 100)
    estilo = loras_estilo(p)
    if estilo:
        # LoRAs de estilo: somam-se a aceleracao do fluxo (num modelo Turbo, que vem sem ela, ficam sozinhas)
        estado = json.loads(g["554"]["inputs"]["LoraLoaderState"])
        estado["loras"] += [{"name": n, "on": True, "sm": float(f), "sc": float(f), "triggers": []} for n, f in estilo]
        g["554"]["inputs"]["LoraLoaderState"] = json.dumps(estado)
    if pele:
        # O mesmo desvio de sigma da tomada 1, logo depois do modelo
        g["560"] = {"class_type": "MiniMaxH3SigmaShift", "inputs": {"model": g["196"]["inputs"]["model"], "shift_video": PELE_DESVIO[0], "shift_audio": PELE_DESVIO[1]}}
        g["196"]["inputs"]["model"] = ["560", 0]
    if p.get("referencias"):
        # As referencias passam por todos os passos: varias em tamanho maximo pesariam demais em 10 GB
        g["5"]["inputs"]["ref_image_size"] = "match"
    if tem_voz:
        # O <Video 1> do fluxo nao chega ao modelo: sem isto, cada tomada inventa uma voz
        midia = json.loads(g["416"]["inputs"]["media_state"])
        midia.append({"kind": "audio", "name": voz, "file": voz, "has_audio": True, "enabled": True})
        g["416"]["inputs"]["media_state"] = json.dumps(midia)
    return g


# Modo audio ("Audio da fala"): o video segue um audio enviado, testado em 20/11/2026 (testes_troca/audio_2026-11-20 e
# ugc_2026-11-20). Cada tomada sai do zero a partir da imagem, com o trecho do audio preso no latente pelo no
# PixaromaH3AudioSync (o "Soundtrack Kept" do WanGP; o AddGuide e o <Audio 1> refaziam a fala). A pele natural vale sempre.
# A fala nao vai escrita: o audio ja e a fala. A boca: sem sorriso durante a fala e labios fechando nos p, b e m, a forma
# que corrigiu o "paga" (sem ela, saia "taga" na leitura labial). As tomadas sao cortes e saem emendadas a seco.
BOCA_AUDIO = ("While the character speaks, the mouth only forms the words, lips relaxed: the lips press fully together on every p, b and m "
              "sound and open for the vowels.")
# Enquadramento preso ao da imagem (20/11/2026): sem isto, a tomada 2 do vídeo completo e as de 1,1 e 1,2 MP chegaram perto do rosto,
# sem o braço da selfie e sem o lugar atrás. O prompt do teste aprovado dizia a distância ("do peito para cima, com o braço esticado")
ENQUADRAR_AUDIO = ("Framing for the whole shot: exactly the framing of <Picture 1>, the same camera distance, height and angle, <Subject 1> shown down to the "
                   "same part of the body as in <Picture 1>, with the same amount of the place visible around and above. The camera never moves "
                   "closer to the face and never turns into a close-up.")
OLHAR_AUDIO = {"selfie": "Ordinary mid-range phone footage from the front camera, soft even light on the face, natural exposure and colors, mild sensor noise, no extra sharpness.",
               "parada": "A phone on a tripod: realistic social media footage, natural colors, sharp focus on the character."}


def tempo(s):
    return f"00:{max(0.0, s):06.3f}"


def quadros_para(segundos):
    """O menor tamanho do H3 (17k+5 quadros) que cobre o trecho do audio."""
    k = max(0, math.ceil((math.ceil(segundos * FPS - 1e-6) - 5) / 17))
    return 17 * k + 5


# Idioma do modo audio. Na selfie, o jeito de falar de influenciadora (sugestao do usuario no teste de 21/11, junto com a fala escrita)
IDIOMA_AUDIO = {"selfie": "Brazilian Portuguese, like a real Brazilian influencer talking to her followers"}


def prompt_audio(p, t, fala, n_refs, cenario):
    """Prompt de uma tomada do modo audio. fala = (primeira voz, ultima voz, [pausas]) dentro da tomada, ou None. t["fala"], se houver,
    e o texto do que se diz, escrito como se fala; entra no prompt so para guiar a boca."""
    idioma = IDIOMA_AUDIO.get(t["camera"], "Brazilian Portuguese")
    quem = limpar(p["quem"])
    quem = "" if not quem or quem == QUEM_PADRAO else f" ({quem})"
    extras = range(3 if cenario else 2, n_refs + 1)
    sujeito = (f"<Subject 1> is the person from <Picture 1>{quem}. <Subject 1>'s face, hair, skin tone, makeup and outfit must match <Picture 1> exactly. "
               "<Subject 1> is the only person in the video.")
    if extras:
        sujeito += f" {', '.join(f'<Picture {i}>' for i in extras)} show <Subject 1> from other angles; their plain background is not part of the scene."
    lugar = (f"\n<Subject 2> is the place from <Picture 2>, the same place seen behind <Subject 1> in <Picture 1>. It is where the whole video happens."
             if cenario else "")
    reter_lugar = (f"\n<Subject 2>: fully_preserved - the place of <Picture 2> stays behind <Subject 1> for the whole video, seen from the same direction as in <Picture 1>."
                   if cenario else "")
    if fala:
        a, b, pausas = fala
        pausa = f", with short pauses around {', '.join(tempo(x) for x in pausas)}" if pausas else ""
        voz = (f"<Subject 1> is visibly speaking {idioma} to the camera with natural lip movements synchronized to the voice, from {tempo(a)} "
               f"to {tempo(b)}{pausa}. {BOCA_AUDIO} After {tempo(b)} the mouth closes and stays relaxed until the last frame.")
        if limpar(t.get("fala")):
            # Fala escrita (21/11/2026): com as palavras, escritas como se fala ("uatizápi"), o "p" do WhatsApp fechou na hora certa,
            # onde antes a boca travava num sorriso. O som continua sendo o audio preso; o texto so diz ao modelo que boca desenhar
            voz += f" In the voice and with the timing of the soundtrack, <Subject 1> (S1) says: <d>[{idioma}] {limpar(t['fala'])}</d>"
    else:
        voz = "<Subject 1> does not speak in this shot: the mouth stays closed and relaxed."
    olhar = OLHAR_AUDIO.get(t["camera"], OLHAR_AUDIO["parada"])
    return (f"subject_definitions:\n{sujeito}{lugar}\n\n"
            f"summary:\n[reference generation] A vertical social media video of <Subject 1> talking to the camera, like a real UGC ad. "
            f"The shot starts with the framing, light and background of <Picture 1>.\n\n"
            f"retention_analysis:\n<Picture 1>: fully_preserved - <Subject 1>'s face, hair, skin, outfit, the framing, the camera distance and the place behind are the ones in <Picture 1> for the whole video.\n"
            # A pele segue a imagem, como no teste UGC aprovado (sem o paragrafo de poros da pele natural: os modelos sao os da receita)
            f"<Subject 1>: fully_preserved - same face, hair, makeup and outfit for the whole video, with the natural skin tone and natural skin of <Picture 1>.{reter_lugar}\n\n"
            f"detailed_description:\nLook: {olhar} The same brightness and colors as <Picture 1>.\n\n[Shot 1] One continuous take. {ENQUADRAR_AUDIO} {_partes(t)}\n\n{voz}\n\n"
            f"overall_soundscape:\n<Subject 1>'s voice, clear and close, speaking {idioma}. {_som(t)}\n\n"
            f"non_diegetic_music:\nN/A")


def grafo_audio(p, t, referencias, cenario, audio, quadros, fala, prefixo, semente):
    """Uma tomada do modo audio: o ref2va da pele natural com a imagem (e o cenario) como referencia e o trecho do audio
    preso no latente. Os nos 20 (prompt), 21 (amostrador) e 26 (video) tem os numeros do grafo_primeira."""
    largura, altura = tamanho(p["proporcao"], p["megapixels"])
    refs = [referencias[0]] + ([cenario] if cenario else []) + list(referencias[1:])
    g = {
        "3": {"class_type": "LoadAudio", "inputs": {"audio": audio}},
        "10": {"class_type": "UNETLoader", "inputs": {"unet_name": PELE_MODELO, "weight_dtype": "default"}},
        "11": {"class_type": "MiniMaxH3SigmaShift", "inputs": {"model": ["10", 0], "shift_video": PELE_DESVIO[0], "shift_audio": PELE_DESVIO[1]}},
        "14": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors", "type": "minimax", "device": "default"}},
        "15": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_video_vae_int8_convrot.safetensors"}},
        "16": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_audio_vae_fp32.safetensors"}},
        "20": {"class_type": "MiniMaxH3ReferenceToVideo", "inputs": {"clip": ["14", 0], "vae": ["15", 0], "audio_vae": ["16", 0], "width": largura, "height": altura,
                                                                   "prompt": loras.com_gatilho(loras_estilo(p), prompt_audio(p, t, fala, len(refs), bool(cenario)), "\n\n"),
                                                                   # Com mais de uma referencia, "match": todas passam por todos os passos (como na continuacao)
                                                                   "length": quadros, "ref_image_size": "max" if len(refs) == 1 else "match"}},
        "28": {"class_type": "PixaromaH3AudioSync", "inputs": {"model": ["11", 0], "latent": ["20", 1], "audio_vae": ["16", 0], "track": ["3", 0], "H3SyncState": "{}"}},
        "21": {"class_type": "KSampler", "inputs": {"seed": semente, "steps": PELE_PASSOS, "cfg": 1.0, "sampler_name": PELE_SAMPLER, "scheduler": PELE_AGENDADOR,
                                                    "positive": ["20", 0], "negative": ["20", 0], "latent_image": ["28", 1], "denoise": 1.0}},
        "22": {"class_type": "LTXVSeparateAVLatent", "inputs": {"av_latent": ["21", 0]}},
        "23": {"class_type": "VAEDecode", "inputs": {"samples": ["22", 0], "vae": ["15", 0]}},
        "24": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["22", 1], "vae": ["16", 0]}},
        "25": {"class_type": "CreateVideo", "inputs": {"images": ["23", 0], "audio": ["24", 0], "fps": FPS}},
        "26": {"class_type": "SaveVideo", "inputs": {"video": ["25", 0], "filename_prefix": prefixo, "format": "auto", "codec": "auto"}},
    }
    for i, nome in enumerate(refs):
        g[f"4{i}"] = {"class_type": "LoadImage", "inputs": {"image": nome}}
        g["20"]["inputs"][f"ref_images.ref_image_{i}"] = [f"4{i}", 0]
    modelo = ["11", 0]
    for i, (nome, forca) in enumerate(loras_estilo(p)):
        g[f"3{i + 1}"] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": modelo, "lora_name": nome, "strength_model": forca}}
        modelo = [f"3{i + 1}", 0]
    g["12"] = {"class_type": "ModelAttentionBackend", "inputs": {"model": modelo, "attention": "comfy kitchen attention"}}
    g["21"]["inputs"]["model"] = ["12", 0]
    return g


def juntar_audio(pasta, feitas, audio):
    """Modo audio: cada tomada aparada no tamanho do seu trecho, emendadas a seco, e o audio original por cima (o H3 devolve o
    som recodificado a 32 kHz). Todas as tomadas tem o mesmo tamanho de imagem."""
    ent, filtros = [], []
    for k, r in enumerate(feitas):
        ent += ["-i", str(caminhos.abrir(pasta, r["arquivo"]))]
        filtros.append(f"[{k}:v]trim=end_frame={r['usar']},setpts=PTS-STARTPTS,format=yuv420p[v{k}]")
    filtro = ";".join(filtros) + ";" + "".join(f"[v{k}]" for k in range(len(feitas))) + f"concat=n={len(feitas)}:v=1:a=0[v]"
    soma = sum(r["usar"] for r in feitas)
    destino = pasta / "final.mp4"
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error", *ent, "-t", f"{soma / FPS:.4f}", "-i", str(audio),
                    "-filter_complex", filtro, "-map", "[v]", "-map", f"{len(feitas)}:a:0", "-c:v", "libx264", "-crf", "17", "-preset", "medium", "-r", str(FPS),
                    "-c:a", "aac", "-b:a", "192k", "-shortest", str(destino)], check=True)
    print(f"final: {destino} | {soma} quadros | {soma / FPS:.2f} s", flush=True)


def ler_audio(arq):
    c = av.open(str(arq))
    try:
        if not c.streams.audio:
            return np.zeros(0, dtype=np.float32)
        conv = av.AudioResampler(format="s16", layout="mono", rate=16000)
        partes = [g.to_ndarray().ravel() for f in c.decode(audio=0) for g in conv.resample(f)]
    finally:
        c.close()
    return (np.concatenate(partes).astype(np.float32) / 32768.0) if partes else np.zeros(0, dtype=np.float32)


def trecho_de_fala(pcm, inicio=0.0, limiar=0.03, minimo=2.0):
    """Do primeiro ao ultimo decimo de segundo com som, a partir de inicio. None se nao houver fala."""
    bloco = 1600
    blocos = [i for i in range(int(inicio * 16000), len(pcm), bloco) if np.sqrt(np.mean(pcm[i:i + bloco] ** 2)) >= limiar]
    if not blocos:
        return None
    a, b = max(blocos[0] / 16000 - 0.05, inicio), min((blocos[-1] + bloco) / 16000 + 0.05, len(pcm) / 16000)
    return (a, max(b, min(a + minimo, len(pcm) / 16000)))


def extrair_voz(arq, destino, inicio=0.0):
    pcm = ler_audio(arq)
    t = trecho_de_fala(pcm, inicio)
    if t is None:
        return False
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{t[0]:.3f}", "-to", f"{t[1]:.3f}", "-i", str(arq), "-vn", "-ac", "2", "-ar", "44100", str(destino)], check=True)
    return True


def nivel(trecho):
    v = trecho[np.abs(trecho) > 0.005]
    return float(np.sqrt(np.mean(v ** 2))) if len(v) else 0.0


def ganhos_volume(niveis):
    """Leva cada fala ao nivel mediano, sem exagerar. O limitador segura os picos depois."""
    validos = [x for x in niveis if x > 0]
    if len(validos) < 2:
        return [1.0] * len(niveis)
    alvo = float(np.median(validos))
    return [float(np.clip(alvo / x, GANHO_MIN, GANHO_MAX)) if x > 0 else 1.0 for x in niveis]


def intervalos(rodadas):
    """Inicio e fim de cada tomada no video final, em segundos: a mesma conta do juntar()."""
    saida, soma = [], 0
    for i, r in enumerate(rodadas):
        a, b = r["pular"], r["total"] - (0 if i == len(rodadas) - 1 else r["sobreposicao"])
        saida.append((soma / FPS, (soma + b - a) / FPS))
        soma += b - a
    return saida


def nivelar(pasta, rodadas, falas):
    """Iguala o volume das falas no final.mp4. A imagem nao e recodificada."""
    final = pasta / "final.mp4"
    pcm = ler_audio(final)
    trechos = intervalos(rodadas)
    niveis = [nivel(pcm[int(a * 16000):int(b * 16000)]) if tem else 0.0 for (a, b), tem in zip(trechos, falas)]
    filtros = [f"volume=enable='between(t,{a:.3f},{b:.3f})':volume={g:.3f}" for (a, b), g in zip(trechos, ganhos_volume(niveis)) if abs(g - 1) >= 0.1]
    if not filtros:
        return
    temporario = pasta / "final_nivelando.mp4"
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(final), "-map", "0:v", "-map", "0:a", "-c:v", "copy", "-af", ",".join(filtros + ["alimiter=limit=0.95:level=disabled"]), "-c:a", "aac", "-b:a", "192k", str(temporario)], check=True)
    os.replace(temporario, final)


class Progresso:
    """Guarda a tomada e o passo atuais em progresso.json, que a pagina le enquanto a geracao roda."""
    AMOSTRADORES = ("21", "125:12")

    def __init__(self, arquivo, total, monitor):
        self.arquivo, self.total, self.monitor = arquivo, total, monitor
        self.inicio = time.time()
        self.n, self.etapa, self.valor, self.maximo, self.em = 0, "preparar", 0, 0, 0
        self.detalhe = Detalhe(monitor, inicio=self.inicio)

    def gravar(self):
        dados = {"tomada": self.n, "total": self.total, "etapa": self.etapa, "valor": self.valor, "maximo": self.maximo, "em": self.em, **self.detalhe.dados()}
        temporario = self.arquivo.with_name(self.arquivo.name + ".tmp")
        try:
            temporario.write_text(json.dumps(dados), encoding="utf-8")
            os.replace(temporario, self.arquivo)
        except OSError:
            # A pagina pode estar lendo o arquivo neste instante; a proxima gravacao resolve
            pass

    def tomada(self, n):
        self.n, self.etapa, self.valor, self.maximo = n, "gerar", 0, 0
        self.em = round(time.time() - self.inicio)
        self.monitor.rotulo = f"tomada {n}"
        self.gravar()

    def grafo(self, g):
        """Cada tomada tem um grafo proprio: o detalhe passa a ler os nos dele."""
        self.detalhe.reiniciar(g)

    def montando(self):
        self.etapa, self.valor, self.maximo = "montar", 0, 0
        self.monitor.rotulo = f"montar {self.n}"
        self.gravar()

    def acabando(self, etapa, valor, maximo):
        """Refino (pedaco valor de maximo) ou ampliacao (quadro valor de maximo), depois das tomadas."""
        if etapa != self.etapa:
            self.em = round(time.time() - self.inicio)
            self.detalhe.reiniciar()
        self.etapa, self.valor, self.maximo = etapa, valor, maximo
        self.monitor.rotulo = etapa
        self.gravar()

    def evento(self, m):
        if m.get("type") != "progress_state":
            return
        nos = (m.get("data") or {}).get("nodes") or {}
        rodando = self.detalhe.evento(nos)
        for no in self.AMOSTRADORES:
            n = nos.get(no)
            if n and n.get("state") == "running" and n.get("max", 0) > 1:
                self.valor, self.maximo = round(n.get("value", 0)), round(n["max"])
        # Wan: 2 passos no modelo High (no 60) e 2 no Low (no 61); a pagina recebe o passo somado, de 0 a 4
        for i, no in enumerate(wan.AMOSTRADORES):
            n = nos.get(no)
            if n and n.get("state") == "running" and n.get("max", 0) > 0 and self.detalhe.tipos.get(no) == "KSamplerAdvanced":
                self.valor, self.maximo = min(4, i * 2 + round(n.get("value", 0))), 4
        if rodando:
            self.gravar()


def cor_do_fundo(q):
    """No video vertical o personagem pode ocupar o terco esquerdo: mede a faixa de cima.
    A mediana ignora o que passa por ali, como um fio ou um objeto pendurado."""
    altura, largura = q[0].shape[:2]
    if altura <= largura:
        return cor_fundo(q)
    return np.median(np.stack([f[:altura // 10] for f in q]).reshape(-1, 3), axis=0)


def corrigir_tomada(bruto, q, pular, quadros_ant, saida):
    """Acerta o brilho de uma tomada seguinte pela anterior e grava em saida; devolve o ganho aplicado.
    Os quadros de sobreposicao (q[pular:pular + SOBREPOSICAO]) sao os mesmos instantes dos ultimos quadros da tomada anterior,
    que a montagem descarta: o ganho que iguala os dois vale para a tomada inteira e tira o degrau da emenda.
    Antes a medida era um canto do quadro no fim da tomada (cor_do_fundo), e uma mudanca de cena virava desvio de cor: em
    19/11/2026 um notebook fechado clareou esse canto e a tomada escureceu 10% ate o fim."""
    ganho = ganho_na_emenda(quadros_ant[-SOBREPOSICAO:], q[pular:pular + SOBREPOSICAO])
    aplicar_ganho(bruto, saida, pular, ganho)
    return round(ganho, 3)


def nome_livre(pasta, n):
    k = 1
    while (pasta / f"tomada{n}_v{k}.mp4").exists():
        k += 1
    return pasta / f"tomada{n}_v{k}.mp4"


def eh_wan(p):
    """Projeto antigo, sem a chave, e do H3."""
    return p.get("modelo", "h3") in wan.MODELOS_WAN


def prompt_wan(t):
    """O Wan nao tem fala nem som: a camera, o olhar e a acao, nas mesmas frases do H3."""
    return _partes(t) or "The character stays in place, breathing naturally."


def grafo_wan(p, t, imagem, prefixo, semente):
    pw = {"prompt": prompt_wan(t), "negativo": p.get("negativo") or "", "modelo": p["modelo"], "duracao": t["duracao"], "proporcao": p["proporcao"], "megapixels": p["megapixels"],
          "loras": [(alta, wan.baixa_de(alta), forca) for alta, forca in p.get("loras") or []]}
    return wan.grafo(pw, imagem, semente, prefixo)


def juntar_sem_audio(pasta, rodadas, fps):
    """Une as tomadas do Wan: cada uma a partir de `pular` (o quadro que repete o fim da anterior), sem som."""
    ent, filtros, rotulos, soma = [], [], [], 0
    for k, r in enumerate(rodadas):
        ent += ["-i", str(caminhos.abrir(pasta, r["arquivo"]))]
        filtros.append(f"[{k}:v]trim=start_frame={r['pular']}:end_frame={r['total']},setpts=PTS-STARTPTS,format=yuv420p[v{k}]")
        rotulos.append(f"[v{k}]")
        soma += r["total"] - r["pular"]
    filtro = ";".join(filtros) + ";" + "".join(rotulos) + f"concat=n={len(rotulos)}:v=1:a=0[v]"
    destino = pasta / "final.mp4"
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error", *ent, "-filter_complex", filtro, "-map", "[v]",
                    "-c:v", "libx264", "-crf", "17", "-preset", "medium", "-r", str(fps), str(destino)], check=True)
    print(f"final: {destino} | {soma} quadros | {soma / fps:.2f} s", flush=True)


# Movimento mais fluido no Wan: o RIFE 4.9 cria um quadro entre cada dois, de 16 para 32 por segundo.
# Testado em 09/11/2026: 6 s de video em 13 s, pico de 2,2 GB, sem fantasma visivel no pulo do gato.
FPS_SUAVE, RIFE = 32, "rife49.pth"


def falta_suavizar(p, estado):
    return eh_wan(p) and p.get("fluidez") is True and not estado.get("suavizado")


def grafo_suave(entrada, prefixo):
    return {
        "1": {"class_type": "LoadVideo", "inputs": {"file": entrada}},
        "2": {"class_type": "GetVideoComponents", "inputs": {"video": ["1", 0]}},
        "3": {"class_type": "RIFE VFI", "inputs": {"ckpt_name": RIFE, "frames": ["2", 0], "clear_cache_after_n_frames": 10, "multiplier": 2, "fast_mode": True,
                                                   "ensemble": True, "scale_factor": 1.0, "dtype": "float32", "torch_compile": False, "batch_size": 1}},
        "4": {"class_type": "CreateVideo", "inputs": {"images": ["3", 0], "fps": FPS_SUAVE}},
        "5": {"class_type": "SaveVideo", "inputs": {"video": ["4", 0], "filename_prefix": prefixo, "format": "auto", "codec": "auto"}},
    }


def suavizar(pasta, projeto, marca, progresso, mon, sair):
    """Passa o final.mp4 do Wan pelo RIFE. O de 16 quadros por segundo fica como final_16qps.mp4."""
    final = pasta / "final.mp4"
    arq_entrada, entrada = entrada_temp.arquivo(projeto, f"imagem_{projeto}_{marca}_suave.mp4")
    shutil.copy2(final, arq_entrada)
    progresso.acabando("suavizar", 0, 0)
    print(f"suavizando: RIFE de {wan.FPS_WAN} para {FPS_SUAVE} quadros por segundo", flush=True)
    r = rodar(grafo_suave(entrada, f"imagem/{projeto}/suave"), 900)
    if mon.quente:
        sair(5, "PARADO por temperatura")
    if r["status"] == "servidor caiu":
        sair(3, f"SERVIDOR CAIU: {r['erro'][:300]}")
    if r["status"] != "success":
        sair(4, f"FALHA ao suavizar o movimento: {r['status']} {r['erro'][:500]}")
    video = arquivo_de_saida(r["saidas"].get("5") or {})
    if video is None or not video.is_file():
        sair(4, f"FALHA ao suavizar o movimento: o ComfyUI nao informou o video. Saidas: {list(r['saidas'])}")
    shutil.copy2(final, pasta / "final_16qps.mp4")
    shutil.copy2(video, final)
    print(f"movimento suavizado: {round(r['segundos'])} s | pico {r['pico_vram']} MiB", flush=True)


def salto_de_luz(antes, depois):
    """Diferenca de brilho medio entre os 4 ultimos quadros de uma tomada e os 4 primeiros da seguinte (0 a 255)."""
    claro = lambda qs: float(np.mean([f.mean() for f in qs]))
    return round(abs(claro(depois[:4]) - claro(antes[-4:])), 2)


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--projeto", required=True)
    a.add_argument("--so-acabar", action="store_true", help="so refaz o acabamento (final_hd.mp4) de um video pronto")
    a = a.parse_args()
    pasta = config.PROJETOS / a.projeto
    p = json.loads((pasta / "interface.json").read_text(encoding="utf-8"))
    arq_estado = pasta / "estado.json"
    estado = json.loads(arq_estado.read_text(encoding="utf-8"))
    feitas = estado.setdefault("tomadas", [])
    total = len(p["tomadas"])
    if a.so_acabar and len(feitas) < total:
        print("FALHA no acabamento: o video ainda nao tem todas as tomadas", flush=True)
        sys.exit(4)
    if len(feitas) >= total and not a.so_acabar and not falta_suavizar(p, estado):
        print("todas as tomadas ja estao prontas", flush=True)
        return

    mon = Monitor(pasta / "gpu.csv")
    mon.start()
    progresso = Progresso(pasta / "progresso.json", total, mon)
    acompanhar(progresso)

    def sair(codigo, mensagem):
        mon.fim.set()
        print(mensagem, flush=True)
        sys.exit(codigo)

    # O ComfyUI guarda carregadores pelo nome: cada execucao precisa de nomes proprios
    marca = int(time.time())
    wan_on = eh_wan(p)
    avancado = p.get("avancado")
    sem_imagem = bool(estado.get("sem_imagem"))
    # A pele natural precisa da foto como referencia da tomada 1; no texto para video e no Wan ela nao vale
    if sem_imagem or wan_on:
        p["pele"] = False
    if wan_on and sem_imagem:
        sair(4, "FALHA na geracao: o Wan precisa de uma imagem de partida")
    if wan_on:
        sem_par = [alta for alta, _ in p.get("loras") or [] if not wan.baixa_de(alta)]
        if sem_par:
            sair(4, f"FALHA na geracao: falta a metade LOW destas LoRAs na pasta loras: {', '.join(sem_par)}")
    # Modo audio: o audio enviado fica copiado no projeto (audio_arquivo); os cortes vieram da validacao (audio_fala.dividir)
    audio_on = bool(p.get("audio")) and not wan_on and not sem_imagem
    if audio_on:
        import audio_fala
        audio_proj = pasta / p["audio_arquivo"]
        if not audio_proj.is_file():
            sair(4, f"FALHA na geracao: o audio da fala sumiu da pasta do projeto ({p['audio_arquivo']})")
        pcm_audio = audio_fala.ler(audio_proj)
        p["pele"] = True
    for n in range(len(feitas) + 1, total + 1):
        t = p["tomadas"][n - 1]
        progresso.tomada(n)
        primeira = n == 1
        semente = random.randrange(2**48) if p["semente"] is None else p["semente"] + (0 if avancado else n * 100)
        prefixo = f"imagem/{a.projeto}/tomada{n}"
        if wan_on:
            # Wan: a primeira parte da imagem; cada uma das outras, do ultimo quadro da anterior
            quadros_ant = None if primeira else ler_quadros(caminhos.abrir(pasta, feitas[-1]["arquivo"]))
            imagem = estado["personagem"]
            if not primeira:
                arq_imagem, imagem = entrada_temp.arquivo(a.projeto, f"imagem_{a.projeto}_{marca}_ref{n}.png")
                salvar_quadro(quadros_ant[-1], arq_imagem)
            g = grafo_wan(p, t, imagem, prefixo, semente)
            prompt = g["31"]["inputs"]["text"]
        elif audio_on:
            # Cada tomada e um corte que sai da imagem, com o seu trecho do audio preso (e silencio ate completar a grade do H3)
            inicio, fim = p["cortes"][n - 1]
            quadros_audio = quadros_para(fim - inicio)
            arq_trecho, trecho = entrada_temp.arquivo(a.projeto, f"imagem_{a.projeto}_{marca}_audio{n}.wav")
            audio_fala.recortar(audio_proj, arq_trecho, inicio, fim, quadros_audio / FPS)
            fala = audio_fala.trechos_de_voz(pcm_audio, inicio, fim)
            g = grafo_audio(p, t, [estado["personagem"], *(p.get("referencias") or [])], p.get("cenario"), trecho, quadros_audio, fala, prefixo, semente)
            prompt = g["20"]["inputs"]["prompt"]
        elif avancado:
            g = None  # as referências preparadas só existem durante o pedido ao ComfyUI
        elif primeira and p.get("pele"):
            g = grafo_pele(p, t, estado["personagem"], prefixo, semente)
            prompt = g["20"]["inputs"]["prompt"]
        elif primeira:
            g = grafo_primeira(p, t, None if sem_imagem else estado["personagem"], prefixo, semente)
            prompt = g["20"]["inputs"]["prompt"]
        else:
            anterior = caminhos.abrir(pasta, feitas[-1]["arquivo"])
            quadros_ant = ler_quadros(anterior)
            arq_video, video = entrada_temp.arquivo(a.projeto, f"imagem_{a.projeto}_{marca}_t{n - 1}.mp4")
            shutil.copy2(anterior, arq_video)
            arq_ref, ref = entrada_temp.arquivo(a.projeto, f"imagem_{a.projeto}_{marca}_ref{n}.png")
            salvar_quadro(quadros_ant[-1], arq_ref)
            personagem = p.get("referencias") or [estado["personagem"]]
            g = grafo_continuacao(p, t, video, max(0.0, len(quadros_ant) / FPS - CONTEXTO), [*personagem, ref], estado.get("voz"), prefixo, semente, n)
            prompt = g["365"]["inputs"]["prompt"]
            semente = g["16"]["inputs"]["seed"]
        print(f"tomada {n} de {total} | {wan.quadros_wan(t['duracao']) if wan_on else quadros_audio if audio_on else total_quadros(t['duracao'])} quadros | semente {semente}"
              + (f" | {wan.MODELOS_WAN[p['modelo']]['nome']}" if wan_on else ""), flush=True)
        if avancado:
            try:
                with video_avancado.preparar_referencias(avancado["referencias"], a.projeto, marca, total_quadros(t["duracao"]), FPS) as refs:
                    g = grafo_avancado(p, refs, prefixo, semente)
                    prompt = g["20"]["inputs"]["prompt"]
                    progresso.grafo(g)
                    r = rodar(g, 1800)
            except video_avancado.Erro as e:
                sair(4, f"FALHA na geração: {e}")
        else:
            progresso.grafo(g)
            r = rodar(g, 1800)
        if mon.quente:
            sair(5, "PARADO por temperatura")
        if r["status"] == "servidor caiu":
            sair(3, f"SERVIDOR CAIU: {r['erro'][:300]}")
        if r["status"] != "success":
            sair(4, f"FALHA na geracao: {r['status']} {r['erro'][:700]}")

        progresso.montando()
        saida = nome_livre(pasta, n)
        if wan_on:
            bruto = arquivo_de_saida(r["saidas"].get("72", {}))
            if bruto is None or not bruto.is_file():
                sair(4, f"FALHA na geracao: o ComfyUI nao informou o video. Saidas: {list(r['saidas'])}")
            shutil.copy2(bruto, saida)
            q = ler_quadros(saida)
            # O primeiro quadro de uma tomada seguinte repete o ultimo da anterior
            pular, emenda = (0, None) if primeira else (1, None)
            if primeira:
                estado["cor_alvo"] = [float(x) for x in cor_do_fundo(q[-21:-5])]
            else:
                # Ainda sem correcao de cor: mede o salto na emenda e o quanto o fundo se afastou da primeira tomada
                deriva = float(cor_do_fundo(q[-8:]).mean()) / max(float(np.mean(estado["cor_alvo"])), 1.0)
                emenda = {"salto_luz": salto_de_luz(quadros_ant, q[1:]), "deriva_cor": round(deriva, 3)}
        elif audio_on or avancado:
            bruto = arquivo_de_saida(r["saidas"].get("26", {}))
            if bruto is None or not bruto.is_file():
                sair(4, f"FALHA na geracao: o ComfyUI nao informou o video. Saidas: {list(r['saidas'])}")
            shutil.copy2(bruto, saida)
            q = ler_quadros(saida)
            pular, emenda = 0, None
        elif primeira:
            bruto = arquivo_de_saida(r["saidas"].get("26", {}))
            if bruto is None or not bruto.is_file():
                sair(4, f"FALHA na geracao: o ComfyUI nao informou o video. Saidas: {list(r['saidas'])}")
            shutil.copy2(bruto, saida)
            q = ler_quadros(saida)
            pular, emenda = 0, None
            estado["cor_alvo"] = [float(x) for x in cor_do_fundo(q[-21:-5])]
            if sem_imagem:
                # O personagem das tomadas seguintes (e do refino) e o quadro do meio da tomada 1, que saiu do texto
                foto = f"imagem_{a.projeto}_{marca}_personagem.png"
                salvar_quadro(q[len(q) // 2], entrada.novo(foto))
                estado["personagem"] = foto
        else:
            bruto = arquivo_de_saida(r["saidas"].get("34", {}))
            if bruto is None or not bruto.is_file():
                sair(4, f"FALHA na geracao: o ComfyUI nao informou o video. Saidas: {list(r['saidas'])}")
            q = ler_quadros(bruto)
            pular = len(q) - total_quadros(t["duracao"])
            emenda = medir_emenda(q, pular, SOBREPOSICAO)
            emenda["ganho_cor"] = corrigir_tomada(bruto, q, pular, quadros_ant, saida)

        if not wan_on and not audio_on and limpar(t["fala"]) and not estado.get("voz"):
            voz = f"imagem_{a.projeto}_{marca}_voz.wav"
            if extrair_voz(saida, entrada.novo(voz), pular / FPS):
                estado["voz"], estado["voz_tomada"] = voz, n

        feitas.append({"n": n, "arquivo": caminhos.guardar(pasta, saida), "pular": pular, "total": len(q), "sobreposicao": 0 if wan_on or audio_on or avancado else SOBREPOSICAO, "semente": semente, "segundos": r["segundos"], "pico_vram": r["pico_vram"], "temp_max": r["temp_max"], "emenda": emenda, "prompt": prompt})
        if audio_on:
            # Quantos quadros da tomada entram no video: o tamanho do trecho do audio (o resto e o silencio da grade do H3)
            feitas[-1]["usar"] = min(len(q), round((p["cortes"][n - 1][1] - p["cortes"][n - 1][0]) * FPS))
        # O final.mp4 volta a ser montado das tomadas, a 16 ou 24 quadros por segundo: a suavizacao, se pedida, refaz no fim
        estado.pop("suavizado", None), estado.pop("fps_final", None)
        if avancado:
            shutil.copy2(saida, pasta / "final.mp4")
        caminhos.gravar_json(arq_estado, estado)
        # A cada tomada, para sempre haver um video com o que ja esta pronto
        if wan_on:
            juntar_sem_audio(pasta, feitas, wan.FPS_WAN)
        elif audio_on:
            juntar_audio(pasta, feitas, audio_proj)
        elif not avancado:
            juntar(pasta, {"rodadas": feitas}, 10**6)
            nivelar(pasta, feitas, [bool(limpar(x["fala"])) for x in p["tomadas"][:len(feitas)]])
        print(f"tomada {n} pronta: {r['segundos']} s | pico {r['pico_vram']} MiB | {r['temp_max']} C", flush=True)

    if falta_suavizar(p, estado) and len(feitas) >= total:
        suavizar(pasta, a.projeto, marca, progresso, mon, sair)
        estado["suavizado"], estado["fps_final"] = True, FPS_SUAVE
        caminhos.gravar_json(arq_estado, estado)
    if p.get("acabamento", "nenhum") != "nenhum":
        acabar(pasta, p, estado, progresso, marca, mon, sair)
        caminhos.gravar_json(arq_estado, estado)
    mon.fim.set()
    print(f"final: {pasta / 'final.mp4'}", flush=True)


def acabar(pasta, p, estado, progresso, marca, mon, sair):
    """Gera final_hd.mp4 a partir do final.mp4: so ESRGAN, ou refino do H3 em pedacos e depois ESRGAN."""
    import acabamento as ac
    modo, final = p["acabamento"], pasta / "final.mp4"
    parte, hd = pasta / "final_hd_parte.mp4", pasta / "final_hd.mp4"
    inicio, medidas = time.time(), []
    print(f"acabamento: {modo}", flush=True)
    try:
        if modo == "refino":
            quadros = ler_quadros(final)
            altura, largura = quadros[0].shape[:2]
            refs = p.get("referencias") or [estado["personagem"]]
            trechos = intervalos(estado["tomadas"])
            quem = limpar(p["quem"]) or QUEM_PADRAO

            def prompts(a, b):
                # O texto da tomada que ocupa o meio do pedaco
                meio = (a + b) / 2 / FPS
                n = next((i for i, (x, y) in enumerate(trechos) if x <= meio < y), len(trechos) - 1)
                return ac.prompt_refino(quem, p["tomadas"][n], len(refs))

            tam, inicios = ac.plano_refino(len(quadros))
            lw, lh = ac.tamanho_refino(largura, altura)
            print(f"refino: {len(inicios)} pedacos de {tam} quadros em {lw}x{lh}", flush=True)
            tam, prontos, medidas = ac.refinar(quadros, largura, altura, prompts, refs, pasta.name, f"imagem_{pasta.name}_{marca}", f"imagem/{pasta.name}/refino",
                                               p["semente"] if p["semente"] is not None else random.randrange(2**48),
                                               avisar=lambda f, t: progresso.acabando("refinar", f, t))
            if mon.quente:
                sair(5, "PARADO por temperatura")
            fonte, total = ac.misturar(quadros, tam, prontos), len(quadros)
        else:
            fonte, total = ac.quadros_de(final), ac.contar_quadros(final)
        ac.liberar_comfy()
        progresso.acabando("ampliar", 0, total)
        ac.esrgan(fonte, total, final, parte, p["proporcao"], avisar=lambda f, t: progresso.acabando("ampliar", f, t), fps=estado.get("fps_final") or (wan.FPS_WAN if eh_wan(p) else FPS))
        os.replace(parte, hd)
    except RuntimeError as e:
        sair(3 if "servidor caiu" in str(e) else 4, f"FALHA no acabamento: {e}")
    estado["acabamento"] = {"modo": modo, "segundos": round(time.time() - inicio), "pedacos": medidas,
                            "pico_vram": max([m.get("pico_vram") or 0 for m in medidas], default=0), "temp_max": max([m.get("temp_max") or 0 for m in medidas], default=0)}
    print(f"acabamento pronto: {hd} | {estado['acabamento']['segundos']} s", flush=True)


if __name__ == "__main__":
    main()
