"""Referências nomeadas do modo livre do MiniMax H3."""
import re
import subprocess
from collections import Counter
from contextlib import ExitStack, contextmanager
from pathlib import Path

import imageio_ffmpeg

import config
import entrada
import entrada_temp
import loras
from erros import Erro


MODELO = "minimax_h3_ref2va_pruned_int8_convrot.safetensors"
TURBO = "minimax_h3_ref2v_turbo_8step_v1.1_768p_comfyui_bf16.safetensors"
CLIP = "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
VAE = "minimax_h3_video_vae_int8_convrot.safetensors"
AUDIO_VAE = "minimax_h3_audio_vae_fp32.safetensors"
LIMITES = {"foto": 9, "video": 3, "audio": 3}
ROTULOS = {"foto": "Picture", "video": "Video", "audio": "Audio"}
SUFIXOS = {
    "foto": (".png", ".jpg", ".jpeg", ".webp"),
    "video": (".mp4",),
    "audio": (".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac"),
}
MAX_PROMPT = 8000
NOME = re.compile(r"[a-z][a-z0-9_-]{0,31}")
MENCAO = re.compile(r"(?<![\w@])@([\w-]+)")
TAG = re.compile(r"<(Picture|Video|Audio) (\d+)>")


def faltam():
    arquivos = (("diffusion_models", MODELO), ("text_encoders", CLIP), ("vae", VAE), ("vae", AUDIO_VAE))
    ausentes = [nome for pasta, nome in arquivos if not (config.MODELOS / pasta / nome).is_file()]
    return ausentes + ([] if TURBO.lower() in loras.mapa() else [TURBO])


def caminho_referencia(tipo, arquivo):
    if not isinstance(arquivo, str) or not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*", arquivo):
        raise Erro("Arquivo de referência inválido.")
    if Path(arquivo).suffix.lower() not in SUFIXOS[tipo]:
        raise Erro(f"O formato de {arquivo} não corresponde ao tipo da referência.")
    # Foto e audio: em input/estudio/envios ou, nos antigos, na raiz do input
    pastas = [config.ENVIOS] if tipo == "video" else [entrada.pasta_envios(), config.ENTRADA]
    caminho = config.ENVIOS / arquivo if tipo == "video" else entrada.caminho(arquivo)
    if not caminho.is_file() or caminho.resolve().parent not in [p.resolve() for p in pastas]:
        raise Erro(f"Envie a referência de novo: {arquivo}.")
    return caminho


def numerar(referencias):
    """A ordem é independente por tipo. Vídeos fornecem só os quadros."""
    indices = Counter()
    for ref in referencias:
        tipo = ref["tipo"]
        indices[tipo] += 1
        yield ref, indices[tipo]


def resolver_prompt(prompt, referencias):
    nomes = {ref["nome"]: f"<{ROTULOS[ref['tipo']]} {i}>" for ref, i in numerar(referencias)}

    def trocar(m):
        tag = nomes.get(m[1].lower())
        if tag is None:
            raise Erro(f"A referência @{m[1]} não foi adicionada.")
        return tag

    resolvido = MENCAO.sub(trocar, prompt)
    tags = set(nomes.values())
    for m in TAG.finditer(resolvido):
        if m[0] not in tags:
            raise Erro(f"A referência {m[0]} não foi adicionada.")
    return resolvido


def validar_referencias(referencias):
    if not isinstance(referencias, list) or not 1 <= len(referencias) <= sum(LIMITES.values()):
        raise Erro("Adicione de 1 a 15 referências.")
    validadas = []
    nomes = set()
    for ref in referencias:
        if not isinstance(ref, dict):
            raise Erro("Uma referência veio incompleta.")
        tipo, nome, arquivo = ref.get("tipo"), ref.get("nome"), ref.get("arquivo")
        if not isinstance(tipo, str) or tipo not in LIMITES:
            raise Erro("Tipo de referência desconhecido.")
        nome = nome.strip().lower() if isinstance(nome, str) else ""
        if not NOME.fullmatch(nome):
            raise Erro("Dê a cada referência um nome que comece com letra e use letras sem acento, números, _ ou -.")
        if nome in nomes:
            raise Erro(f"Há duas referências chamadas @{nome}.")
        caminho_referencia(tipo, arquivo)
        nomes.add(nome)
        validadas.append({"tipo": tipo, "nome": nome, "arquivo": arquivo})
    for ref, i in numerar(validadas):
        if i > LIMITES[ref["tipo"]]:
            raise Erro("Use até 9 imagens, 3 vídeos e 3 áudios.")
    return validadas


def preparar_arquivo(origem, destino, tipo, quadros, fps):
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-nostdin", "-y", "-hide_banner", "-loglevel", "error", "-i", str(origem)]
    if tipo == "video":
        filtro = f"fps={fps},scale=w='min(iw,960)':h='min(ih,960)':force_original_aspect_ratio=decrease:force_divisible_by=2"
        cmd += ["-map", "0:v:0", "-an", "-vf", filtro,
                "-frames:v", str(quadros), "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p"]
    else:
        cmd += ["-map", "0:a:0", "-vn", "-t", "15", "-ar", "32000", "-ac", "2"]
    r = subprocess.run([*cmd, str(destino)], capture_output=True, text=True, errors="replace", creationflags=config.SEM_JANELA)
    if r.returncode:
        raise Erro(f"Não consegui preparar a referência {origem.name}: {r.stderr.strip()[:180]}")


@contextmanager
def preparar_referencias(referencias, projeto, marca, quadros, fps):
    """Prepara vídeos a 24 fps e limita a mídia carregada pelo ComfyUI."""
    with ExitStack() as pilha:
        prontas = []
        for ref, i in numerar(referencias):
            tipo = ref["tipo"]
            origem = caminho_referencia(tipo, ref["arquivo"])
            arquivo = origem.name
            if tipo != "foto":
                ext = ".mp4" if tipo == "video" else ".wav"
                destino, nome = entrada_temp.arquivo(projeto, f"imagem_{projeto}_{marca}_av_{tipo}{i}{ext}")
                pilha.callback(destino.unlink, missing_ok=True)
                preparar_arquivo(origem, destino, tipo, quadros, fps)
                arquivo = nome
            prontas.append({**ref, "arquivo": arquivo})
        yield prontas
