"""O que se pergunta ao ComfyUI: se esta ligado e o que esta instalado."""
import json, re, threading, time, urllib.request
from pathlib import Path

import config
from loras import nomes_unicos, pares_wan


SAMPLERS = ["er_sde", "euler", "res_multistep", "dpmpp_2m", "uni_pc"]
AGENDADORES = ["beta", "simple", "normal", "sgm_uniform", "karras"]
SO_FLUXO_LORA = re.compile(r"minimax[_-]?h3|mmh3|^h3_", re.I)
FORA_LORA = re.compile(r"(?!)", re.I)
# Modelos H3 de referencia (o tipo ref2va): os com "ref2va" no nome e os H3 da comunidade que nao o dizem
# (com h3 entre separadores no nome). O fl2va fica de fora: so serve para partir da imagem e ja e o padrao da tomada 1
MODELO_H3 = re.compile(r"ref2va|(^|[_-])h3[_-]", re.I)


def modelo_de_referencia(nome: str) -> bool:
    return bool(MODELO_H3.search(nome)) and "fl2va" not in nome.lower()
LORAS_TROCA = {"troca": ["minimax_h3_character_swap_v1.1_ref2va_fro.safetensors", "h3_character_swap_v1.5.safetensors",],
               "turbo": ["minimax_h3_dmd_ref2va_8step_turbo_pruned.safetensors", "minimax_h3_ref2v_turbo_8step_v1.1_768p_comfyui_bf16.safetensors", "minimax_h3_DMAD_4step_full_lora_avg_rank_39_bf16.safetensors"],
               "nitidez": ["minimax_h3_lms_v1.0_r64.safetensors"]}
# LoRAs de estilo do H3 (Imagem para video e Troca): montadas sozinhas a cada leitura, sem lista no codigo (pedido do usuario em
# 09/11/2026). Conta como H3 a LoRA da subpasta loras/h3 ou com H3 no nome; saem as tecnicas, que o estudio ja usa por conta propria
# (aceleracao, troca de personagem, upscale/nitidez).
LORA_H3_NOME = re.compile(r"minimax[_-]?h3|mmh3|(^|[_-])h3[_-]", re.I)
# five_view: a Turnaround (folha de 5 vistas, nós H3ContactSheet), não muda o estilo de um vídeo
LORA_TECNICA = re.compile(r"turbo|dmd|dmad|lightning|\d+step|_lms_|upscal|character_swap|head_swap|five_view|turnaround", re.I)


def lora_de_estilo(caminho: str) -> bool:
    """`caminho` como o ComfyUI lista: "x.safetensors" ou, numa subpasta, "h3" + separador + "x.safetensors"."""
    partes = caminho.replace("\\", "/").lower().split("/")
    nome = caminho.replace("\\", "/").rsplit("/", 1)[-1]
    return ("h3" in partes[:-1] or bool(LORA_H3_NOME.search(nome))) and not LORA_TECNICA.search(nome)


class Cache:
    """Guarda o resultado de `funcao` por `segundos`. Um resultado que `valido` recusa (ComfyUI ainda ligando)
    vale so `segundos_falha`, para a pagina nao ficar com listas vazias."""
    def __init__(self, segundos, funcao, valido=lambda v: True, segundos_falha=None, relogio=time.time):
        self.segundos, self.funcao, self.valido, self.relogio = segundos, funcao, valido, relogio
        self.segundos_falha = segundos if segundos_falha is None else segundos_falha
        self.valor, self.quando, self.validade = None, 0, 0
        self.trava = threading.Lock()

    def __call__(self):
        with self.trava:
            if self.relogio() - self.quando >= self.validade:
                self.valor, self.quando = self.funcao(), self.relogio()
                self.validade = self.segundos if self.valido(self.valor) else self.segundos_falha
            return self.valor


def ler_comfy():
    try:
        with urllib.request.urlopen(config.URL_COMFY + "/queue", timeout=1.5) as r:
            f = json.load(r)
        return {"ligado": True, "ocupado": bool(f.get("queue_running") or f.get("queue_pending"))}
    except Exception:
        return {"ligado": False, "ocupado": False}


def _lista_opcional(lista, no, campo):
    """Nó de um pacote extra: sem ele (máquina nova, nó que não carregou) a lista fica vazia, mas as outras opções valem."""
    try:
        return lista(no, campo)
    except Exception:
        return []


def ler_opcoes():
    """O que esta instalado, perguntado ao proprio ComfyUI. Vazio se ele estiver desligado."""
    def lista(no, campo):
        with urllib.request.urlopen(f"{config.URL_COMFY}/object_info/{no}", timeout=10) as r:
            c = json.load(r)[no]["input"]["required"][campo]
        return c[0] if isinstance(c[0], list) else c[1]["options"]
    try:
        # O ComfyUI lista "h3\arquivo" quando a LoRA esta numa subpasta; a pagina usa so o nome do arquivo (ver loras.py)
        caminhos = lista("LoraLoaderModelOnly", "lora_name")
        loras = nomes_unicos(caminhos)
        return {"modelos": [m for m in lista("UNETLoader", "unet_name") if modelo_de_referencia(m)],
                "loras": [l for l in loras if SO_FLUXO_LORA.search(l) and not FORA_LORA.search(l)],
                "samplers": [s for s in SAMPLERS if s in lista("KSamplerSelect", "sampler_name")],
                "agendadores": [s for s in AGENDADORES if s in lista("BasicScheduler", "scheduler")],
                "loras_troca": {k: [l for l in v if l in loras] for k, v in LORAS_TROCA.items()},
                "loras_estilo": sorted(nomes_unicos(c for c in caminhos if lora_de_estilo(c)), key=str.lower),
                "loras_wan": pares_wan(caminhos),
                "upscalers": [u for u in _lista_opcional(lista, "MinimaxH3LatentUpscaler3D", "model_name") if not u.startswith("(")]}
    except Exception:
        return {"modelos": [], "loras": [], "samplers": [], "agendadores": [], "loras_troca": {k: [] for k in LORAS_TROCA}, "loras_estilo": [], "loras_wan": [], "upscalers": []}


def opcoes_validas(o):
    """Com o ComfyUI no ar ha sempre algum sampler; lista vazia quer dizer que ele nao respondeu."""
    return bool(o.get("samplers"))


comfy = Cache(2, ler_comfy)
opcoes = Cache(30, ler_opcoes, valido=opcoes_validas, segundos_falha=2)
