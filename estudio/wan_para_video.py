"""Imagem para video com o Wan 2.2 I2V 14B: um video curto e sem som a partir de uma imagem e um texto.

Uso: python -I wan_para_video.py --projeto NOME
Le projetos/NOME/interface.json (prompt, modelo, duracao, formato, resolucao, semente) e a imagem de estado.json, e grava
final.mp4 na pasta do projeto, mais estado.json, progresso.json e gpu.csv.
Modelo oficial, com 4 passos (2 no High + 2 no Low), CFG 1 e euler/simple, medido em 09/11/2026 na 3080:
- wan22: Wan 2.2 em GGUF Q4_K_M com a LoRA lightx2v de 4 passos, shift 8. 290 s em 576x864 e 5 s.
Modelos da comunidade (com a aceleracao embutida: lora None) entram pelo arquivo local, fora do git (ver extras.py).
Codigos de saida: 0 ok, 3 servidor caiu, 4 falha da geracao, 5 temperatura.
"""
import argparse, json, os, random, shutil, sys, time
from pathlib import Path

# Com python -I a pasta do script nao entra no caminho de importacao
sys.path.insert(0, str(Path(__file__).resolve().parent))
import config, extras, loras
from continuar_video import Monitor, rodar
from detalhe_comfy import Detalhe
from trocar_personagem import acompanhar, arquivo_de_saida

FPS_WAN = 16
ENCODER = "umt5_xxl_fp8_e4m3fn_scaled.safetensors"
VAE = "wan_2.1_vae.safetensors"
AMOSTRADORES = ("60", "61")
# alta e baixa: o modelo de cada metade dos passos; lora: a aceleracao (None quando ja vem no modelo)
MODELOS_WAN = {
    "wan22": {"nome": "Wan 2.2 GGUF + lightx2v", "carregador": "UnetLoaderGGUF", "shift": 8,
              "alta": "Wan2.2-I2V-A14B-HighNoise-Q4_K_M.gguf", "baixa": "Wan2.2-I2V-A14B-LowNoise-Q4_K_M.gguf",
              "lora": ("wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors", "wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors")},
}
MODELOS_WAN.update(extras.secao("wan"))


def quadros_wan(segundos):
    """O Wan so aceita 4k+1 quadros: 2 s = 33, 3 s = 49, 4 s = 65, 5 s = 81."""
    return round(segundos * FPS_WAN / 4) * 4 + 1


def tamanho_wan(proporcao, megapixels):
    """Largura e altura em multiplos de 16, como o Wan pede."""
    w, h = (int(x) for x in proporcao.split(" ")[0].split(":"))
    escala = (megapixels * 1024 * 1024 / (w * h)) ** 0.5
    return round(w * escala / 16) * 16, round(h * escala / 16) * 16


def arquivos_que_faltam(modelo):
    """Os arquivos do modelo que nao estao na pasta de modelos do ComfyUI."""
    m = MODELOS_WAN[modelo]
    pastas = [config.MODELOS / "diffusion_models", config.MODELOS / "unet"]
    precisa = [(pastas, m["alta"]), (pastas, m["baixa"]), ([config.MODELOS / "text_encoders", config.MODELOS / "clip"], ENCODER), ([config.MODELOS / "vae"], VAE)]
    instaladas = loras.mapa()  # a LoRA pode estar em qualquer subpasta de loras
    return [nome for lugares, nome in precisa if not any((p / nome).is_file() for p in lugares)] + [n for n in (m["lora"] or ()) if n.lower() not in instaladas]


def baixa_de(alta):
    """A metade Low do par de LoRAs de estilo cuja metade High e `alta`, ou None se ela nao estiver na pasta loras."""
    return next((x["baixa"] for x in loras.pares_wan(loras.mapa().values()) if x["alta"].lower() == alta.lower()), None)


