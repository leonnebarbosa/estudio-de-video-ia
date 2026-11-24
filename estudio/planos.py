"""Receitas de video, regras das tomadas e planos do MCP. Quem escreve as tomadas e o agente que conversa com o usuario
(cliente MCP): regras() entrega os limites e um exemplo, o planejar_video confere as tomadas com a mesma validacao da
pagina e guarda o pedido pronto por 30 min; o confirmar_plano usa o plano uma vez so. Nada aqui toca na placa."""
import copy, json, re, secrets, threading, time
from pathlib import Path

import caminhos, config, entrada, estimativas, extras
from erros import Erro
from imagem_para_video import CAMERAS, PELE_MODELO, duracao_maxima, duracoes_permitidas
from validacao import MAX_TOMADAS, PADRAO

# Os nomes que a pagina mostra (base.js NOMES_MODELO); os modelos locais vem de modelos_locais.json (extras, secao pagina)
NOMES_MODELO = {PADRAO["modelo"]: "ref2va oficial", PELE_MODELO: "Singularity V2 · visual de cinema"}


def nomes_modelo() -> dict:
    return {**NOMES_MODELO, **(extras.secao("pagina").get("nomes_modelo") or {})}


def _nome_curto(arquivo: str) -> str:
    """Para o resumo: o nome da pagina ate o ponto (\"Singularity V2\"), senao o arquivo sem .safetensors."""
    nome = nomes_modelo().get(arquivo)
    if nome:
        return nome.split(" · ")[0]
    return arquivo[:-len(".safetensors")] if arquivo.lower().endswith(".safetensors") else arquivo

RECEITAS = config.ESTUDIO / "mcp" / "receitas.json"
REGRAS = config.ESTUDIO / "mcp" / "receitas" / "regras_tomadas.md"
REGRAS_LIVRE = config.ESTUDIO / "mcp" / "receitas" / "regras_livre.md"
TIPOS = ("receita", "livre", "imagem")  # o que o confirmar_plano inicia: acao_iniciar_imagem (receita), acao_iniciar_avancado (livre) ou acao_iniciar_texto (imagem)
AVISO_SEM_FALA = "Aviso: o prompt não tem fala marcada. Se alguém fala no vídeo, escreva a fala dentro de <d>[Portuguese (Brazil)] ...</d>."
FORMATOS = {"9:16": "9:16 (Portrait Widescreen)", "16:9": "16:9 (Widescreen)", "1:1": "1:1 (Square)"}
FORMATOS_IMAGEM = {"1:1": "1:1 (Square)", "2:3": "2:3 (Portrait Photo)", "3:2": "3:2 (Photo)", "3:4": "3:4 (Portrait Standard)",
                   "4:3": "4:3 (Standard)", "9:16": "9:16 (Portrait Widescreen)", "16:9": "16:9 (Widescreen)", "21:9": "21:9 (Ultrawide)"}
VALIDADE = 1800  # segundos que um plano vale
ARQUIVO = None  # onde os planos ficam gravados; None = config.LOGS/planos.json, lido na hora do uso (os testes apontam para outro)
# Qualidade do planejar_video (pedido do usuario, 21/11/2026): "ugc" e a receita como esta; "rapido" troca so a resolucao e
# tira a pele natural, para um teste que fica pronto bem antes
QUALIDADES = {"ugc": {}, "rapido": {"megapixels": 0.4746, "pele": False}}
# Resolucao do planejar_video: os mesmos valores do menu da pagina (validacao.QUALIDADES_IMAGEM_MENU). Quando vem, troca so os
# megapixels; a qualidade segue decidindo a pele natural
RESOLUCOES = {"480p": 0.39, "540p": 0.4746, "720p": 0.88, "maxima": 1.2}
# Receitas que pedem "um corte a cada 2 a 3 s": no exemplo, tomadas de ate CORTE_MAX s (um modelo pequeno copia o JSON do
# exemplo mais do que segue a prosa). Os limites maximos ficam so no texto "Limite por tomada"
CORTE_MAX = 3.5
# Textos do exemplo de regras(); as duracoes saem dos limites da resolucao (e dos cortes da receita)
_EXEMPLO_IMAGEM = [("The character smiles and waves at the camera while talking.", "Oi, gente! Olha só que novidade.", "aproximar"),
                   ("The character points to the side and nods.", "Chegou internet nova aqui.", "acompanhar"),
                   ("The character gives a thumbs up and smiles.", "Corre lá e aproveita!", "afastar")]
