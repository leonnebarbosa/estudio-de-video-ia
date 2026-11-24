"""Aviso de prompt comprido: Klein, Z-Image, Chroma, Krea 2 e Wan foram feitos para ate 512 tokens de texto (o codigo oficial corta o
resto). O ComfyUI nao corta: manda o texto inteiro, e o fim pode ser ignorado. Aqui so se conta e avisa; nada e cortado nem bloqueado.
H3 e Qwen Image 2.1 nao tem limite no codigo oficial, e o SDXL nao usa estes codificadores: ficam sem aviso (pesquisa de 24/11/2026).

A conta usa os mesmos tokenizadores do ComfyUI, sem carregar o torch (Qwen e T5 bateram com os dele em 44 de 44 textos, 24/11/2026).
Se um arquivo ou biblioteca faltar, nao ha aviso: a contagem nunca atrapalha a geracao."""
import functools, json, struct

import config

LIMITE = 512
CODIFICADORES = config.RAIZ_COMFY / "ComfyUI" / "comfy" / "text_encoders"
_PEDACOS_QWEN = (r"(?i:'s|'t|'re|'ve|'m|'ll|'d)|[^\r\n\p{L}\p{N}]?\p{L}+|\p{N}| ?[^\s\p{L}\p{N}]+[\r\n]*|\s*[\r\n]+|\s+(?!\S)|\s+")
# tipo_encoder de MODELOS_TEXTO (e "wan") -> (nome no aviso, tokenizador, o molde que entra na conta dos 512). O Klein e o Z-Image contam o molde da
# conversa; o Krea 2 deixa a introducao de fora e conta so o fecho (encoder.py oficial)
_TIPOS = {
    "flux2": ("FLUX.2 Klein", "qwen", "<|im_start|>user\n{}<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"),
    "lumina2": ("Z-Image", "qwen", "<|im_start|>user\n{}<|im_end|>\n<|im_start|>assistant\n"),
    "krea2": ("Krea 2", "qwen", "{}<|im_end|>\n<|im_start|>assistant\n"),
    "chroma": ("Chroma", "t5", "{}"),
    "wan": ("Wan", "umt5", "{}"),
}


@functools.lru_cache(maxsize=None)
def _contador(nome):
    """Uma funcao texto -> numero de tokens. Levanta se faltar arquivo ou biblioteca."""
    if nome == "umt5":
        import sentencepiece
        from wan_para_video import ENCODER
        # O tokenizador do umT5 vem dentro do .safetensors: so o cabecalho e esse pedaco sao lidos
        caminho = next(p for p in (config.MODELOS / d / ENCODER for d in ("text_encoders", "clip")) if p.is_file())
        with open(caminho, "rb") as f:
            n = struct.unpack("<Q", f.read(8))[0]
            inicio, fim = json.loads(f.read(n))["spiece_model"]["data_offsets"]
            f.seek(8 + n + inicio)
            sp = sentencepiece.SentencePieceProcessor(model_proto=f.read(fim - inicio))
        return lambda texto: len(sp.encode(texto)) + 1  # + o fim de texto
    from tokenizers import AddedToken, Regex, Tokenizer, models, normalizers, pre_tokenizers
    if nome == "t5":
        t = Tokenizer.from_file(str(CODIFICADORES / "t5_tokenizer" / "tokenizer.json"))
    else:
        pasta = CODIFICADORES / "qwen25_tokenizer"
        t = Tokenizer(models.BPE.from_file(str(pasta / "vocab.json"), str(pasta / "merges.txt")))
        t.normalizer = normalizers.NFC()
        t.pre_tokenizer = pre_tokenizers.Sequence([pre_tokenizers.Split(Regex(_PEDACOS_QWEN), "isolated"),
                                                   pre_tokenizers.ByteLevel(add_prefix_space=False, use_regex=False)])
        especiais = json.loads((pasta / "tokenizer_config.json").read_text(encoding="utf-8"))["added_tokens_decoder"]
        t.add_special_tokens([AddedToken(v["content"], special=True, normalized=False) for v in especiais.values()])
    return lambda texto: len(t.encode(texto).ids)


def contar(tipo, texto):
    """Os tokens que o texto ocupa dos 512, ou None: tipo sem limite, ou sem como contar."""
    if tipo not in _TIPOS:
        return None
    _, nome, molde = _TIPOS[tipo]
    try:
        return _contador(nome)(molde.replace("{}", texto))
    except Exception:  # falta de arquivo ou biblioteca, ou tokenizador de outro formato: so fica sem aviso
        return None


def aviso(tipo, texto, oque="o prompt"):
    """A frase do aviso, ou "" quando cabe (ou nao ha limite)."""
    n = contar(tipo, texto)
    if n is None or n <= LIMITE:
        return ""
    return (f"Aviso: {oque} tem {n} tokens e o {_TIPOS[tipo][0]} foi feito para até {LIMITE}. O fim pode ser ignorado; "
            "encurte ou ponha o mais importante no começo.")


def aviso_imagem(a):
    """O aviso dos ajustes do Texto para imagem (lerTexto da pagina, ou o plano do MCP), ou ""."""
    from texto_para_imagem import MODELOS_TEXTO, modelo_do_estilo
    prompt, modelo = str(a.get("prompt") or ""), a.get("modelo")
    try:
        if a.get("estilo"):
            # As cores da foto so saem na hora de gerar (ate 120 tokens a mais): o estilo conta sem elas
            import estilos
            modelo, prompt = modelo_do_estilo(a), estilos.pedido(a["estilo"], None, prompt)
    except (KeyError, TypeError, ValueError):
        return ""
    m = MODELOS_TEXTO.get(modelo) if isinstance(modelo, str) else None
    return aviso(m.get("tipo_encoder"), prompt) if m else ""


def avisos_wan(a):
    """Um aviso por tomada que passa, nos ajustes do Imagem para video com o Wan (o texto que o grafo manda)."""
    import imagem_para_video, loras
    from wan_para_video import MODELOS_WAN
    if not isinstance(a.get("modelo"), str) or a["modelo"] not in MODELOS_WAN:
        return []
    estilo = [x for x in a.get("loras") or [] if isinstance(x, (list, tuple)) and x and isinstance(x[0], str)]
    saida = []
    for i, t in enumerate(a.get("tomadas") or [], 1):
        if not isinstance(t, dict) or t.get("camera") not in imagem_para_video.CAMERAS:
            continue
        tomada = {"camera": t["camera"], "olhar": bool(t.get("olhar")), "acao": str(t.get("acao") or "")}
        texto = loras.com_gatilho(estilo, imagem_para_video.prompt_wan(tomada), ", ")
        saida.append(aviso("wan", texto, f"a tomada {i}"))
    return [x for x in saida if x]


def do_pedido(d):
    """A rota /api/contar-tokens: {"alvo": "imagem"|"wan"|"pintura", "ajustes": {...}} -> {"avisos": [...]}."""
    a = d.get("ajustes") if isinstance(d.get("ajustes"), dict) else {}
    alvo = d.get("alvo")
    if alvo == "wan":
        return {"avisos": avisos_wan(a)}
    x = ""
    if alvo == "imagem":
        x = aviso_imagem(a)
    elif alvo == "pintura":  # Editar video: o pedido em ingles que o Klein recebe
        x = aviso_imagem({"modelo": "klein_edit", "prompt": a.get("prompt")})
    return {"avisos": [x] if x else []}
