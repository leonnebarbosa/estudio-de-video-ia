"""Fila de geracoes: com uma geracao rodando, os pedidos novos esperam aqui e comecam sozinhos, um depois do outro.

O pedido e conferido e o projeto criado na hora (como sem fila); so o lancamento espera. Fica em logs/fila.json, que
sobrevive a fechar o estudio e a reiniciar o PC.
Regras (pedido do usuario, 17/11/2026):
- 15 s entre uma geracao e a proxima (a placa respira; ela caiu varias vezes sob carga longa).
- Falhou ou foi parada: a fila pausa e diz por que. Continuar a fila e com o botao da pagina.
- Queda da placa: se a retomada relancar a geracao que caiu, a fila segue depois dela. Se cair de novo (a retomada so
  tenta uma vez), fica pausada.
- Ao ligar o estudio sem retomada, a fila que tinha pedidos fica pausada: nada comeca sem o usuario ver.
"""
import json, threading, time, uuid

import config

ARQUIVO = "fila.json"
INTERVALO = 15            # segundos entre o fim de uma geracao e o comeco da proxima
ESPERA_COMFY = 15 * 60    # quanto esperar o ComfyUI ficar pronto antes de lancar o proximo


class Fila:
    """`lancar(cmd, projeto, modo, tipo)` comeca uma geracao; `rodando()` diz se ha uma em andamento; `trava` e a da
    tarefa (um pedido da pagina e o comeco do proximo da fila nao podem se cruzar); `comfy_pronto()` diz se o ComfyUI
    esta ligado e livre."""

    def __init__(self, lancar, rodando, trava, comfy_pronto, arquivo=None, intervalo=INTERVALO, espera_comfy=ESPERA_COMFY, passo_comfy=5):
        self.lancar, self.rodando, self.trava, self.comfy_pronto = lancar, rodando, trava, comfy_pronto
        self.arquivo = arquivo
        self.intervalo, self.espera_comfy, self.passo_comfy = intervalo, espera_comfy, passo_comfy
        self.proxima_em = None    # quando o proximo comeca (time.time), enquanto espera os 15 s
        self._agendado = None
        self.dados = self._ler()

    # ---------------------------------------------------------------- arquivo

    def _arq(self):
        return self.arquivo or config.LOGS / ARQUIVO

    def _ler(self):
        try:
            d = json.loads(self._arq().read_text(encoding="utf-8"))
            if isinstance(d, dict) and isinstance(d.get("itens"), list):
                return {"pausada": bool(d.get("pausada")), "motivo": d.get("motivo") or "", "projeto_falhou": d.get("projeto_falhou"), "itens": d["itens"]}
        except (OSError, ValueError):
            pass
        return {"pausada": False, "motivo": "", "projeto_falhou": None, "itens": []}

    def _gravar(self):
        try:
            arq = self._arq()
            arq.parent.mkdir(parents=True, exist_ok=True)
            tmp = arq.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.dados, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(arq)
        except OSError:
            pass

    # ---------------------------------------------------------------- consultas

    def itens(self):
        return list(self.dados["itens"])

    def ativa(self):
        """Ha pedidos esperando e a fila nao esta pausada: um pedido novo vai para o fim dela."""
        return bool(self.dados["itens"]) and not self.dados["pausada"]

    def tem(self, projeto):
        return any(i["projeto"] == projeto for i in self.dados["itens"])

    def resumo(self):
        falta = round(self.proxima_em - time.time()) if self.proxima_em else None
        return {"pausada": self.dados["pausada"], "motivo": self.dados["motivo"], "intervalo": self.intervalo, "proxima_em": max(0, falta) if falta is not None else None,
                "itens": [{k: i[k] for k in ("id", "projeto", "modo", "tipo", "criado")} for i in self.dados["itens"]]}

    # ---------------------------------------------------------------- pedidos

    def adicionar(self, cmd, projeto, modo, tipo):
        """Chamado com a trava da tarefa. Devolve a posicao na fila (1 = o proximo)."""
        self.dados["itens"].append({"id": uuid.uuid4().hex[:8], "cmd": [str(c) for c in cmd], "projeto": projeto, "modo": modo, "tipo": tipo, "criado": time.time()})
        self._gravar()
        # Nada rodando e a fila parada esperando (o ComfyUI ainda ligando, por exemplo): ja agenda
        if not self.rodando() and not self.dados["pausada"] and self._agendado is None:
            self._agendar(1)
        return len(self.dados["itens"])

    def tirar(self, iid):
        with self.trava:
            antes = len(self.dados["itens"])
            self.dados["itens"] = [i for i in self.dados["itens"] if i["id"] != iid]
            if len(self.dados["itens"]) == antes:
                raise KeyError(iid)
            self._gravar()

    def mover(self, iid, passo):
        with self.trava:
            lista = self.dados["itens"]
            k = next((n for n, i in enumerate(lista) if i["id"] == iid), None)
            if k is None:
                raise KeyError(iid)
            j = max(0, min(len(lista) - 1, k + passo))
            lista.insert(j, lista.pop(k))
            self._gravar()

    def pausar(self, motivo, projeto_falhou=None):
        self.dados.update(pausada=True, motivo=motivo, projeto_falhou=projeto_falhou)
        self._cancelar()
        self._gravar()

    def continuar(self):
        with self.trava:
            self.dados.update(pausada=False, motivo="", projeto_falhou=None)
            self._gravar()
            if not self.rodando() and self.dados["itens"]:
                self._agendar(1)

    # ---------------------------------------------------------------- fim de uma geracao e a proxima

    def terminou(self, projeto, codigo, parada):
        """A geracao acabou (chamado pela tarefa). Bem: o proximo em 15 s. Mal ou parada: pausa."""
        if codigo == 0 and not parada:
            if self.dados["itens"] and not self.dados["pausada"]:
                self._agendar(self.intervalo)
            return
        if not self.dados["itens"]:
            return
        if parada:
            self.pausar(f"Você parou a geração de {projeto}. A fila pausou.")
        else:
            self.pausar(f"A geração de {projeto} falhou (código {codigo}). A fila pausou: confira o projeto e clique em Continuar a fila.", projeto)

    def _agendar(self, segundos):
        self._cancelar()
        self.proxima_em = time.time() + segundos
        t = threading.Timer(segundos, self._proxima)
        t.daemon = True
        self._agendado = t
        t.start()

    def _cancelar(self):
        if self._agendado is not None:
            self._agendado.cancel()
        self._agendado, self.proxima_em = None, None

    def _proxima(self):
        """Lanca o primeiro da fila quando o ComfyUI estiver livre."""
        limite = time.monotonic() + self.espera_comfy
        while not self.comfy_pronto():
            if time.monotonic() > limite:
                with self.trava:
                    self.pausar("O ComfyUI não ficou pronto para o próximo da fila. Quando ele voltar, clique em Continuar a fila.")
                return
            if self.dados["pausada"]:
                self._agendado = self.proxima_em = None
                return
            time.sleep(self.passo_comfy)
        with self.trava:
            self._agendado = self.proxima_em = None
            if self.rodando() or self.dados["pausada"] or not self.dados["itens"]:
                return
            item = self.dados["itens"].pop(0)
            self._gravar()
            try:
                self.lancar(item["cmd"], item["projeto"], item["modo"], item["tipo"])
            except Exception as e:
                self.dados["itens"].insert(0, item)
                self.pausar(f"Não consegui começar {item['projeto']}: {e}")

    # ---------------------------------------------------------------- ao ligar o estudio

    def ao_ligar(self, retomando=None, motivo_retomada=""):
        """`retomando`: o fio da retomada (retomada.retomar_em_fundo), ou None se ela nao vai relancar nada."""
        if not self.dados["itens"] and not self.dados["pausada"]:
            return
        if retomando is not None:
            # A geracao que caiu volta: a fila segue depois dela, mesmo que tenha pausado pela queda
            falhou = self.dados.get("projeto_falhou")
            if self.dados["pausada"] and falhou:
                self.dados.update(pausada=False, motivo="", projeto_falhou=None)
                self._gravar()

            def vigiar():
                retomando.join()
                time.sleep(2)
                with self.trava:
                    if not self.rodando() and self.dados["itens"] and not self.dados["pausada"]:
                        self.pausar("Não consegui retomar a geração interrompida. Confira e clique em Continuar a fila.")
            threading.Thread(target=vigiar, daemon=True, name="fila-retomada").start()
            return
        if self.dados["itens"] and not self.dados["pausada"]:
            if "caiu de novo" in motivo_retomada:
                self.pausar("A placa caiu duas vezes na mesma geração. A fila pausou: confira e clique em Continuar a fila.")
            else:
                self.pausar("O estúdio foi reiniciado com pedidos na fila. Clique em Continuar a fila para seguir.")