_EXEMPLO_CENA = [("A router on a shelf blinks its green lights.", "", "aproximar"),
                 ("A young woman sits on the sofa and smiles at her phone.", "Agora sim, internet de verdade.", "acompanhar")]
_CENA_EXEMPLO = "Realistic live-action commercial look, a bright modern living room, natural daylight, a young woman in a green sweater"


def receitas():
    return json.loads(RECEITAS.read_text(encoding="utf-8"))


def _br(x):
    return f"{float(x):g}".replace(".", ",")


def com_qualidade(receita: dict, qualidade: str, resolucao: str | None = None) -> dict:
    """Copia da receita com os ajustes da qualidade por cima (o resto vem da receita); a `resolucao`, quando vem, troca so os
    megapixels. Qualidade ou resolucao desconhecida: Erro."""
    if not isinstance(qualidade, str) or qualidade not in QUALIDADES:
        raise Erro(f"Qualidade desconhecida. Use uma destas: {', '.join(QUALIDADES)}.")
    if resolucao is not None and (not isinstance(resolucao, str) or resolucao not in RESOLUCOES):
        raise Erro(f"Resolução desconhecida. Use uma destas: {', '.join(RESOLUCOES)}.")
    r = copy.deepcopy(receita)
    r["ajustes"].update(QUALIDADES[qualidade])
    if resolucao is not None:
        r["ajustes"]["megapixels"] = RESOLUCOES[resolucao]
    return r


def nome_resolucao(mp: float) -> str:
    """Ex.: "720p (0,88 MP)", "máxima (1,2 MP)"; fora da tabela (o 1,1 MP do UGC), "1,1 MP"."""
    mp = float(mp)
    for nome, valor in RESOLUCOES.items():
        if abs(mp - valor) < 1e-6:
            return f"{'máxima' if nome == 'maxima' else nome} ({_br(round(valor, 2))} MP)"
    return f"{_br(round(mp, 2))} MP"


def nome_qualidade(qualidade: str, ajustes: dict) -> str:
    """Ex.: "qualidade UGC, 1,1 MP, pele natural" ou "qualidade rápida, 540p (0,47 MP)"."""
    res = nome_resolucao(ajustes.get("megapixels", 0.4746))
    if qualidade == "rapido":
        return f"qualidade rápida, {res}" + (", pele natural" if ajustes.get("pele") else "")  # com áudio da fala a pele fica ligada
    return f"qualidade UGC, {res}" + (", pele natural" if ajustes.get("pele") else "")


def avisos_resolucao(mp: float) -> list:
    """Avisos da resolucao: 480p e 720p ainda nao foram medidas nesta placa, e a maxima e a mais pesada testada."""
    mp = float(mp)
    # Um agente local escolheu a maxima sem o usuario pedir (22/11/2026): todo aviso de resolucao manda planejar de novo sem ela
    sem_pedido = " Se o usuário não pediu essa resolução, planeje de novo sem resolucao."
    if abs(mp - RESOLUCOES["480p"]) < 1e-6:
        return ["Aviso: 480p ainda não foi rodada nesta placa; deve ser um pouco mais rápida que 540p, com menos detalhe." + sem_pedido]
    if abs(mp - RESOLUCOES["720p"]) < 1e-6:
        return ["Aviso: 720p ainda não foi rodada exatamente; deve levar perto de 2 vezes o tempo de 540p." + sem_pedido]
    if abs(mp - RESOLUCOES["maxima"]) < 1e-6:
        return ["Aviso: resolução máxima é a mais pesada testada; cada tomada vai até 8 s e leva cerca do dobro do tempo de 540p." + sem_pedido]
    return []


def _foto_vai_ser_cortada(foto: str, formato: str) -> bool:
    """A proporcao da foto (na entrada: envios ou a raiz) difere da do formato em mais de 3%? Foto que nao abre: False (a validacao
    da pagina cuida dela)."""
    try:
        from PIL import Image
        with Image.open(entrada.caminho(foto)) as im:
            largura, altura = im.size
        fl, fa = (float(x) for x in formato.split(":"))
        return abs((largura / altura) / (fl / fa) - 1) > 0.03
    except (OSError, ValueError, ZeroDivisionError, ImportError):
        return False


