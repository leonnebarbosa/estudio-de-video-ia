"""Passa os arquivos do Qwen Image 2.1 que vieram com o WanGP para o formato que o ComfyUI le, sem baixar nada.

- VAE: o do WanGP usa os nomes do diffusers (AutoencoderKLQwenImage21); o ComfyUI espera o desenho do Wan 2.2
  (comfy/sd.py reconhece por "decoder.middle.0.residual.0.gamma"). Sao as mesmas 238 pecas com outros nomes; as convolucoes
  2D ganham o eixo do tempo (tamanho 1). Confere com o modelo do proprio ComfyUI quando ele esta disponivel.
- Codificador de texto Qwen3-VL-8B: muda so o prefixo das chaves ("language_model." -> "model.language_model.",
  "visual." -> "model.visual."), que e como o comfy/sd.py o reconhece. Reescreve so o cabecalho e copia os dados.

Nao sobrescreve arquivo existente.
Uso: python -I converter_qwen21.py vae <origem> <saida>
     python -I converter_qwen21.py codificador <origem> <saida>"""
import json, os, re, struct, sys
from pathlib import Path

RESNET = {"norm1.gamma": "residual.0.gamma", "conv1.weight": "residual.2.weight", "conv1.bias": "residual.2.bias",
          "norm2.gamma": "residual.3.gamma", "conv2.weight": "residual.6.weight", "conv2.bias": "residual.6.bias",
          "conv_shortcut.weight": "shortcut.weight", "conv_shortcut.bias": "shortcut.bias"}
BLOCOS = {"encoder": ("down_blocks", "downsamples", "downsampler"), "decoder": ("up_blocks", "upsamples", "upsampler")}


class NaoConverte(Exception):
    pass


def ler_cabecalho(arquivo):
    """(cabecalho como dicionario, onde os dados comecam no arquivo)."""
    with open(arquivo, "rb") as f:
        n = struct.unpack("<Q", f.read(8))[0]
        return json.loads(f.read(n)), 8 + n


def nome_vae(chave, resnets):
    """A chave do diffusers -> a do desenho Wan 2.2. `resnets`: {("encoder", 0): 2, ...}, quantos resnets cada bloco tem
    (o reamostrador vem logo depois deles na lista do bloco)."""
    if chave.startswith("quant_conv."):
        return "conv1." + chave.split(".", 1)[1]
    if chave.startswith("post_quant_conv."):
        return "conv2." + chave.split(".", 1)[1]
    lado, resto = chave.split(".", 1)
    if lado not in BLOCOS:
        raise NaoConverte(f"chave que não sei converter: {chave}")
    de, para, reamostrador = BLOCOS[lado]
    if resto.startswith("conv_in."):
        return f"{lado}.conv1.{resto[8:]}"
    if resto.startswith("conv_out."):
        return f"{lado}.head.2.{resto[9:]}"
    if resto == "norm_out.gamma":
        return f"{lado}.head.0.gamma"
    m = re.match(r"mid_block\.resnets\.(\d)\.(.+)$", resto)
    if m and m.group(2) in RESNET:
        return f"{lado}.middle.{int(m.group(1)) * 2}.{RESNET[m.group(2)]}"
    m = re.match(r"mid_block\.attentions\.0\.(.+)$", resto)
    if m:
        return f"{lado}.middle.1.{m.group(1)}"
    m = re.match(rf"{de}\.(\d+)\.resnets\.(\d+)\.(.+)$", resto)
    if m and m.group(3) in RESNET:
        return f"{lado}.{para}.{m.group(1)}.{para}.{m.group(2)}.{RESNET[m.group(3)]}"
    m = re.match(rf"{de}\.(\d+)\.{reamostrador}\.(.+)$", resto)
    if m:
        return f"{lado}.{para}.{m.group(1)}.{para}.{resnets[(lado, int(m.group(1)))]}.{m.group(2)}"
    raise NaoConverte(f"chave que não sei converter: {chave}")


def formas_do_comfy(cab):
    """As chaves e os formatos que o VAE do ComfyUI espera, montando o modelo dele. None fora do ComfyUI (nos testes)."""
    try:
        import comfy.ldm.wan.vae2_2 as wan
    except ImportError:
        return None
    f = {k: v["shape"] for k, v in cab.items()}
    modelo = wan.WanVAE(dim=f["encoder.conv_in.weight"][0], dec_dim=f["decoder.conv_out.weight"][1], z_dim=64, dim_mult=[1, 2, 4, 8, 8],
                        num_res_blocks=2, attn_scales=[], temperal_downsample=[False, True, True, True], dropout=0.0,
                        image_channels=f["decoder.conv_out.weight"][0], patch_size=1, temporal_kernel=1)
    return {k: tuple(t.shape) for k, t in modelo.state_dict().items()}


