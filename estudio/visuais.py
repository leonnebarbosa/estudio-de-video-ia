"""Pessoa e visuais: cada cópia com roupa nova (copia_de) pertence à pessoa da raiz da cadeia."""


def _raiz(f, por_id):
    # Segue copia_de até a raiz; guarda os já vistos para um ciclo não travar (o próprio item vira raiz)
    vistos = {f["id"]}
    atual = f
    while True:
        pai = atual.get("copia_de")
        if not pai or pai not in por_id:
            return atual
        if pai in vistos:
            return f
        vistos.add(pai)
        atual = por_id[pai]


def agrupar(fichas):
    """Para cada id, (id da pessoa, rótulo do visual)."""
    por_id = {f["id"]: f for f in fichas}
    saida = {}
    for f in fichas:
        raiz = _raiz(f, por_id)
        if f.get("visual"):
            rotulo = f["visual"]
        elif raiz is f:
            rotulo = "Original"
        else:
            nome, prefixo = str(f.get("nome") or ""), f"{raiz.get('nome') or ''} ("
            achou = nome.startswith(prefixo) and nome.endswith(")") and len(nome) > len(prefixo) + 1
            rotulo = nome[len(prefixo):-1] if achou else nome
        saida[f["id"]] = (raiz["id"], rotulo)
    return saida


def pronto(f, eh_pessoa):
    """A pessoa sempre serve; a cópia só depois de aprovar a ficha dela. Uma raiz com o campo `visual` é cópia promovida
    (o Original foi apagado): a raiz normal nunca tem esse campo, então ela segue exigindo aprovação."""
    return bool(f.get("ficha_aprovada")) or (eh_pessoa and not f.get("visual"))