def avisos(pedido: dict, formato: str) -> list:
    """Avisos do resumo: os da resolucao, camera parada em tomada com fala e foto cortada pelo centro (so sem a pele natural,
    em que a foto vira o primeiro quadro)."""
    a = pedido.get("ajustes") or {}
    saida = avisos_resolucao(a.get("megapixels", 0.4746))
    for i, t in enumerate(a.get("tomadas") or [], 1):
        # No modo audio a fala e o audio enviado: camera parada avisa mesmo sem a fala escrita
        if t.get("camera") == "parada" and ((t.get("fala") or "").strip() or a.get("audio")):
            saida.append(f"Aviso: tomada {i} com câmera parada. Vídeo com fala fica mais natural com a câmera em movimento.")
    if pedido.get("foto") and not a.get("pele") and _foto_vai_ser_cortada(pedido["foto"], formato):
        saida.append("Aviso: a foto tem outro formato e será cortada pelo centro.")
    return saida


def com_cortes(receita: dict) -> bool:
    """A receita pede um corte a cada 2 a 3 s (campo "cortes": fala_camera, podcast, anuncio_vertical)?"""
    return receita.get("cortes") is True


def exemplo_tomadas(receita: dict) -> list:
    """Tomadas validas para a receita (ja com a qualidade aplicada). Com cortes: tres tomadas curtas, a maior duracao
    aceita ate CORTE_MAX, a menor e de novo a maior (ex.: 3,5 + 3 + 3,5). Sem cortes: duas, a tomada 1 no limite dela e
    a 2 no limite das seguintes."""
    mp = float(receita["ajustes"].get("megapixels", 0.4746))
    if com_cortes(receita):
        curtas = [d for d in duracoes_permitidas(mp, primeira=False) if d <= CORTE_MAX]
        duracoes = [max(curtas), min(curtas), max(curtas)]
    else:
        duracoes = [max(duracoes_permitidas(mp)), max(duracoes_permitidas(mp, primeira=False))]
    textos = _EXEMPLO_IMAGEM if receita["com_imagem"] else _EXEMPLO_CENA
    return [{"acao": acao, "fala": fala, "som": "soft room tone", "camera": camera, "duracao": d}
            for (acao, fala, camera), d in zip(textos, duracoes)]


def com_audio(receita: dict) -> dict:
    """Copia da receita no modo audio da fala: a pele natural fica sempre ligada, em qualquer qualidade."""
    r = copy.deepcopy(receita)
    r["ajustes"]["pele"] = True
    return r


def exemplo_audio(n: int) -> list:
    """Tomadas validas do modo audio: n tomadas sem duracao (ela vem do corte do audio) e sem camera parada."""
    return [{"acao": acao, "fala": "", "som": "soft room tone", "camera": camera}
            for acao, _, camera in (_EXEMPLO_IMAGEM[i % len(_EXEMPLO_IMAGEM)] for i in range(n))]


def _s(x) -> str:
    return f"{_br(round(float(x), 2))} s"


def divisao_audio(cortes: list) -> str:
    """Ex.: "O áudio tem 14,8 s e vira 2 tomadas nesta resolução: 1) 6,4 s; 2) 8,4 s."."""
    total = sum(b - a for a, b in cortes)
    n = len(cortes)
    return (f"O áudio tem {_br(round(total, 1))} s e vira {n} {'tomada' if n == 1 else 'tomadas'} nesta resolução: "
            + "; ".join(f"{i}) {_s(b - a)}" for i, (a, b) in enumerate(cortes, 1)) + ".")


# Linhas do regras_tomadas.md que nao valem no modo audio (a fala e o audio, a duracao vem do corte e nao ha corte a cada 2 a 3 s)
_FORA_DO_AUDIO = ("- Fala:", "- Duração:", "- Cortes:")


