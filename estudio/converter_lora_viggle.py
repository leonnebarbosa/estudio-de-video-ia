"""Converte uma LoRA do Viggle Remake (nomes diffusers, como vem no WanGP) para os nomes que o ComfyUI aceita no H3.
Chamado pelo troca_viggle.preparar quando a LoRA convertida ainda nao existe; roda so na CPU (cerca de 1 minuto, ~7 GB de RAM).

Segue o que o WanGP faz ao carregar (models/minimax_h3/transformer.py, preprocess_loras):
- transformer_blocks. -> blocks. ; proj_in -> video_patch_proj ; proj_out -> final_layer.video_out
- attn.to_out.0 -> attn.out_proj ; ff.net.0.proj -> mlp.fc1 ; ff.net.2 -> mlp.fc2
- o lora_B do ff.net.0.proj tem as duas metades trocadas (SwiGLU)
- to_q / to_k / to_v viram um qkv_proj so: os A empilhados (posto 3r) e os B em blocos na diagonal, na ordem agrupada q, k, v

Confere cada destino com o cabecalho do modelo base (nome e formato) antes de gravar. Nao sobrescreve arquivo existente.
Uso: python -I converter_lora_viggle.py <lora de origem> <modelo base .safetensors> <arquivo de saida>"""
import json, os, re, struct, sys
from pathlib import Path

RENOMES = (("transformer_blocks.", "blocks."), ("proj_in.", "video_patch_proj."), ("proj_out.", "final_layer.video_out."))
MEIO = ((".attn.to_out.0.", ".attn.out_proj."), (".attn.to_q.", ".attn.q_proj."), (".attn.to_k.", ".attn.k_proj."),
        (".attn.to_v.", ".attn.v_proj."), (".ff.net.0.proj.", ".mlp.fc1."), (".ff.net.2.", ".mlp.fc2."))


class NaoConverte(Exception):
    pass


def formas_do_modelo(arquivo):
    """{modulo: formato do peso} lido so do cabecalho do safetensors do modelo base."""
    with open(arquivo, "rb") as f:
        n = struct.unpack("<Q", f.read(8))[0]
        cab = json.loads(f.read(n))
    cab.pop("__metadata__", None)
    return {re.sub(r"^(model\.)?diffusion_model\.", "", k)[:-len(".weight")]: v["shape"] for k, v in cab.items() if k.endswith(".weight")}


def nome_no_comfy(chave):
    """('blocks.3.mlp.fc1', 'lora_B', True) para 'transformer_blocks.3.ff.net.0.proj.lora_B.weight'; o ultimo diz se e o fc1."""
    k = re.sub(r"^(transformer\.|diffusion_model\.)", "", chave)
    m = re.match(r"(.+)\.(lora_A|lora_B)(?:\.default)?\.weight$", k)
    if not m:
        raise NaoConverte(f"chave que não sei converter: {chave}")
    modulo, lado = m.group(1) + ".", m.group(2)
    fc1 = ".ff.net.0.proj." in modulo
    for de, para in RENOMES:
        if modulo.startswith(de):
            modulo = para + modulo[len(de):]
            break
    for de, para in MEIO:
        modulo = modulo.replace(de, para)
    return modulo[:-1], lado, fc1


def converter(origem, base, saida):
    """Grava `saida` e devolve quantos modulos foram convertidos. Levanta NaoConverte se algo nao conferir."""
    import torch
    from safetensors import safe_open
    from safetensors.torch import save_file

    origem, base, saida = Path(origem), Path(base), Path(saida)
    if saida.exists():
        raise NaoConverte(f"{saida} já existe; não sobrescrevo")
    formas = formas_do_modelo(base)
    novo = {}
    with safe_open(str(origem), framework="pt") as f:
        for chave in f.keys():
            if chave.endswith(".alpha"):
                raise NaoConverte("a LoRA tem chaves alpha; este conversor só trata escala 1")
            modulo, lado, fc1 = nome_no_comfy(chave)
            t = f.get_tensor(chave)
            if fc1 and lado == "lora_B":
                t = torch.cat(t.chunk(2, dim=0)[::-1], dim=0).contiguous()
            novo[f"{modulo}.{lado}.weight"] = t

    # q, k, v separados -> um qkv_proj (ordem agrupada: as linhas de q, depois k, depois v)
    for chave in [c for c in novo if c.endswith(".attn.q_proj.lora_A.weight")]:
        pre = chave[:-len("q_proj.lora_A.weight")]
        A = [novo.pop(f"{pre}{p}_proj.lora_A.weight") for p in "qkv"]
        B = [novo.pop(f"{pre}{p}_proj.lora_B.weight") for p in "qkv"]
        novo[f"{pre}qkv_proj.lora_A.weight"] = torch.cat(A).contiguous()
        novo[f"{pre}qkv_proj.lora_B.weight"] = torch.block_diag(*(b.float() for b in B)).to(B[0].dtype).contiguous()

    modulos = sorted(c[:-len(".lora_A.weight")] for c in novo if c.endswith(".lora_A.weight"))
    erros = []
    for modulo in modulos:
        a, b = novo[modulo + ".lora_A.weight"], novo[modulo + ".lora_B.weight"]
        alvo = formas.get(modulo)
        if alvo is None:
            erros.append(f"{modulo}: não existe no modelo base")
        elif [b.shape[0], a.shape[1]] != list(alvo[:2]) or a.shape[0] != b.shape[1]:
            erros.append(f"{modulo}: LoRA {list(b.shape)} x {list(a.shape)} contra o peso {alvo}")
    if erros or not modulos:
        raise NaoConverte(f"{len(erros)} destinos não conferem com o modelo base: " + "; ".join(erros[:5]))
    # Grava com outro nome e so troca no fim: um arquivo pela metade nunca fica com o nome final
    parcial = saida.with_name(saida.name + ".parcial")
    save_file(novo, str(parcial), metadata={"origem": origem.name, "convertido_por": "estudio converter_lora_viggle.py", "formato": "comfyui minimax_h3 qkv agrupado"})
    os.replace(parcial, saida)
    return len(modulos)


if __name__ == "__main__":
    try:
        print(f"{converter(*sys.argv[1:4])} módulos convertidos e conferidos com o modelo base")
    except NaoConverte as e:
        sys.exit(str(e))