def converter_vae(origem, saida, formas=None):
    """Grava `saida` com os nomes do ComfyUI e devolve quantas pecas foram. `formas`: {chave: formato} esperado; sem ele,
    usa o modelo do ComfyUI (formas_do_comfy) e, se nem isso houver, converte so os nomes e poe o eixo do tempo."""
    import torch
    from safetensors import safe_open
    from safetensors.torch import save_file

    origem, saida = Path(origem), Path(saida)
    if saida.exists():
        raise NaoConverte(f"{saida} já existe; não sobrescrevo")
    cab, _ = ler_cabecalho(origem)
    cab.pop("__metadata__", None)
    resnets = {}
    for chave in cab:
        m = re.match(r"(encoder|decoder)\.(?:down|up)_blocks\.(\d+)\.resnets\.(\d+)\.", chave)
        if m:
            bloco = (m.group(1), int(m.group(2)))
            resnets[bloco] = max(resnets.get(bloco, 0), int(m.group(3)) + 1)
    formas = formas if formas is not None else formas_do_comfy(cab)
    novo, erros = {}, []
    with safe_open(str(origem), framework="pt") as f:
        for chave in cab:
            alvo = nome_vae(chave, resnets)
            t = f.get_tensor(chave)
            if formas is None:
                # Sem o modelo para conferir: as convolucoes 2D viram 3D com o tempo de tamanho 1
                if t.ndim == 4 and alvo.endswith(".weight") and ".to_qkv." not in alvo and ".proj." not in alvo:
                    t = t.unsqueeze(2)
            elif alvo not in formas:
                erros.append(f"{alvo} (de {chave}): o ComfyUI não tem esta peça")
                continue
            elif t.numel() != torch.Size(formas[alvo]).numel():
                erros.append(f"{alvo}: {tuple(t.shape)} contra {formas[alvo]}")
                continue
            else:
                t = t.reshape(formas[alvo])
            novo[alvo] = t.contiguous()
    if formas is not None:
        erros += [f"{k}: faltou na origem" for k in formas if k not in novo]
    if erros:
        raise NaoConverte(f"{len(erros)} peças do VAE não conferem: " + "; ".join(erros[:6]))
    parcial = saida.with_name(saida.name + ".parcial")
    save_file(novo, str(parcial), metadata={"origem": origem.name, "convertido_por": "estudio converter_qwen21.py", "formato": "comfyui wan2.2 vae"})
    os.replace(parcial, saida)
    return len(novo)


def nome_codificador(chave):
    if chave.startswith(("language_model.", "visual.")):
        return "model." + chave
    return chave


def converter_codificador(origem, saida, bloco=64 * 2**20):
    """Reescreve so o cabecalho com as chaves prefixadas e copia os dados como estao. Devolve quantas chaves mudaram."""
    origem, saida = Path(origem), Path(saida)
    if saida.exists():
        raise NaoConverte(f"{saida} já existe; não sobrescrevo")
    cab, inicio = ler_cabecalho(origem)
    novo, mudadas = {}, 0
    for chave, valor in cab.items():
        alvo = chave if chave == "__metadata__" else nome_codificador(chave)
        mudadas += alvo != chave
        if alvo in novo:
            raise NaoConverte(f"duas chaves viram {alvo}")
        novo[alvo] = valor
    if not mudadas:
        raise NaoConverte("nenhuma chave com os prefixos language_model. ou visual.: o arquivo não é o codificador esperado")
    texto = json.dumps(novo, separators=(",", ":")).encode("utf-8")
    texto += b" " * (-len(texto) % 8)  # o safetensors alinha o comeco dos dados em 8 bytes
    parcial = saida.with_name(saida.name + ".parcial")
    with open(origem, "rb") as entrada, open(parcial, "wb") as f:
        f.write(struct.pack("<Q", len(texto)))
        f.write(texto)
        entrada.seek(inicio)
        while True:
            pedaco = entrada.read(bloco)
            if not pedaco:
                break
            f.write(pedaco)
    os.replace(parcial, saida)
    return mudadas


if __name__ == "__main__":
    try:
        if sys.argv[1] == "vae":
            print(f"VAE: {converter_vae(sys.argv[2], sys.argv[3])} peças convertidas")
        elif sys.argv[1] == "codificador":
            print(f"codificador: {converter_codificador(sys.argv[2], sys.argv[3])} chaves com o prefixo novo")
        else:
            sys.exit(__doc__)
    except NaoConverte as e:
        sys.exit(str(e))
