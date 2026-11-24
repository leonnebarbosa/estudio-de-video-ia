"""Mudar o estilo de uma foto (Editar imagem com um estilo pronto). Desenho: docs/superpowers/specs/2026-11-23-estilo-foto-design.md.

Pedidos validados em 23/11/2026 (projetos/teste_estilo_foto): a mesma pessoa, pose, roupa e cena, redesenhada no estilo. Antes das
imagens, a LLM de visao descreve as cores da foto (INSTRUCAO_CORES) e elas entram travadas no pedido (TRAVA): sem isso o Klein clareava
o cabelo e a pele e inventava fundo. No lapis a trava nao entra (o desenho e cinza e a cor da roupa vazava).

Motor: o Klein 4B por padrao; a chave Qualidade alta leva ao Klein 9B (mais fiel ao rosto e as cores, ~2x mais lento). O realista
(desenho para foto) liga a chave sozinho na pagina; sem ela, vai para o Qwen 2.1, que mantem a pessoa."""

BASE = ("Redraw this exact image as {estilo}. Keep the same person with the same face shape, eyes, eyebrows, nose, lips, hairstyle, "
        "hair color and expression, the same pose, clothing, framing and background. Change only the rendering style, not the content.")
TRAVA = (" Keep these colors exactly as in the original: {cores}. Do not lighten or change the hair color, skin tone or eye color. "
         "Keep the background as it is; do not add or invent any scenery.")
REALISTA = ("Turn this illustration into a real candid photograph of a real person, taken with a modern smartphone camera. "
            "Keep the same person, face shape, expression, hairstyle, pose, clothing, framing and background layout. "
            "Real human anatomy: normal-size eyes with detailed irises and catchlights, a real nose and real lips, natural asymmetry. "
            "Skin with visible pores, fine peach fuzz, slight unevenness and natural redness, no makeup look, no airbrushing. "
            "Hair as individual strands with flyaways. Fabric with real weave and natural wrinkles. Soft natural window light, "
            "realistic shadows, slight depth of field, subtle sensor noise. Photorealistic. No drawing, no outlines, no cel shading, "
            "no cartoon, anime or 3D render look.")
INSTRUCAO_CORES = ("Look at this image and write one short line in English, with no preamble, listing only the colors that must be "
                   "kept: hair color and hairstyle, skin tone, eye color, the color of each clothing item, and the background in a few "
                   "words (for example 'plain light grey studio background'). Use precise color words such as 'dark brown', 'jet black', "
                   "'light olive', 'medium tan', 'dark brown eyes', 'hazel eyes'; never write just 'dark', 'light' or 'fair' alone.")

# id: nome na tela, o estilo para a BASE (o realista tem pedido proprio) e se as cores entram travadas
ESTILOS = {
    "anime": {"nome": "Anime", "cores": True,
              "texto": "a Japanese anime illustration: clean line art, cel shading with flat colors and soft shadows, expressive anime eyes, "
                       "painted anime background"},
    "cartoon3d": {"nome": "Cartoon 3D", "cores": True,
                  "texto": "a 3D animated movie still: stylized cartoon proportions, big expressive eyes, smooth soft skin shading, soft global "
                           "illumination, subsurface scattering, colorful 3D animated feature film look"},
    "quadrinhos": {"nome": "Quadrinhos", "cores": True,
                   "texto": "a comic book illustration: bold black ink outlines, halftone dot shading, flat saturated colors, dramatic inking"},
    "aquarela": {"nome": "Aquarela", "cores": True,
                 "texto": "a watercolor painting on textured paper: soft wet washes, loose brush strokes, gentle color bleeding, visible paper "
                          "grain, white paper showing through"},
    "oleo": {"nome": "Pintura a óleo", "cores": True,
             "texto": "a classical oil painting on canvas: visible thick brush strokes, rich impasto texture, painterly light, canvas weave"},
    "lapis": {"nome": "Lápis", "cores": False,
              "texto": "a graphite pencil sketch on white paper: hand-drawn lines, cross-hatching, smudged graphite shading, monochrome grey, "
                       "no color"},
    "pixelart": {"nome": "Pixel art", "cores": True,
                 "texto": "16-bit pixel art: a low resolution grid of clearly visible square pixels, limited color palette, crisp pixel edges, "
                          "retro video game look"},
    "realista": {"nome": "Realista (desenho para foto)", "cores": True, "texto": None},
}
MOTOR_RAPIDO, MOTOR_ALTO, MOTOR_REALISTA_SEM_9B = "klein_edit", "klein9b_edit", "qwen21_edit"
# Modelos em que a chave Qualidade alta troca o Klein 4B pelo 9B (os arquivos do MOTOR_ALTO): Editar e Gerar (24/11/2026)
COM_9B = (MOTOR_RAPIDO, "klein_t2i")


def lista():
    """Os estilos para o seletor da pagina, na ordem."""
    return [{"id": k, "nome": v["nome"]} for k, v in ESTILOS.items()]


def usa_cores(estilo):
    return bool(ESTILOS[estilo]["cores"])


def pedido(estilo, cores=None, extra=""):
    """O pedido em ingles: o do estilo, as cores travadas (se o estilo usa e a LLM as descreveu) e o que o usuario acrescentou."""
    e = ESTILOS[estilo]
    texto = REALISTA if estilo == "realista" else BASE.format(estilo=e["texto"])
    if e["cores"] and cores:
        texto += TRAVA.format(cores=cores.strip().rstrip("."))
    extra = (extra or "").strip()
    return f"{texto} {extra}" if extra else texto


def motor(estilo, qualidade_alta):
    """O modelo de MODELOS_TEXTO que faz o estilo."""
    if qualidade_alta:
        return MOTOR_ALTO
    return MOTOR_REALISTA_SEM_9B if estilo == "realista" else MOTOR_RAPIDO
