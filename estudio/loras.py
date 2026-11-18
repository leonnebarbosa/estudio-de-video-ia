"""Acha cada LoRA pelo nome do arquivo, em qualquer subpasta de models/loras (h3, wan, chroma...).

O estudio guarda, mostra e confere so o nome do arquivo. Na hora de mandar o grafo ao ComfyUI, `resolver_grafo` troca
o nome pelo caminho que ele usa, relativo a pasta loras e com o separador do sistema (h3\\arquivo.safetensors no Windows,
como o ComfyUI lista). Assim mover uma LoRA de pasta nao quebra os grafos, os projetos antigos nem as listas da pagina."""
import json, re
from pathlib import Path

import config

# LoRAs de estilo do Wan 2.2 14B vem em par: uma para o modelo High (primeiros passos) e outra para o Low (ultimos).
# O par e achado pelo nome: os dois so diferem num pedaco HIGH/LOW (ou H/L, high_noise/low_noise) entre separadores.
# Conta como Wan a LoRA da subpasta loras/wan ou com Wan 2.x no nome; saem as tecnicas (aceleracao), que o estudio ja usa.
LADO_WAN = {"high": "low", "h": "l", "highnoise": "lownoise", "hn": "ln"}
WAN_NOME = re.compile(r"wan[_ .-]?2", re.I)
WAN_TECNICA = re.compile(r"lightx2v|lightning|distill|turbo|\d+steps?|scail|rife", re.I)
SEPARADOR = re.compile(r"([_.\- ])")
# Palavras de gatilho: LoRAs treinadas com uma palavra que precisa estar no prompt (pedaço do nome do arquivo -> palavra).
# Realism People (fal, 17/11/2026): "r34l1sm", segundo o cartão do modelo no Hugging Face.
GATILHOS = {"h3-realism-people": "r34l1sm"}


def pasta() -> Path:
    return config.MODELOS / "loras"


def nome(caminho: str) -> str:
    """"h3\\x.safetensors", "h3/x.safetensors" ou "x.safetensors" -> "x.safetensors"."""
    return caminho.replace("\\", "/").rsplit("/", 1)[-1]


def mapa() -> dict:
    """Nome do arquivo (em minusculas) -> caminho relativo, como o ComfyUI lista. Com o mesmo nome em duas pastas,
    vale o primeiro em ordem alfabetica do caminho. Le a pasta a cada chamada: sao poucas dezenas de arquivos."""
    raiz, m = pasta(), {}
    if raiz.is_dir():
        for p in sorted(raiz.rglob("*.safetensors"), key=lambda p: str(p).lower()):
            m.setdefault(p.name.lower(), str(p.relative_to(raiz)))
    return m


def caminho(n: str, m: dict | None = None) -> str:
    """O caminho atual da LoRA `n` (nome ou caminho antigo). Se ela nao existe, devolve `n` e o ComfyUI recusa com o nome."""
    m = mapa() if m is None else m
    return m.get(nome(n).lower(), n)


def nomes_unicos(lista) -> list:
    """Caminhos do ComfyUI -> nomes de arquivo, sem repetir, na ordem em que vieram."""
    return list(dict.fromkeys(nome(c) for c in lista))


def pares_wan(caminhos) -> list:
    """Caminhos de LoRA (como o ComfyUI lista ou como `mapa` guarda) -> [{"alta", "baixa", "nome"}], so nomes de arquivo,
    em ordem alfabetica. `nome` e o do par sem o pedaco HIGH, para mostrar na pagina. LoRA sem a outra metade fica de fora."""
    nomes = {}
    for c in caminhos:
        n = nome(c)
        pastas = c.replace("\\", "/").lower().split("/")[:-1]
        if ("wan" in pastas or WAN_NOME.search(n)) and not WAN_TECNICA.search(n):
            nomes[n.lower()] = n
    pares = []
    for n in nomes.values():
        pedacos = SEPARADOR.split(n)
        for i, p in enumerate(pedacos):
            outro = LADO_WAN.get(p.lower())
            if outro is None:
                continue
            baixa = nomes.get("".join(pedacos[:i] + [outro] + pedacos[i + 1:]).lower())
            if baixa:
                # Tira o pedaco HIGH e o separador antes dele: "estilo-22-H-e8.safetensors" -> "estilo-22-e8"
                curto = "".join(pedacos[:max(i - 1, 0)] + pedacos[i + 1:])
                pares.append({"alta": n, "baixa": baixa, "nome": re.sub(r"\.safetensors$", "", curto, flags=re.I).strip("_.- ")})
                break
    return sorted(pares, key=lambda x: x["alta"].lower())


def resolver_grafo(g: dict) -> dict:
    """Troca, no grafo (formato da API), o nome de cada LoRA pelo caminho atual. Vale para os campos com "lora" no nome
    (lora_name dos carregadores) e para o estado do carregador da Pixaroma (LoraLoaderState). Altera e devolve o proprio grafo."""
    m = mapa()
    for no in g.values():
        entradas = no.get("inputs") if isinstance(no, dict) else None
        if not isinstance(entradas, dict):
            continue
        for chave, valor in list(entradas.items()):
            if chave == "LoraLoaderState" and isinstance(valor, str):
                try:
                    estado = json.loads(valor)
                except ValueError:
                    continue
                for item in (estado.get("loras") or []) if isinstance(estado, dict) else []:
                    if isinstance(item, dict) and isinstance(item.get("name"), str):
                        item["name"] = caminho(item["name"], m)
                entradas[chave] = json.dumps(estado)
            elif "lora" in chave.lower() and isinstance(valor, str) and valor.lower().endswith(".safetensors"):
                entradas[chave] = caminho(valor, m)
    return g


def gatilho(loras) -> str:
    """As palavras de gatilho das LoRAs escolhidas ([[nome, força], ...]), separadas por espaço; vazio se nenhuma pedir."""
    nomes = [nome(str(n)).lower() for n, _ in (loras or [])]
    return " ".join(p for chave, p in GATILHOS.items() if any(chave in n for n in nomes))
