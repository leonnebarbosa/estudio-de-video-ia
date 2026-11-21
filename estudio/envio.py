"""Recebe e confere os arquivos enviados pela pagina."""
import filecmp, os, re
from pathlib import Path

import av
from PIL import Image

import config
import validacao


def nome_limpo(nome):
    base = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(nome.replace("\\", "/")).name).strip("._")
    return base or "arquivo"


def examinar_video(caminho):
    try:
        c = av.open(str(caminho))
    except Exception:
        raise validacao.Erro("O arquivo não abriu como vídeo.")
    try:
        if not c.streams.video:
            raise validacao.Erro("O arquivo não tem imagem de vídeo.")
        v = c.streams.video[0]
        fps = float(v.average_rate or validacao.FPS)
        largura, altura = v.width, v.height
        audio = len(c.streams.audio) > 0
        quadros = sum(1 for p in c.demux(v) if p.size)
    finally:
        c.close()
    return {"quadros": quadros, "fps": round(fps, 2), "largura": largura, "altura": altura, "audio": audio, "duracao": round(quadros / fps, 2)}


SUFIXOS_AUDIO = (".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac")


def examinar_audio(caminho):
    try:
        c = av.open(str(caminho))
    except Exception:
        raise validacao.Erro("O arquivo não abriu como áudio.")
    try:
        if not c.streams.audio:
            raise validacao.Erro("O arquivo não tem som.")
        duracao = float(c.duration / 1_000_000) if c.duration else 0.0
    finally:
        c.close()
    if duracao <= 0:
        raise validacao.Erro("Não consegui ler a duração do áudio.")
    return {"duracao": round(duracao, 2)}


def destino_livre(pasta, nome, arquivo):
    """Reaproveita o nome se o conteudo for igual; nunca devolve o nome de um arquivo diferente."""
    destino = pasta / nome
    i = 2
    while destino.exists() and not filecmp.cmp(arquivo, destino, shallow=False):
        destino = pasta / f"{Path(nome).stem}_{i}{Path(nome).suffix}"
        i += 1
    return destino


def receber_arquivo(fluxo, tamanho, tipo, nome):
    """Grava em .parte, valida e so entao da o nome final. Nunca substitui um arquivo diferente."""
    nome = nome_limpo(nome)
    sufixo = Path(nome).suffix.lower()
    if tipo == "video":
        if sufixo != ".mp4":
            raise validacao.Erro("Escolha um vídeo em MP4.")
        pasta = config.ENVIOS
    elif tipo == "foto":
        if sufixo not in (".png", ".jpg", ".jpeg", ".webp"):
            raise validacao.Erro("Escolha uma foto em PNG, JPG ou WEBP.")
        pasta = config.ENTRADA
    elif tipo == "audio":
        # Audio da fala do Imagem para video (modo audio, 20/11/2026): vai para a pasta input, como as fotos
        if sufixo not in SUFIXOS_AUDIO:
            raise validacao.Erro("Escolha um áudio em MP3, WAV, M4A, OGG ou FLAC.")
        pasta = config.ENTRADA
    else:
        raise validacao.Erro("Tipo de arquivo desconhecido.")
    pasta.mkdir(parents=True, exist_ok=True)
    parte = pasta / f".{nome}.parte"
    try:
        resta = tamanho
        with parte.open("wb") as f:
            while resta > 0:
                bloco = fluxo.read(min(1024 * 1024, resta))
                if not bloco:
                    raise validacao.Erro("O envio foi interrompido. Escolha o arquivo de novo.")
                f.write(bloco)
                resta -= len(bloco)
        if tipo == "video":
            info = examinar_video(parte)
        elif tipo == "audio":
            info = examinar_audio(parte)
        else:
            try:
                with Image.open(parte) as im:
                    largura, altura = im.size
                    im.verify()
            except Exception:
                raise validacao.Erro("O arquivo não abriu como imagem.")
            info = {"largura": largura, "altura": altura}
        destino = destino_livre(pasta, nome, parte)
        # Se o arquivo ja existe, o conteudo e igual: no Windows, gravar por cima falha se a pagina estiver lendo a miniatura
        if not destino.exists():
            os.replace(parte, destino)
        return {**info, "arquivo": destino.name}
    except OSError as e:
        raise validacao.Erro(f"Não consegui gravar o arquivo. Tente de novo. ({e.strerror or e})", 500)
    finally:
        parte.unlink(missing_ok=True)
