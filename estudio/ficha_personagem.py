"""Prepara vistas independentes e monta a ficha sem uma nova geração."""
import secrets
import shutil

from PIL import Image, ImageOps

import config
import entrada_temp

FOLHA = "ficha.png"
VISTAS = ("rosto", "perfil", "frente", "costas")
ARQUIVOS = {vista: f"ficha_{vista}.png" for vista in VISTAS}
APROVACAO = "ficha_frente.ok"
ROUPA = "ficha_roupa.png"
CORPO = "ficha_corpo.png"  # Nova roupa: o corpo inteiro aprovado do personagem de base (personagens.criar_com_nova_roupa)
# Rosto e perfil empilhados à esquerda, frente e costas lado a lado na altura toda: os closes são 1:1 e os corpos 2:3,
# então as caixas encaixam sem faixas vazias (a grade 2x2 de antes deixava quase metade da folha em branco, 21/11)
ALTURA_FOLHA, VAO_FOLHA, FUNDO_FOLHA = 1344, 8, "#e5e3df"
_CLOSE, _CORPO = (ALTURA_FOLHA - VAO_FOLHA) // 2, ALTURA_FOLHA * 2 // 3
POSICOES_FOLHA = {
    "rosto": (0, 0, _CLOSE, _CLOSE),
    "perfil": (0, ALTURA_FOLHA - _CLOSE, _CLOSE, _CLOSE),
    "frente": (_CLOSE + VAO_FOLHA, 0, _CORPO, ALTURA_FOLHA),
    "costas": (_CLOSE + _CORPO + 2 * VAO_FOLHA, 0, _CORPO, ALTURA_FOLHA),
}
TAMANHO_FOLHA = (_CLOSE + 2 * _CORPO + 2 * VAO_FOLHA, ALTURA_FOLHA)
# Sem isto o Klein punha delineador, alisava a pele e, no perfil, prendia o cabelo atrás da orelha ou o alongava
# (teste de 21/11 em projetos/teste_ficha_realismo; a LoRA de pele do Civitai quase não somou)
REALISMO = (" Natural, unretouched skin with visible pores and fine skin texture, matte, true to life. Do not add makeup that is not in"
            " the character's photo: no added eyeliner, mascara or lipstick, no beauty filter. Looks like an unedited real camera photo, soft daylight.")
CABELO = (" Keep the exact same haircut, hair length, bangs and hairstyle as the character's photo: do not make the hair longer or shorter,"
          " and do not tuck it behind the ear unless it is like that in the photo.")
PEDIDOS = {
    "frente": "Full-body front-facing reference photo, from the top of the head to the shoes. Neutral standing pose, arms relaxed slightly away from the body.",
    "rosto": "Frontal head-and-shoulders close-up. Show the complete head, facial features and hairline in fine detail.",
    "perfil": "Exact side profile head-and-shoulders close-up facing left. Show the complete head, nose, chin, ear and hairstyle.",
    "costas": "Exact back view, full body from head to shoes. Match the approved front view's pose, body scale, garment shapes, colors and accessories.",
}


def estado(pasta):
    marcas = {v: str((pasta / a).stat().st_mtime_ns) for v, a in ARQUIVOS.items() if (pasta / a).is_file()}
    try:
        aprovada = (pasta / APROVACAO).read_text() == marcas.get("frente")
    except FileNotFoundError:
        aprovada = False
    return marcas, aprovada


def salvar(imagem, destino):
    temporario = destino.with_suffix(".tmp")
    try:
        imagem.save(temporario, format="PNG")
        temporario.replace(destino)
    finally:
        temporario.unlink(missing_ok=True)


def copiar(origem, destino):
    with Image.open(origem) as im:
        salvar(ImageOps.exif_transpose(im).convert("RGB"), destino)


