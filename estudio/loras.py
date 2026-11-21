"""Acha cada LoRA pelo nome do arquivo, em qualquer subpasta de models/loras (h3, wan, chroma...).

O estudio guarda, mostra e confere so o nome do arquivo. Na hora de mandar o grafo ao ComfyUI, `resolver_grafo` troca
o nome pelo caminho que ele usa, relativo a pasta loras e com o separador do sistema (h3\\arquivo.safetensors no Windows,
como o ComfyUI lista). Assim mover uma LoRA de pasta nao quebra os grafos, os projetos antigos nem as listas da pagina."""
import json, re
from pathlib import Path

import config, extras, palavras_lora

# LoRAs de estilo do Wan 2.2 14B vem em par: uma para o modelo High (primeiros passos) e outra para o Low (ultimos).
# O par e achado pelo nome: os dois so diferem num pedaco HIGH/LOW (ou H/L, high_noise/low_noise) entre separadores.
# Conta como Wan a LoRA da subpasta loras/wan ou com Wan 2.x no nome; saem as tecnicas (aceleracao), que o estudio ja usa.
LADO_WAN = {"high": "low", "h": "l", "highnoise": "lownoise", "hn": "ln"}
WAN_NOME = re.compile(r"wan[_ .-]?2", re.I)
WAN_TECNICA = re.compile(r"lightx2v|lightning|distill|turbo|\d+steps?|scail|rife", re.I)
SEPARADOR = re.compile(r"([_.\- ])")
# Palavras-chave (gatilhos): LoRAs treinadas com uma palavra ou frase que precisa estar no prompt para o efeito aparecer.
# A chave é um pedaço do nome do arquivo, em minúsculas. Dois tipos de entrada:
#   {"palavra": "x"}                    palavra fixa: o estúdio a põe sozinho no começo do prompt e a página avisa
#   {"frases": ["a", "b"], "nota": ""}  depende da cena: só quem escreve sabe qual usar; a página avisa e confere o texto
#                                       ("opcional": true quando a LoRA funciona sem elas e as frases só ajudam)
# "pagina" (opcional) é o endereço da ficha do modelo. Um texto no lugar do dicionário vale como palavra fixa.
# As LoRAs da comunidade desta máquina ficam no arquivo local (extras.py, seção "gatilhos"), no mesmo formato.
GATILHOS = {
    # Realism People (fal, 17/11/2026): segundo o cartão do modelo no Hugging Face
    "h3-realism-people": {"palavra": "r34l1sm", "pagina": "https://huggingface.co/fal/MiniMax-H3-Realism-People-LoRA"},
    # Felt Stop-Motion (20/11/2026): palavra de treino na ficha do Civitai; os prompts de exemplo do autor começam por ela
    "feltstopmotionstyle": {"palavra": "felt_stopmotion_style", "pagina": "https://civitai.com/models/3005946"},
}


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


def gatilhos() -> dict:
    """O cadastro de palavras-chave: o do código mais o do arquivo local, que vence na mesma chave. A página o recebe inteiro
    (/api/estado) e acha a entrada pelo nome do arquivo. Entrada sem palavra nem frases é ignorada."""
    todos = {}
    for chave, v in {**GATILHOS, **extras.secao("gatilhos")}.items():
        if isinstance(v, str):
            v = {"palavra": v}
        # Chave começada por "_" é anotação do arquivo local (como o "_sobre"), não uma LoRA
        if not isinstance(v, dict) or str(chave).startswith("_"):
            continue
        palavra, frases = v.get("palavra"), v.get("frases")
        if (isinstance(palavra, str) and palavra.strip()) or (isinstance(frases, list) and frases):
            todos[str(chave).lower()] = v
    return todos


def gatilho_do_cadastro(n, cadastro: dict | None = None) -> dict | None:
    """A entrada do cadastro do estúdio (código e arquivo local) para a LoRA `n`, achada por um pedaço do nome."""
    n = nome(str(n)).lower()
    cadastro = gatilhos() if cadastro is None else cadastro
    return next((v for chave, v in cadastro.items() if chave in n), None)


def gatilho_de(n, cadastro: dict | None = None) -> dict | None:
    """A palavra-chave que vale para a LoRA `n` (nome ou caminho), ou None se ela não pede nada. Nesta ordem: o que o
    usuário editou na página, o cadastro do estúdio e, por último, as palavras da ficha do Civitai (palavras_lora.py)."""
    daqui = palavras_lora.do_arquivo(nome(str(n)))
    if daqui and daqui[0] == "meu":
        return daqui[1]
    return gatilho_do_cadastro(n, cadastro) or (daqui[1] if daqui else None)


def para_a_pagina() -> dict:
    """Nome do arquivo (minúsculas) -> palavra-chave que vale, para cada LoRA instalada que tem uma (/api/estado)."""
    cadastro, r = gatilhos(), {}
    for chave in mapa():
        g = gatilho_de(chave, cadastro)
        if g:
            r[chave] = g
    return r


def palavras_fixas(loras) -> list:
    """As palavras fixas das LoRAs escolhidas, na ordem delas e sem repetir. Cada item da lista começa pelo nome:
    [nome, força] no H3 e no texto para imagem, [alta, baixa, força] no Wan."""
    cadastro, palavras = gatilhos(), []
    for item in loras or []:
        g = gatilho_de(item[0], cadastro)
        palavra = (g or {}).get("palavra")
        if isinstance(palavra, str) and palavra.strip() and palavra.strip() not in palavras:
            palavras.append(palavra.strip())
    return palavras


def gatilho(loras) -> str:
    """As palavras fixas das LoRAs escolhidas, separadas por espaço; vazio se nenhuma pedir."""
    return " ".join(palavras_fixas(loras))


def com_gatilho(loras, prompt: str, separador: str = " ") -> str:
    """O prompt com as palavras fixas das LoRAs no começo. A que já está escrita (sem ligar para maiúsculas) não entra de novo."""
    escrito = prompt.lower()
    faltam = [p for p in palavras_fixas(loras) if p.lower() not in escrito]
    return separador.join(faltam + [prompt]) if faltam else prompt
