"""Recebe e confere os arquivos que entram no estudio (pagina, link, importar_url e MCP): grava, valida o conteudo e registra em midias.json."""
import filecmp, os, re, secrets, sys, threading, traceback
from pathlib import Path

import av
from PIL import Image

import config
import entrada
import midias
import validacao

_trava_nome = threading.Lock()


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
    """Reaproveita o nome se o conteudo for igual; nunca devolve o nome de um arquivo diferente. `pasta` None: a pasta
    input do ComfyUI, onde o nome livre precisa estar livre em envios e na raiz (o arquivo antigo de mesmo nome pode
    estar la); o novo vai para envios."""
    achar = entrada.caminho if pasta is None else (lambda n: pasta / n)
    destino = achar(nome)
    i = 2
    while destino.exists() and not filecmp.cmp(arquivo, destino, shallow=False):
        destino = achar(f"{Path(nome).stem}_{i}{Path(nome).suffix}")
        i += 1
    return destino


def receber_arquivo(fluxo, tamanho, tipo, nome, origem="pagina"):
    """Grava num .parte proprio do envio, valida e so entao da o nome final. Nunca substitui um arquivo diferente.
    Depois de aceitar, anota a midia em midias.json com a `origem` ("pagina", "link", "url" ou "mcp")."""
    nome = nome_limpo(nome)
    sufixo = Path(nome).suffix.lower()
    if tipo == "video":
        if sufixo != ".mp4":
            raise validacao.Erro("Escolha um vídeo em MP4.")
        pasta = config.ENVIOS
    elif tipo == "foto":
        if sufixo not in (".png", ".jpg", ".jpeg", ".webp"):
            raise validacao.Erro("Escolha uma foto em PNG, JPG ou WEBP.")
        pasta = None  # input/estudio/envios (destino_livre confere tambem a raiz do input)
    elif tipo == "audio":
        # Audio da fala do Imagem para video (modo audio, 20/11/2026): vai para a pasta input, como as fotos
        if sufixo not in SUFIXOS_AUDIO:
            raise validacao.Erro("Escolha um áudio em MP3, WAV, M4A, OGG ou FLAC.")
        pasta = None
    else:
        raise validacao.Erro("Tipo de arquivo desconhecido.")
    pasta_parte = entrada.pasta_envios() if pasta is None else pasta
    pasta_parte.mkdir(parents=True, exist_ok=True)
    parte = pasta_parte / f".{nome}.{secrets.token_hex(4)}.parte"  # um por envio: dois envios com o mesmo nome nao dividem o arquivo
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
        with _trava_nome:  # escolher o nome e dar o nome e um passo so: dois envios do mesmo nome nao escolhem o mesmo destino
            destino = destino_livre(pasta, nome, parte)
            # Se o arquivo ja existe, o conteudo e igual: no Windows, gravar por cima falha se a pagina estiver lendo a miniatura
            if not destino.exists():
                os.replace(parte, destino)
        try:
            midias.registrar(destino.name, tipo, origem, info)
        except Exception:  # o registro ajuda o agente a achar a midia, mas nao pode derrubar um envio que deu certo
            print(f"Aviso: não consegui registrar {destino.name} em midias.json.", file=sys.stderr)
            traceback.print_exc()
        return {**info, "arquivo": destino.name}
    except TimeoutError:
        raise validacao.Erro("O envio parou de chegar. Tente de novo.", 408)
    except OSError as e:
        raise validacao.Erro(f"Não consegui gravar o arquivo. Tente de novo. ({e.strerror or e})", 500)
    finally:
        parte.unlink(missing_ok=True)