def montar(pasta):
    marcas, aprovada = estado(pasta)
    if not aprovada or len(marcas) != len(VISTAS):
        return
    folha = Image.new("RGB", TAMANHO_FOLHA, FUNDO_FOLHA)
    for v, (x, y, w, h) in POSICOES_FOLHA.items():
        with Image.open(pasta / ARQUIVOS[v]) as im:
            # Os closes preenchem a caixa cortando as bordas (o recorte do rosto da foto original nem sempre é quadrado e o
            # rosto fica no centro); os corpos cabem inteiros, sem cortar cabeça nem pés, apoiados embaixo
            if v in ("rosto", "perfil"):
                painel = ImageOps.fit(im.convert("RGB"), (w, h), Image.Resampling.LANCZOS, centering=(0.5, 0.45))
            else:
                painel = ImageOps.contain(im.convert("RGB"), (w, h), Image.Resampling.LANCZOS)
            topo = y + (h - painel.height) // 2 if v in ("rosto", "perfil") else y + h - painel.height
            folha.paste(painel, (x + (w - painel.width) // 2, topo))
    salvar(folha, pasta / FOLHA)


def recortar_rosto(origem, destino):
    import cv2
    import rostos_video
    try:
        img = cv2.imread(str(origem))
        rosto = rostos_video.maior_rosto(rostos_video.detector(), img) if img is not None else None
    except (OSError, cv2.error):
        return False
    if rosto is None or min(rosto[2:4]) < 180:
        return False
    corte = rostos_video.recorte(img, [round(float(v)) for v in rosto[:4]])
    salvar(Image.fromarray(cv2.cvtColor(corte, cv2.COLOR_BGR2RGB)), destino)
    return True


def pedido_vista(vista, n_fontes, descricao, roupa_en="", corpo=False):
    """O pedido do Klein para uma vista. Na frente, `n_fontes` 2 = foto da roupa como 2ª imagem; `roupa_en` = roupa
    descrita em texto (já em inglês), que troca a roupa inteira sozinha ou completa a da foto. Com `corpo` (Nova roupa),
    a 1ª imagem é o corpo inteiro aprovado do personagem de base, a 2ª a foto original (o rosto) e a 3ª, se houver, a roupa."""
    if vista == "frente" and corpo:
        # Sem o corpo aprovado, a cópia de um personagem feito de um retrato recebia só o rosto e o Klein inventava outro
        # corpo; com o corpo primeiro ele manteve as curvas e as proporções (teste de 21/11 em projetos/teste_nova_roupa)
        pedido = PEDIDOS[vista] + (
            " The first image is the person in full body: keep their exact body shape, curves, height, proportions and hair,"
            " but not their clothing or pose. The second image is a close-up of their face: copy the face, identity and skin"
            " exactly from it."
        )
        if n_fontes > 2:
            pedido += (" Replace all of the clothing with the complete outfit from the third image: every garment, layer, sleeve"
                       " length, collar, color, texture, buttons and shoes exactly as shown there. Do not use the face, hair, age"
                       " or body of the person in the third image.") + (f" Outfit notes: {roupa_en}." if roupa_en else "")
        elif roupa_en:
            pedido += f" Replace all of the clothing with {roupa_en}. Nothing from the current clothing remains."
        else:
            pedido += " Keep the clothing of the first image."
        return pedido + REALISMO + " Plain light gray studio background, even lighting, no text. Only one character and one view." + (
            f" Character details: {descricao}" if descricao else "")
    troca_foto = vista == "frente" and n_fontes > 1
    if troca_foto:
        # Com "preserve a roupa" o Klein misturava as duas: o cardigã da roupa virava colete por cima da camiseta original (21/11)
        pedido = PEDIDOS[vista] + (
            " Use the first image only for the person: face, identity, skin, hair and body proportions."
            " Replace all of the clothing with the complete outfit from the second image: every garment, layer, sleeve length,"
            " collar, color, texture, buttons and shoes exactly as shown there. Nothing from the first image's clothing remains."
            " Do not use the face, hair or age of the person in the second image."
        ) + (f" Outfit notes: {roupa_en}." if roupa_en else "")
    elif vista == "frente" and roupa_en:
        pedido = PEDIDOS[vista] + (
            " Keep the same person: face, identity, skin, hair and body proportions."
            f" Replace all of the clothing with {roupa_en}: every garment, color and shoe exactly as described."
            " Nothing from the current clothing remains."
        )
    else:
        pedido = PEDIDOS[vista] + " Preserve the exact character identity, proportions, hair, clothing, colors and visual style."
    pedido += REALISMO + (CABELO if vista in ("perfil", "costas") else "")
    pedido += " Plain light gray studio background, even lighting, no text. Only one character and one view."
    if n_fontes > 1 and not troca_foto:
        pedido += (" The first image is the approved outfit and body framing: copy every garment exactly from it."
                   " The second is the original character: use it only for the face, identity and hair, never for the clothing.")
    if descricao:
        pedido += f" Character details: {descricao}"
    return pedido


def gerar_vista(pasta, vista, descricao, roupa=""):
    from comfy_api import rodar
    import texto_para_imagem as t2i

    base = pasta / "frente.png"
    destino = pasta / ARQUIVOS[vista]
    if vista == "rosto" and recortar_rosto(base, destino):
        return
    referencia = pasta / (ROUPA if vista == "frente" else ARQUIVOS["frente"])
    # Fora da frente, a frente aprovada vem primeiro (roupa e corpo) e a foto original só dá o rosto. Com a original na frente,
    # o rosto e o perfil vestiam metade da roupa dela (a camiseta por baixo do cardigã aprovado, 21/11)
    corpo = vista == "frente" and (pasta / CORPO).is_file()
    if corpo:
        fontes = [pasta / CORPO, base] + ([referencia] if referencia.is_file() else [])
    elif vista == "frente":
        fontes = [base] + ([referencia] if referencia.is_file() else [])
    else:
        fontes = [referencia, base] if referencia.is_file() else [base]
    por_vista = f"personagem_{pasta.name}_ficha_{vista}"
    # As copias vao para os temporarios do personagem (entrada_temp); o grafo recebe o nome com a subpasta
    dono = entrada_temp.dono_personagem(pasta.name)
    copias, nomes = zip(*(entrada_temp.arquivo(dono, f"{por_vista}_{i}.png") for i in range(len(fontes))))
    modelo = t2i.MODELOS_TEXTO["klein_edit"]
    try:
        for fonte, copia in zip(fontes, copias):
            shutil.copyfile(fonte, copia)
        roupa_en = ""
        if vista == "frente" and str(roupa or "").strip():
            import personagens
            roupa_en = personagens.traduzir_roupa(roupa, nomes[0])[0]
        pedido = pedido_vista(vista, len(fontes), descricao, roupa_en, corpo)
        p = {"partida": nomes[0], "referencias": list(nomes[1:]), "prompt": pedido, "passos": modelo["passos"]}
        tamanho = (1024, 1024) if vista in ("rosto", "perfil") else (896, 1344)
        r = rodar(t2i.grafo_edicao_klein(p, modelo, secrets.randbits(31), f"personagens/{por_vista}", tamanho_saida=tamanho), 1800)
        if r["status"] != "success":
            raise RuntimeError(f"o Klein não gerou a vista {vista} ({r['status']} {str(r.get('erro', ''))[:300]})")
        imagens = (r["saidas"].get("9") or {}).get("images", [])
        if not imagens:
            raise RuntimeError(f"o ComfyUI não devolveu a vista {vista}")
        img = imagens[0]
        copiar(config.SAIDA / img.get("subfolder", "") / img["filename"], destino)
    finally:
        for copia in copias:
            copia.unlink(missing_ok=True)


FOLHA_H3 = "ficha_h3.png"
NO_FIZGIG = "ComfyUI-Fizgig-H3-Still"
TAMANHO_H3 = (4096, 1536)
# Receita do tutorial da Earngenix (fluxo padrão): ref2va sem a Turbo e sem desvio de sigma, er_sde/beta 18 passos, um quadro só
# pelo nó Fizgig. O JSON deles dá 404; o pedido foi refeito pela descrição da página. Teste de 21/11: 409 s, pico de 9,5 GB,
# rosto com ~1100 px (projetos/teste_ficha_h3). A frente aprovada como 2ª referência impede o corpo da foto da roupa de vazar.
PASSOS_H3, AMOSTRADOR_H3, AGENDADOR_H3 = 18, "er_sde", "beta"
PEDIDO_H3 = (
    "<CHARACTER> is the person from <Picture 1> and <Picture 2>. Keep the exact face, eyes, skin tone and natural unretouched skin"
    " from the close-up <Picture 1>, and the exact hair, body proportions and complete outfit from the full-body <Picture 2>.\n"
    "A professional photographic character reference sheet of <CHARACTER> on a plain seamless white studio background, soft even"
    " studio lighting, real photo, natural skin and fabric texture, sharp focus, no text. Six panels in total.\n"
    "1. <CHARACTER> On the left: one large close-up portrait of head and chest, facing the camera, neutral relaxed expression.\n"
    "2. <CHARACTER> In the center: full body view from 3 different angles side by side, head to shoes, standing straight with arms"
    " relaxed: front, side, back.\n"
    "3. <CHARACTER> On the right: 2 large head-and-chest portraits stacked vertically: top a side profile, bottom a three-quarter view.\n"
    "The same person, same face, same hair and same outfit in every view, completely still.{detalhes}\n"
    "Negative: cartoon, anime, illustration, 3d render, painting, makeup, beauty filter, plastic skin, different face,"
    " different outfit, text, watermark, extra people."
)


def faltam_h3():
    """O que falta no ComfyUI para a ficha pelo H3: os arquivos do ref2va e o nó Fizgig."""
    import video_avancado
    no = config.RAIZ_COMFY / "ComfyUI" / "custom_nodes" / NO_FIZGIG
    return [n for n in video_avancado.faltam() if n != video_avancado.TURBO] + ([] if no.is_dir() else [NO_FIZGIG])


def grafo_h3(rosto, corpo, descricao, prefixo, semente):
    import imagem_para_video as ipv
    import video_avancado as va
    detalhes = f" Character details: {descricao}" if descricao else ""
    g = ipv.grafo_referencia({"proporcao": "16:9 (Widescreen)", "megapixels": 1.0}, 1, PEDIDO_H3.format(detalhes=detalhes),
                             prefixo, semente, va.MODELO, [], "max")
    largura, altura = TAMANHO_H3
    g["20"]["inputs"].update(width=largura, height=altura, length=5)
    del g["11"]
    g["12"]["inputs"]["model"] = ["10", 0]
    g["21"]["inputs"].update(steps=PASSOS_H3, sampler_name=AMOSTRADOR_H3, scheduler=AGENDADOR_H3)
    for i, nome in enumerate((rosto, corpo)):
        g[f"10{i}"] = {"class_type": "LoadImage", "inputs": {"image": nome}}
        g["20"]["inputs"][f"ref_images.ref_image_{i}"] = [f"10{i}", 0]
    for no in ("22", "23", "24", "25", "26"):
        del g[no]
    g["40"] = {"class_type": "FizgigH3StillLatent", "inputs": {"width": largura, "height": altura, "batch_size": 1}}
    g["21"]["inputs"]["latent_image"] = ["40", 0]
    g["41"] = {"class_type": "FizgigH3StillDecode", "inputs": {"samples": ["21", 0], "vae": ["15", 0]}}
    g["9"] = {"class_type": "SaveImage", "inputs": {"images": ["41", 0], "filename_prefix": prefixo}}
    return g


def gerar_h3(pasta, descricao):
    """A ficha de 6 vistas numa imagem só, pelo H3. O rosto vem do recorte da foto original (ou do close do Klein, ou da
    foto inteira, nessa ordem) e o corpo e a roupa da frente aprovada."""
    from comfy_api import rodar
    por = f"personagem_{pasta.name}_ficha_h3"
    dono = entrada_temp.dono_personagem(pasta.name)
    (rosto, nome_rosto), (corpo, nome_corpo) = entrada_temp.arquivo(dono, f"{por}_rosto.png"), entrada_temp.arquivo(dono, f"{por}_corpo.png")
    try:
        if not recortar_rosto(pasta / "frente.png", rosto):
            copiar(pasta / (ARQUIVOS["rosto"] if (pasta / ARQUIVOS["rosto"]).is_file() else "frente.png"), rosto)
        shutil.copyfile(pasta / ARQUIVOS["frente"], corpo)
        r = rodar(grafo_h3(nome_rosto, nome_corpo, descricao, f"personagens/{por}", secrets.randbits(48)), 3600)
        if r["status"] != "success":
            raise RuntimeError(f"o H3 não gerou a ficha ({r['status']} {str(r.get('erro', ''))[:300]})")
        imagens = (r["saidas"].get("9") or {}).get("images", [])
        if not imagens:
            raise RuntimeError("o ComfyUI não devolveu a ficha do H3")
        img = imagens[0]
        copiar(config.SAIDA / img.get("subfolder", "") / img["filename"], pasta / FOLHA_H3)
    finally:
        rosto.unlink(missing_ok=True)
        corpo.unlink(missing_ok=True)


# Apagar por partes: "h3" é só a ficha de 6 vistas; "ficha" é a ficha 2x2 com o rosto, o perfil e as costas gerados e a
# aprovação da frente (a frente, a referência da roupa e a do corpo ficam, para aprovar e gerar de novo)
PARTES = {"h3": (FOLHA_H3,), "ficha": (FOLHA, ARQUIVOS["rosto"], ARQUIVOS["perfil"], ARQUIVOS["costas"], APROVACAO)}


def apagar_parte(pasta, parte):
    for nome in PARTES[parte]:
        (pasta / nome).unlink(missing_ok=True)


def gerar(pasta, etapa, descricao, roupa=""):
    marcas, aprovada = estado(pasta)
    if etapa == "h3":
        if not aprovada:
            raise ValueError("Aprove a frente de corpo inteiro primeiro.")
        print("Gerando ficha de 6 vistas pelo H3", flush=True)
        gerar_h3(pasta, descricao)
        return
    if etapa in ("aprovar", "completar"):
        if "frente" not in marcas or (etapa == "completar" and not aprovada):
            raise ValueError("Prepare e aprove a frente de corpo inteiro primeiro.")
        if etapa == "aprovar":
            (pasta / APROVACAO).write_text(marcas["frente"])
        vistas = [v for v in VISTAS if v not in marcas]
    else:
        if etapa != "frente" and not aprovada:
            raise ValueError("Aprove a frente de corpo inteiro primeiro.")
        vistas = [etapa]
    for v in vistas:
        print(f"Gerando vista {v}", flush=True)
        gerar_vista(pasta, v, descricao, roupa)
    montar(pasta)
