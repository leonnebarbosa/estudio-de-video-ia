"""Prepara vistas independentes e monta a ficha sem uma nova geração."""
import secrets
import shutil

from PIL import Image, ImageOps

import config

FOLHA = "ficha.png"
VISTAS = ("rosto", "perfil", "frente", "costas")
ARQUIVOS = {vista: f"ficha_{vista}.png" for vista in VISTAS}
APROVACAO = "ficha_frente.ok"
ROUPA = "ficha_roupa.png"
TAMANHO_FOLHA = (1536, 1280)
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
    fundo = "#e5e3df"
    folha = Image.new("RGB", TAMANHO_FOLHA, fundo)
    posicoes = ((20, 20, 738, 470), (778, 20, 738, 470), (20, 510, 738, 750), (778, 510, 738, 750))
    for v, (x, y, w, h) in zip(VISTAS, posicoes):
        with Image.open(pasta / ARQUIVOS[v]) as im:
            painel = ImageOps.contain(im, (w, h), Image.Resampling.LANCZOS)
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


def gerar_vista(pasta, vista, descricao):
    from comfy_api import rodar
    import texto_para_imagem as t2i

    base = pasta / "frente.png"
    destino = pasta / ARQUIVOS[vista]
    if vista == "rosto" and recortar_rosto(base, destino):
        return
    referencia = pasta / (ROUPA if vista == "frente" else ARQUIVOS["frente"])
    fontes = [base] if vista != "costas" else [referencia, base]
    if vista != "costas" and referencia.is_file():
        fontes.append(referencia)
    por_vista = f"personagem_{pasta.name}_ficha_{vista}"
    copias = [config.ENTRADA / f"{por_vista}_{i}.png" for i in range(len(fontes))]
    pedido = PEDIDOS[vista] + (
        " Preserve the exact character identity, proportions, hair, clothing, colors and visual style. "
        "Plain light gray studio background, even lighting, no text. Only one character and one view."
    )
    if len(fontes) > 1:
        pedido += (" The first image is the approved outfit and body framing; the second is the original character."
                   if vista == "costas" else " Use the first image for identity and the second for the outfit.")
    if descricao:
        pedido += f" Character details: {descricao}"
    modelo = t2i.MODELOS_TEXTO["klein_edit"]
    try:
        for fonte, copia in zip(fontes, copias):
            shutil.copyfile(fonte, copia)
        p = {"partida": copias[0].name, "prompt": pedido, "passos": modelo["passos"]}
        if len(copias) > 1:
            p["referencia"] = copias[1].name
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


def gerar(pasta, etapa, descricao):
    marcas, aprovada = estado(pasta)
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
        gerar_vista(pasta, v, descricao)
    montar(pasta)
