"""Tempo estimado das geracoes e o que ha na frente na fila, para o resumo dos planos do MCP.

As contas sao as da pagina (pagina/js/imagem.js e texto.js) escritas em Python: a pagina continua com as dela. Nada aqui usa
rede, GPU ou o ComfyUI; so leem-se a tarefa e a fila do proprio estudio."""

# Segundos por imagem de cada modelo (a 0,9 MP e nos passos do modelo) e os passos em que foram medidos
SEGUNDOS_IMAGEM = {"chroma_flash": 35, "z_image_turbo": 10, "klein_edit": 25, "klein_t2i": 20, "qwen21_edit": 55}
PASSOS_IMAGEM = {"chroma_flash": 12, "z_image_turbo": 8, "klein_edit": 4, "klein_t2i": 4, "qwen21_edit": 8}
SEGUNDOS_PADRAO = 35  # modelo local sem medida


def video_h3(tomadas, megapixels, pele=False):
    """Segundos para gerar um video no H3 com estas tomadas (duracoes em segundos), so a geracao. A primeira tomada nao leva os
    48 quadros de contexto das seguintes; a pele natural soma 350/312."""
    total = 0.0
    for i, s in enumerate(tomadas):
        novos = round(float(s) * 24 / 17) * 17 + 5
        total += 176 + 50 * ((novos + (0 if i == 0 else 48)) / 124) ** 2 * (megapixels / 0.4746) ** 2
    if pele:
        total *= 350 / 312
    return round(total)


def video_livre(duracao, megapixels):
    """Segundos para um video do modo livre (uma tomada no H3 com referencias). Medido: 5 s a 540p levou 230, 280 e
    278 s contra 226 da formula, e na maxima cerca de 580 contra 496; as referencias somam perto de 17%."""
    return round(video_h3([duracao], megapixels) * 1.17)


def video_audio(tomadas, megapixels):
    """Segundos para um video do modo audio da fala (pele natural sempre ligada). A conta da pagina fica abaixo do real:
    em 14 tomadas ja geradas ate 22/11/2026 (0,47 a 1,2 MP, de 3 a 8,7 s) o real foi de 1,0 a 1,7 vezes a formula.
    Com 15% a mais e 45 s da carga dos modelos, o erro ficou dentro de uns 25% em todas."""
    return round(video_h3(tomadas, megapixels, pele=True) * 1.15 + 45)


def imagem(modelo, quantidade, passos, megapixels, n_extras=0, n_loras=0, edicao=False):
    """Segundos para gerar ou editar `quantidade` imagens. Na edicao cada imagem extra soma 18 s, menos no qwen21_edit."""
    por_imagem = SEGUNDOS_IMAGEM.get(modelo, SEGUNDOS_PADRAO) * (passos / PASSOS_IMAGEM.get(modelo, passos)) * (megapixels / 0.9) ** 1.1
    por_imagem += n_loras * 10 + (n_extras * 18 if edicao and modelo != "qwen21_edit" else 0)
    return round(15 + quantidade * por_imagem)


def texto(segundos):
    """"cerca de 40 s" abaixo de 90 s; de 90 s em diante, "cerca de N min" (minimo 2)."""
    if segundos < 90:
        return f"cerca de {round(segundos)} s"
    return f"cerca de {max(2, round(segundos / 60))} min"


def linha_tempo(segundos):
    """A linha do resumo dos planos."""
    return f"Tempo estimado: {texto(segundos)} (só a geração; não conta espera na fila)."


def comfy():
    """O estado do ComfyUI ({"ligado", "ocupado"}), com o cache de 2 s do ambiente. Funcao a parte para os testes trocarem."""
    import ambiente
    return ambiente.comfy()


def fila():
    """Uma frase com o que ha na frente de um pedido novo. Le a tarefa e a fila do estudio; so quando o pedido comecaria na
    hora olha tambem o ComfyUI, como a acao da pagina faz (exigir_comfy_livre): com ele ocupado por fora ou desligado a
    confirmacao falharia, e a frase nao pode prometer o inicio."""
    import tarefa  # aqui dentro: quem so quer as contas acima nao precisa da tarefa
    rodando = tarefa.tarefa.rodando()
    f = tarefa.tarefa.fila.resumo()
    n = len(f["itens"])
    if not rodando and (f["pausada"] or not n):  # nada do estudio na frente: o pedido comecaria agora
        c = comfy()
        if not c.get("ligado"):
            return ("O ComfyUI está desligado: a confirmação vai falhar até ele ligar. "
                    "Avise o usuário e chame ver_estado antes de confirmar.")
        if c.get("ocupado"):
            return ("O ComfyUI está ocupado com outra tarefa, fora da fila do estúdio: a confirmação só funciona quando ele ficar livre. "
                    "Avise o usuário e chame ver_estado antes de confirmar.")
    if f["pausada"] and rodando:
        # parar_geracao sempre pausa a fila: o pedido entra nela e so comeca depois de retomar_fila
        com = f" com {n} {'pedido' if n == 1 else 'pedidos'}" if n else ""
        return (f"Há 1 geração em andamento e a fila está pausada{com}: este pedido entra na fila e só começa depois de retomar_fila. "
                "Pergunte ao usuário se quer retomar.")
    if f["pausada"] and n and not rodando:
        return f"A fila está pausada com {n} {'pedido' if n == 1 else 'pedidos'}; este começa assim que você confirmar."
    partes = (["1 geração em andamento"] if rodando else []) + ([f"{n} na fila"] if n else [])
    if not partes:
        return "A placa está livre: começa assim que você confirmar."
    atras = "dela" if rodando + n == 1 else "delas"
    return f"Há {' e '.join(partes)}: este pedido entra " + ("na fila " if rodando and not n else "") + f"atrás {atras}."