def regras(rid: str, receita: dict, qualidade: str, audio: dict | None = None, resolucao: str | None = None) -> str:
    """O texto de regras_das_tomadas: limites na resolucao da qualidade, duracoes e cameras aceitas, a instrucao da
    receita, o regras_tomadas.md, a cena (obrigatoria sem imagem) e um exemplo de tomadas em JSON. Com `audio`
    ({"nome", "cortes"}, o modo audio da fala): no lugar dos limites, a divisao do audio e o que cada tomada leva.
    `resolucao` e a pedida pelo usuario (ja aplicada na receita); so entra na linha final, para o planejar_video repeti-la."""
    mp = float(receita["ajustes"].get("megapixels", 0.4746))
    instrucao = receita["instrucao"]
    if audio:  # com o audio da fala as tomadas saem do corte do audio: a frase dos cortes de 2 a 3 s confunde o agente
        instrucao = re.sub(r",?\s*e um corte a cada 2 a 3 s(\s*\([^)]*\))?", "", instrucao)
    linhas = [f"Regras das tomadas: receita {rid} ({receita['nome']}), {nome_qualidade(qualidade, receita['ajustes'])}.",
              f"Receita: {instrucao}"]
    if audio:
        n = len(audio["cortes"])
        linhas += [divisao_audio(audio["cortes"]),
                   f"Mande exatamente {n} {'tomada' if n == 1 else 'tomadas'}, na ordem. Cada tomada leva acao, camera e som; "
                   "a fala escrita é opcional (se o usuário disser o texto, escreva-o: ela só guia a boca, o som é o áudio enviado). "
                   "Não mande a duracao: ela vem do corte do áudio. Os cortes de 2 a 3 s não valem aqui. "
                   "A Pele natural fica ligada, em qualquer qualidade. Se o usuário tiver uma foto do lugar, passe-a em cenario.",
                   f"Câmeras aceitas: {', '.join(CAMERAS)}. Evite \"parada\": gera aviso."]
    else:
        linhas += [f"Limite por tomada a {_br(mp)} MP: tomada 1 até {_br(duracao_maxima(mp))} s; "
                   f"tomadas 2 em diante até {_br(duracao_maxima(mp, primeira=False))} s.",
                   f"Durações aceitas (s): tomada 1: {', '.join(map(_br, duracoes_permitidas(mp)))}; "
                   f"tomadas 2 em diante: {', '.join(map(_br, duracoes_permitidas(mp, primeira=False)))}.",
                   f"Câmeras aceitas: {', '.join(CAMERAS)}.",
                   f"De 1 a {MAX_TOMADAS} tomadas. A duração do vídeo é a soma das tomadas."]
    if receita["com_imagem"] and not receita["ajustes"].get("pele"):
        linhas.append("Cena: não mande; nesta qualidade a tomada 1 e o lugar saem da imagem do personagem ou da foto.")
    elif receita["com_imagem"]:
        padrao = f"o lugar desta receita: \"{receita['lugar']}\"" if receita.get("lugar") else "o padrão do estúdio (um cômodo claro)"
        linhas.append("Cena (opcional): onde acontece, o lugar atrás da pessoa, em inglês: lugar e luz. A tomada 1 parte da imagem do "
                      f"personagem ou da foto; a cena só diz o lugar em volta. Sem cena, vale {padrao}. Mande só se o usuário pedir outro lugar.")
    else:
        linhas.append("Cena: obrigatória (sem imagem), em inglês: estilo, lugar e luz, e quem aparece. "
                      f"Exemplo: \"{_CENA_EXEMPLO}\".")
    texto_md = REGRAS.read_text(encoding="utf-8").strip()
    exemplo = exemplo_tomadas(receita)
    if audio:
        texto_md = "\n".join(l for l in texto_md.splitlines() if not l.startswith(_FORA_DO_AUDIO))
        exemplo = exemplo_audio(len(audio["cortes"]))
    linhas += ["", texto_md, "",
               "Exemplo de tomadas (JSON válido para esta receita e qualidade):",
               json.dumps(exemplo, ensure_ascii=False, indent=1), "",
               "Depois, chame planejar_video com estas mesmas receita e qualidade"
               + (f" e resolucao \"{resolucao}\"" if resolucao else "") + ", o formato"
               + (", o personagem (ou a foto)" if receita["com_imagem"] else "")
               + (f", o audio_fala {audio['nome']}" if audio else "")
               + ("" if receita["com_imagem"] else ", a cena") + " e as tomadas que você escreveu."]
    return "\n".join(linhas)


