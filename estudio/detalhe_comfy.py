"""O que o ComfyUI esta fazendo agora, a partir do aviso progress_state: o no que roda, a fase, o ritmo dos passos.

Usado pelo acompanhamento da troca de personagem e da imagem para video. O resumo vai para o progresso.json (a
pagina mostra) e cada mudanca de fase vira uma linha no registro tecnico, com a placa naquele momento.
O ComfyUI so manda os nos que ja comecaram, entao nao da para contar "no X de Y" com confianca: fica a fase.
"""
import time

# Ordem importa: "Loader" antes de "Load...", "VAEEncode" antes de "Encode"
FASES = (("Sampler", "amostrar"), ("Loader", "carregar"), ("VAEDecode", "decodificar"), ("Decode", "decodificar"),
         ("VAEEncode", "codificar"), ("Encode", "texto"), ("Upscale", "ampliar"), ("Save", "salvar"), ("Combine", "salvar"),
         ("CreateVideo", "salvar"), ("LoadImage", "ler"), ("LoadVideo", "ler"), ("LoadAudio", "ler"))
# Servem para video e para imagem: o modo aparece no titulo do andamento
NOMES = {"amostrar": "Gerando", "carregar": "Carregando modelos", "decodificar": "Decodificando",
         "codificar": "Preparando a referência", "texto": "Lendo o texto", "ampliar": "Ampliando", "salvar": "Salvando",
         "ler": "Lendo a mídia", "outro": "Processando"}


def fase_de(tipo):
    return next((f for trecho, f in FASES if trecho in (tipo or "")), "outro")


def relogio(s):
    s = max(0, round(s))
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def placa(monitor):
    u = getattr(monitor, "ultimo", None)
    if not u:
        return ""
    partes = [f"{u['temp']} °C", f"{u['vram_mib'] / 1024:.1f} GB".replace(".", ",")]
    if u.get("watts"):
        partes.append(f"{round(u['watts'])} W")
    return " | placa " + ", ".join(partes)


class Detalhe:
    def __init__(self, monitor, grafo=None, inicio=None, escrever=print):
        self.monitor, self.escrever = monitor, escrever
        self.inicio = inicio or time.time()
        self.reiniciar(grafo)

    def reiniciar(self, grafo=None):
        """Chamado a cada grafo novo (cada tomada): os ids dos nos mudam de significado."""
        self.tipos = {str(k): v.get("class_type", "") for k, v in (grafo or {}).items()}
        self.no, self.tipo, self.fase, self.fase_desde = "", "", "", time.time()
        self.valor = self.maximo = 0
        self.passo_inicio, self.s_passo, self.aquecido = None, 0.0, False

    def linha(self, texto):
        self.escrever(f"[{relogio(time.time() - self.inicio)}] {texto}{placa(self.monitor)}", flush=True)

    def evento(self, nos):
        """nos: o campo data.nodes do progress_state. Devolve True quando ha um no rodando."""
        rodando = [(str(k), n) for k, n in nos.items() if n.get("state") == "running"]
        if not rodando:
            return False
        # Com mais de um no rodando, o que tem passos (o amostrador) diz mais
        k, n = max(rodando, key=lambda kn: kn[1].get("max", 0) or 0)
        tipo = self.tipos.get(k) or self.tipos.get(str(n.get("real_node_id") or "")) or ""
        agora = time.time()
        if k != self.no:
            if self.fase == "amostrar" and self.maximo > 1 and self.s_passo:
                self.linha(f"amostragem pronta: {self.maximo} passos em {relogio(agora - self.fase_desde)} ({self.s_passo:.1f} s por passo)")
            fase = fase_de(tipo)
            if fase != self.fase:
                self.fase, self.fase_desde = fase, agora
                self.linha(f"{NOMES[fase]} ({tipo or 'nó'} #{k})")
            self.no, self.tipo = k, tipo
            self.passo_inicio, self.s_passo = None, 0.0
        valor, maximo = round(n.get("value", 0) or 0), round(n.get("max", 0) or 0)
        if maximo > 1:
            # O primeiro passo inclui o aquecimento (carregar pesos na placa): o ritmo conta a partir do fim dele
            if self.passo_inicio is None or valor < self.passo_inicio[1]:
                self.passo_inicio, self.aquecido = (agora, valor), False
            elif valor > self.passo_inicio[1]:
                if not self.aquecido:
                    self.passo_inicio, self.aquecido = (agora, valor), True
                else:
                    self.s_passo = (agora - self.passo_inicio[0]) / (valor - self.passo_inicio[1])
        self.valor, self.maximo = valor, maximo
        return True

    def dados(self):
        if not self.fase:
            return {}
        return {"fase": self.fase, "fase_nome": NOMES[self.fase], "no": self.no, "tipo": self.tipo,
                "s_passo": round(self.s_passo, 2), "fase_em": round(self.fase_desde - self.inicio)}