def grafo(p, imagem, semente, prefixo):
    """`p["loras"]`, opcional: LoRAs de estilo [alta, baixa, forca], encadeadas depois da aceleracao (nos 13x e 23x)."""
    m = MODELOS_WAN[p["modelo"]]
    largura, altura = tamanho_wan(p["proporcao"], p["megapixels"])
    g = {
        "30": {"class_type": "CLIPLoader", "inputs": {"clip_name": ENCODER, "type": "wan", "device": "default"}},
        "31": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["30", 0], "text": p["prompt"]}},
        "32": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["30", 0], "text": p["negativo"]}},
        "40": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
        "50": {"class_type": "LoadImage", "inputs": {"image": imagem}},
        "51": {"class_type": "WanImageToVideo", "inputs": {"positive": ["31", 0], "negative": ["32", 0], "vae": ["40", 0], "width": largura, "height": altura,
                                                           "length": quadros_wan(p["duracao"]), "batch_size": 1, "start_image": ["50", 0]}},
        "70": {"class_type": "VAEDecode", "inputs": {"samples": ["61", 0], "vae": ["40", 0]}},
        "71": {"class_type": "CreateVideo", "inputs": {"images": ["70", 0], "fps": FPS_WAN}},
        "72": {"class_type": "SaveVideo", "inputs": {"video": ["71", 0], "filename_prefix": prefixo, "format": "auto", "codec": "auto"}},
    }
    for i, (carregar, lora, amostra, metade) in enumerate((("10", "11", "12", "alta"), ("20", "21", "22", "baixa"))):
        extra = {"weight_dtype": "default"} if m["carregador"] == "UNETLoader" else {}
        g[carregar] = {"class_type": m["carregador"], "inputs": {"unet_name": m[metade], **extra}}
        entrada = [carregar, 0]
        if m["lora"]:
            g[lora] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": entrada, "lora_name": m["lora"][i], "strength_model": 1.0}}
            entrada = [lora, 0]
        for j, (alta, baixa, forca) in enumerate(p.get("loras") or []):
            no = f"{carregar[0]}3{j}"
            g[no] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": entrada, "lora_name": (alta, baixa)[i], "strength_model": forca}}
            entrada = [no, 0]
        g[amostra] = {"class_type": "ModelSamplingSD3", "inputs": {"model": entrada, "shift": m["shift"]}}
    comum = {"noise_seed": semente, "steps": 4, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple", "positive": ["51", 0], "negative": ["51", 1]}
    g["60"] = {"class_type": "KSamplerAdvanced", "inputs": {**comum, "model": ["12", 0], "add_noise": "enable", "latent_image": ["51", 2],
                                                            "start_at_step": 0, "end_at_step": 2, "return_with_leftover_noise": "enable"}}
    g["61"] = {"class_type": "KSamplerAdvanced", "inputs": {**comum, "model": ["22", 0], "add_noise": "disable", "latent_image": ["60", 0],
                                                            "start_at_step": 2, "end_at_step": 4, "return_with_leftover_noise": "disable"}}
    return g


class Progresso:
    """Fase e passo atuais em progresso.json, que a pagina le enquanto a geracao roda. Os 4 passos sao 2 no modelo
    High (no 60) e 2 no Low (no 61); a pagina recebe o passo somado, de 0 a 4."""

    def __init__(self, arquivo, monitor, g):
        self.arquivo, self.monitor = arquivo, monitor
        self.inicio = time.time()
        self.valor, self.maximo, self.metade = 0, 4, "alta"
        self.detalhe = Detalhe(monitor, g, inicio=self.inicio)

    def gravar(self):
        dados = {"valor": self.valor, "maximo": self.maximo, "metade": self.metade, **self.detalhe.dados()}
        temporario = self.arquivo.with_name(self.arquivo.name + ".tmp")
        try:
            temporario.write_text(json.dumps(dados), encoding="utf-8")
            os.replace(temporario, self.arquivo)
        except OSError:
            # A pagina pode estar lendo o arquivo neste instante; a proxima gravacao resolve
            pass

    def evento(self, m):
        if m.get("type") != "progress_state":
            return
        nos = (m.get("data") or {}).get("nodes") or {}
        rodando = self.detalhe.evento(nos)
        for i, no in enumerate(AMOSTRADORES):
            n = nos.get(no)
            if n and n.get("state") == "running" and n.get("max", 0) > 0:
                # O KSamplerAdvanced informa os passos da sua metade: 0 a 2
                self.metade = ("alta", "baixa")[i]
                self.valor = min(4, i * 2 + round(n.get("value", 0)))
        if rodando:
            self.gravar()


def gravar_json(arquivo, dados):
    import caminhos
    caminhos.gravar_json(arquivo, dados)   # resiste a uma queda do PC (fsync antes de trocar)


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--projeto", required=True)
    a = a.parse_args()
    pasta = config.PROJETOS / a.projeto
    p = json.loads((pasta / "interface.json").read_text(encoding="utf-8"))
    arq_estado = pasta / "estado.json"
    estado = json.loads(arq_estado.read_text(encoding="utf-8"))
    if (pasta / "final.mp4").exists() and estado.get("resultado"):
        print("o video ja esta pronto", flush=True)
        return
    faltam = arquivos_que_faltam(p["modelo"])
    if faltam:
        print(f"FALHA na geracao: faltam arquivos do modelo no ComfyUI: {', '.join(faltam)}", flush=True)
        sys.exit(4)

    semente = random.randrange(2**48) if p["semente"] is None else p["semente"]
    g = grafo(p, estado["personagem"], semente, f"wan/{a.projeto}/video")
    mon = Monitor(pasta / "gpu.csv")
    mon.start()
    progresso = Progresso(pasta / "progresso.json", mon, g)
    progresso.gravar()
    acompanhar(progresso)

    def sair(codigo, mensagem):
        mon.fim.set()
        print(mensagem, flush=True)
        sys.exit(codigo)

    largura, altura = tamanho_wan(p["proporcao"], p["megapixels"])
    print(f"{MODELOS_WAN[p['modelo']]['nome']} | {largura}x{altura} | {quadros_wan(p['duracao'])} quadros a {FPS_WAN} fps | semente {semente}", flush=True)
    r = rodar(g, 1800)
    if mon.quente:
        sair(5, "PARADO por temperatura")
    if r["status"] == "servidor caiu":
        sair(3, f"SERVIDOR CAIU: {r['erro'][:300]}")
    if r["status"] != "success":
        sair(4, f"FALHA na geracao: {r['status']} {r['erro'][:700]}")
    video = arquivo_de_saida(r["saidas"].get("72") or {})
    if video is None or not video.is_file():
        sair(4, f"FALHA na geracao: o ComfyUI nao informou o video. Saidas: {list(r['saidas'])}")
    shutil.copy2(video, pasta / "final.mp4")
    estado["resultado"] = {"semente": semente, "segundos": round(r["segundos"]), "pico_vram": r["pico_vram"], "temp_max": r["temp_max"], "largura": largura, "altura": altura}
    gravar_json(arq_estado, estado)
    mon.fim.set()
    print(f"pronto: {round(r['segundos'])} s | pico {r['pico_vram']} MiB | {r['temp_max']} C | {pasta / 'final.mp4'}", flush=True)


if __name__ == "__main__":
    main()
