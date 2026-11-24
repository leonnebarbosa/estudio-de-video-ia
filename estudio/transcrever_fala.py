"""Transcreve a fala de um audio com o faster-whisper, na CPU. Roda no Python do transcritor (local.json "python_transcricao"), que
nao e o do ComfyUI: por isso nao importa nada do estudio. Quem chama e descrever_video.transcrever.

Uso: python -I transcrever_fala.py audio.wav modelo idioma
Escreve na saida, em UTF-8, {"palavras": [[inicio, fim, "palavra"], ...]} (segundos) ou {"erro": "o que houve"}.
O modelo so e lido do disco (local_files_only): um modelo que nao esta baixado vira erro, nada e baixado sem combinar.
"""
import json
import sys


def responder(dados, codigo=0):
    sys.stdout.buffer.write(json.dumps(dados, ensure_ascii=False).encode("utf-8"))
    sys.stdout.buffer.flush()
    return codigo


def main():
    if len(sys.argv) < 4:
        return responder({"erro": "uso: transcrever_fala.py audio modelo idioma"}, 2)
    audio, modelo, idioma = sys.argv[1:4]
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return responder({"erro": "o faster-whisper não está instalado neste Python"}, 3)
    try:
        m = WhisperModel(modelo, device="cpu", compute_type="int8", local_files_only=True)
    except Exception as e:
        return responder({"erro": f"o modelo de transcrição {modelo} não está baixado ({type(e).__name__})"}, 4)
    try:
        trechos, _ = m.transcribe(audio, language=idioma, word_timestamps=True, vad_filter=False, beam_size=5)
        palavras = [[round(float(p.start), 2), round(float(p.end), 2), p.word.strip()] for t in trechos for p in (t.words or [])]
    except Exception as e:
        return responder({"erro": f"não consegui transcrever ({type(e).__name__}: {e})"[:300]}, 5)
    return responder({"palavras": palavras})


if __name__ == "__main__":
    sys.exit(main())