class Planos:
    """Planos na memoria do servidor: codigo -> pedido pronto, de um de tres tipos: "receita" (acoes.acao_iniciar_imagem),
    "livre" (o video avancado do modo livre) ou "imagem" (acoes.acao_iniciar_texto). Cada codigo vale 1 vez so e por VALIDADE. Cada mudanca tambem vai para
    ARQUIVO (logs/planos.json) e o arquivo e lido uma vez, na primeira operacao: planos pendentes sobrevivem a um religamento
    do estudio. Quem esvazia `_itens` na mao (os testes) nao dispara nova leitura: so recarregar() le o arquivo de novo."""

    def __init__(self):
        self._itens = {}
        self._trava = threading.Lock()
        self._carregado = False

    def recarregar(self):
        """Esvazia a memoria e le o arquivo de novo na proxima operacao (o que acontece num religamento do estudio)."""
        with self._trava:
            self._itens.clear()
            self._carregado = False

    def _caminho(self) -> Path:
        return Path(ARQUIVO) if ARQUIVO else config.LOGS / "planos.json"

    def _carregar(self):
        """Chamado com a trava: na primeira operacao junta a memoria o que o arquivo guarda e ainda vale. Plano usado fica
        pelo mesmo prazo da limpeza em memoria (4*VALIDADE): repetir o confirmar_plano continua ouvindo "ja foi confirmado"."""
        if self._carregado:
            return
        self._carregado = True
        try:
            dados = json.loads(self._caminho().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(dados, dict):
            return
        agora = time.time()
        for codigo, x in dados.items():
            # O tipo fica como veio: um tipo novo (de uma versao mais nova do estudio) tambem sobrevive
            if (isinstance(x, dict) and isinstance(x.get("pedido"), dict) and isinstance(x.get("resumo"), str)
                    and isinstance(x.get("tipo"), str) and isinstance(x.get("usado"), bool)
                    and isinstance(x.get("criado"), (int, float)) and not isinstance(x.get("criado"), bool)
                    and agora - x["criado"] <= (4 * VALIDADE if x["usado"] else VALIDADE)):
                self._itens.setdefault(codigo, {k: x[k] for k in ("pedido", "resumo", "criado", "usado", "tipo")})

    def _gravar(self):
        """Chamado com a trava. Quem nao consegue gravar segue so em memoria. Devolve se gravou."""
        try:
            arq = self._caminho()
            arq.parent.mkdir(parents=True, exist_ok=True)
            caminhos.gravar_json(arq, self._itens)
            return True
        except (OSError, TypeError, ValueError):
            return False

    def _gravar_consumo(self):
        """Como _gravar, para quem gasta um plano: se o arquivo ficar com o estado antigo (usado: False), um religamento
        reabriria o plano e o confirmar_plano repetido geraria de novo. Entao, sem gravar, apaga o arquivo (perde os outros
        planos pendentes, mas nunca reabre um usado). Se nem apagar der, segue em memoria."""
        if not self._gravar():
            try:
                self._caminho().unlink(missing_ok=True)
            except OSError:
                pass

    def criar(self, pedido: dict, resumo: str, tipo: str = "receita") -> str:
        if tipo not in TIPOS:
            raise Erro(f"Tipo de plano desconhecido: {tipo}.")
        with self._trava:
            self._carregar()
            agora = time.time()
            for c in [c for c, x in self._itens.items() if agora - x["criado"] > 4 * VALIDADE]:
                del self._itens[c]
            codigo = secrets.token_hex(3)
            while codigo in self._itens:
                codigo = secrets.token_hex(3)
            self._itens[codigo] = {"pedido": copy.deepcopy(pedido), "resumo": resumo, "criado": agora, "usado": False, "tipo": tipo}
            self._gravar()
            return codigo

    def tipo_de(self, codigo: str) -> str:
        """O tipo do plano ("receita", "livre" ou "imagem"; um plano de versao mais nova pode trazer outro); vale tambem para um plano ja usado ou vencido."""
        with self._trava:
            self._carregar()
            x = self._itens.get(str(codigo or "").strip().lower())
            if x is None:
                raise Erro("Plano não encontrado. Peça para planejar de novo.", 404)
            return x["tipo"]

    def usar(self, codigo: str) -> dict:
        with self._trava:
            self._carregar()
            x = self._itens.get(str(codigo or "").strip().lower())
            if x is None:
                raise Erro("Plano não encontrado. Peça para planejar de novo.", 404)
            if x["usado"]:
                raise Erro("Este plano já foi confirmado.", 409)
            if time.time() - x["criado"] > VALIDADE:
                raise Erro("Este plano expirou. Peça para planejar de novo.", 410)
            x["usado"] = True
            self._gravar_consumo()
            return copy.deepcopy(x["pedido"])

    def vale_ate(self, codigo: str) -> str:
        """A hora (HH:MM) em que o plano vence; "" se o codigo nao existe."""
        with self._trava:
            self._carregar()
            x = self._itens.get(str(codigo or "").strip().lower())
        return time.strftime("%H:%M", time.localtime(x["criado"] + VALIDADE)) if x else ""

    def devolver(self, codigo: str):
        """O inicio falhou (ComfyUI desligado, por exemplo): o plano pode ser confirmado de novo, dentro da validade."""
        with self._trava:
            self._carregar()
            x = self._itens.get(str(codigo or "").strip().lower())
            if x:
                x["usado"] = False
                self._gravar()


planos = Planos()


def linha_semente(semente: int) -> str:
    """A linha do resumo quando o pedido fixa a semente (so com pedido do usuario: sem ela cada geracao sorteia)."""
    return f"Semente: {semente} (fixa)"


def resumo(pedido: dict, qualidade: str | None = None) -> str:
    """Uma linha geral e uma por tomada, para o operador mostrar ao usuario antes de confirmar. Com `qualidade`, a linha
    geral diz qual (nome_qualidade)."""
    a = pedido.get("ajustes") or {}
    tomadas = a.get("tomadas") or []
    formato = next((k for k, v in FORMATOS.items() if v == a.get("proporcao")), a.get("proporcao") or "?")
    total = sum(float(t["duracao"]) for t in tomadas)
    pers = pedido.get("personagem")
    if pers:
        import personagens
        try:
            quem = f"personagem {personagens.ler(pers['id']).get('nome') or pers['id']}"
            # Um visual (outra roupa da mesma pessoa) mostra "Pessoa · Rótulo"; a raiz sem rótulo ("Original") segue só com o nome
            lista = {f["id"]: f for f in personagens.listar()}
            f = lista.get(pers["id"])
            if f and f.get("visual") and f["visual"] != "Original":
                quem = f"personagem {(lista.get(f.get('pessoa')) or f).get('nome') or pers['id']} · {f['visual']}"
        except (OSError, ValueError, KeyError):
            quem = f"personagem {pers.get('id')}"
    elif pedido.get("foto"):
        quem = f"foto {pedido['foto']}"
    else:
        quem = "sem imagem"
    linhas = [f"vídeo {formato}, {_br(total)} s, {quem}, {len(tomadas)} {'tomada' if len(tomadas) == 1 else 'tomadas'}"
              + (f", {nome_qualidade(qualidade, a)}" if qualidade else "")]
    duracoes, mp = [float(t["duracao"]) for t in tomadas], float(a.get("megapixels") or 0.4746)
    linhas.append(estimativas.linha_tempo(estimativas.video_audio(duracoes, mp) if a.get("audio")
                                          else estimativas.video_h3(duracoes, mp, bool(a.get("pele")))))
    if a.get("primeira"):
        linhas.append(f"Modelo da tomada 1: {_nome_curto(a['primeira'])}")
    if a.get("seguintes"):
        linhas.append(f"Tomadas seguintes: {_nome_curto(a['seguintes'])}")
    if a.get("loras"):
        linhas.append("LoRAs de estilo: " + ", ".join(f"{_nome_curto(n)} ({_br(f)})" for n, f in a["loras"]))
    if a.get("semente") is not None:
        linhas.append(linha_semente(a["semente"]))
    if pedido.get("foto") and not pers:
        linhas.append(f"{'Pessoa da foto' if a.get('pele') else 'Primeiro quadro'}: {pedido['foto']}")
    if a.get("audio"):
        linhas.append(f"Áudio da fala: {a['audio']} ({_br(round(total, 1))} s, {len(tomadas)} {'tomada' if len(tomadas) == 1 else 'tomadas'})")
    if a.get("cenario"):
        linhas.append(f"Lugar (foto): {a['cenario']}")
    if pers or pedido.get("foto"):
        # Com imagem, a cena e o lugar atras da pessoa, e so a pele natural usa (imagem_para_video.prompt_pele); vazia, um
        # comodo claro. Sem a pele (qualidade rapido) o lugar sai da imagem: nao entra no resumo
        if a.get("audio"):
            # No modo audio o lugar e o da propria imagem (imagem_para_video.prompt_audio), a nao ser que venha o cenario
            if not a.get("cenario"):
                de_onde = "o fundo da imagem do personagem" if pers else "o lugar da foto"
                linhas.append(f"Onde: {de_onde} (para outro lugar, mande cenario)")
        elif a.get("pele"):
            linhas.append(f"Onde: {a.get('cena') or 'o padrão do estúdio (um cômodo claro)'}")
    elif a.get("cena"):
        linhas.append(f"cena: {a['cena']}")
    for i, t in enumerate(tomadas, 1):
        fala = (t.get("fala") or "").strip()
        linhas.append(f"{i}) {_br(t['duracao'])} s, câmera {t['camera']}: {fala or '(sem fala) ' + (t.get('acao') or '').strip()}")
    return "\n".join(linhas + avisos(pedido, formato))


def tem_seis_partes(prompt: str) -> bool:
    """O prompt traz, em ordem, uma linha `nome:` para cada parte de editar_video.SECOES? (Sem limpar_roteiro: este mexe no texto.)
    O import fica aqui dentro: o editar_video puxa modulos pesados ao ser importado."""
    import editar_video
    pos = 0
    for nome in editar_video.SECOES:
        m = re.compile(rf"(?m)^{nome}:").search(str(prompt), pos)
        if not m:
            return False
        pos = m.end()
    return True


def erro_seis_partes(prompt: str) -> str | None:
    """Por que o prompt do modo livre nao serve (falta uma parte, ou estao fora de ordem), ou None. O planejar_video_livre recusa
    com esta mensagem: o agente local mandava texto solto e o aviso no resumo nao bastava (decisao do usuario, 22/11/2026).
    A pagina continua aceitando texto solto: esta conferencia e so do MCP."""
    import editar_video
    partes = ", ".join(f"{n}:" for n in editar_video.SECOES)
    faltam = [n for n in editar_video.SECOES if not re.search(rf"(?m)^{n}:", str(prompt))]
    if faltam:
        return (f"O prompt do modo livre precisa das seis partes, nesta ordem, cada uma começando uma linha: {partes} "
                f"Falta: {', '.join(faltam)}. Chame regras_do_modo_livre e copie o modelo preenchido, trocando só o conteúdo.")
    if not tem_seis_partes(prompt):
        return f"As seis partes do prompt precisam vir nesta ordem: {partes} Chame regras_do_modo_livre e copie o modelo preenchido."
    return None


_TIPOS_MIDIA = {"foto": "foto", "video": "vídeo", "audio": "áudio"}


def resumo_livre(d: dict) -> str:
    """O resumo do plano do modo livre: formato, duracao, resolucao, uma linha por referencia, o prompt inteiro (com @nome, como o
    agente escreveu) e os avisos."""
    formato = next((k for k, v in FORMATOS.items() if v == d["proporcao"]), d["proporcao"])
    refs = d["referencias"]
    linhas = [f"vídeo {formato}, {_br(d['duracao'])} s, {nome_resolucao(d['megapixels'])}, modo livre, "
              f"{len(refs)} {'referência' if len(refs) == 1 else 'referências'}"]
    linhas.append(estimativas.linha_tempo(estimativas.video_livre(float(d["duracao"]), float(d["megapixels"]))))
    if d.get("semente") is not None:
        linhas.append(linha_semente(d["semente"]))
    linhas += [f"@{r['nome']}: {r['arquivo']} ({_TIPOS_MIDIA[r['tipo']]})" for r in refs]
    linhas += ["Prompt:", d["prompt"]]
    if "<d>[" not in d["prompt"]:
        linhas.append(AVISO_SEM_FALA)
    return "\n".join(linhas + avisos_resolucao(d["megapixels"]))


def _prompt_do_modelo(texto_md: str) -> str:
    """O prompt do modelo preenchido do regras_livre.md: o bloco entre as cercas ```."""
    return texto_md.split("```")[1].strip("\n")


def regras_livre(resolucao: str = "540p") -> str:
    """O texto de regras_do_modo_livre: limites, duracoes aceitas nesta resolucao (as mesmas da validacao: tomada 1), o papel de
    cada tipo de referencia, o regras_livre.md e um exemplo de chamada do planejar_video_livre."""
    import video_avancado
    if not isinstance(resolucao, str) or resolucao not in RESOLUCOES:
        raise Erro(f"Resolução desconhecida. Use uma destas: {', '.join(RESOLUCOES)}.")
    mp = RESOLUCOES[resolucao]
    lim = video_avancado.LIMITES
    permitidas = duracoes_permitidas(mp)
    texto_md = REGRAS_LIVRE.read_text(encoding="utf-8").strip()
    duracao = 5 if 5 in permitidas else max(permitidas)
    chamada = {"prompt": _prompt_do_modelo(texto_md),
               "referencias": [{"nome": "ana", "midia": "ana.png"}, {"nome": "voz", "midia": "voz.wav"}],
               "formato": "9:16", **({} if resolucao == "540p" else {"resolucao": resolucao}), "duracao": duracao}
    return "\n".join([
        f"Regras do modo livre: uma tomada no MiniMax H3 com referências, resolução {nome_resolucao(mp)}.",
        f"Limites: de 1 a {sum(lim.values())} referências ({lim['foto']} fotos, {lim['video']} vídeos e {lim['audio']} áudios); "
        f"o prompt tem até {video_avancado.MAX_PROMPT} caracteres. Todas são mídias do estúdio (listar_midias).",
        f"Durações aceitas nesta resolução: {', '.join(map(_br, permitidas))} s. Uma tomada só; o vídeo tem essa duração.",
        "Papel de cada referência:",
        "- foto: referência visual (uma pessoa, um lugar, um objeto).",
        "- vídeo: o H3 usa só o começo do vídeo como referência visual; o som dele não entra.",
        "- áudio: até 15 s orientam a voz ou o som, e o áudio NÃO fica preso ao vídeo. Para manter uma gravação exatamente como é, "
        "o caminho é o audio_fala das receitas (regras_das_tomadas).",
        "", texto_md, "",
        "Exemplo de chamada de planejar_video_livre (as mídias ana.png e voz.wav são só um exemplo; use as que listar_midias mostrar):",
        json.dumps(chamada, ensure_ascii=False, indent=1), "",
        "Depois, chame planejar_video_livre com o seu prompt, as referências, o formato, a resolução e a duração."])


def resumo_estilo(a: dict, foto: str) -> str:
    """O resumo do plano de estilo pronto (estilos.py): o estilo, a foto, o motor, o tempo e o detalhe acrescentado, se houver."""
    import estilos
    from texto_para_imagem import MODELOS_TEXTO
    q, e = a["quantidade"], a["estilo"]
    modelo = estilos.motor(e, bool(a.get("qualidade_alta")))
    por_imagem = 48 if a.get("qualidade_alta") else 95 if e == "realista" else 21
    segundos = 15 + (15 if estilos.usa_cores(e) else 0) + q * por_imagem
    linhas = [f"mudar o estilo da imagem para {estilos.ESTILOS[e]['nome']}, {q} {'resultado' if q == 1 else 'resultados'}",
              f"Motor: {MODELOS_TEXTO[modelo]['nome']}" + (" (qualidade alta)" if a.get("qualidade_alta") else ""),
              "Formato: o da foto", f"image 1: {foto}", estimativas.linha_tempo(segundos)]
    if (a.get("prompt") or "").strip():
        linhas += ["Detalhe a mais:", a["prompt"].strip()]
    return "\n".join(linhas)


def resumo_imagem(d: dict) -> str:
    """O resumo do plano de imagem: a operacao (gerar, editar, juntar), o modelo pelo nome mostrado, o formato (so ao gerar), a
    quantidade, as imagens na ordem de "image N", o tempo estimado e o prompt inteiro."""
    from texto_para_imagem import MODELOS_TEXTO
    a = d["ajustes"]
    m = MODELOS_TEXTO[a["modelo"]]
    imagens = [x for x in [a.get("partida"), a.get("referencia"), *(a.get("referencias") or [])] if x]
    q = a["quantidade"]
    semente = [linha_semente(a["semente"])] if a.get("semente") is not None else []
    if a.get("estilo"):
        return "\n".join([resumo_estilo(a, imagens[0]), *semente])
    if not imagens:
        linhas = [f"gerar {q} {'imagem' if q == 1 else 'imagens'} a partir do texto"]
    elif len(imagens) == 1:
        linhas = [f"editar a imagem, {q} {'resultado' if q == 1 else 'resultados'}"]
    else:
        linhas = [f"juntar {len(imagens)} imagens numa só, {q} {'resultado' if q == 1 else 'resultados'}"]
    linhas.append(f"Modelo: {m['nome']}")
    if imagens:
        linhas.append("Formato: o da image 1 (a saída segue a primeira imagem)")
    else:
        linhas.append("Formato: " + next((k for k, v in FORMATOS_IMAGEM.items() if v == a["proporcao"]), a["proporcao"]))
    linhas += [f"image {i}: {x}" for i, x in enumerate(imagens, 1)]
    linhas.append(estimativas.linha_tempo(estimativas.imagem(a["modelo"], q, a["passos"], float(a["megapixels"]),
                                                             max(0, len(imagens) - 1), 0, bool(m.get("edicao")))))
    return "\n".join(linhas + semente + ["Prompt:", a["prompt"]])
