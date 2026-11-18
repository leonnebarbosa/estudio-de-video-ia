"""Retomar a geracao que um reinicio do PC interrompeu (queda da placa, tela azul).

Ao comecar, a tarefa grava o comando em logs/em_andamento.json. Ao terminar bem, ou parada pelo usuario, apaga.
Quando o estudio liga e acha o arquivo, a geracao morreu: se o PC reiniciou no meio dela, roda o mesmo comando
de novo, uma vez so. Imagem para video, Texto e Continuacao seguem da ultima parte pronta; Troca e Wan recomecam.
Uma Troca volta sem a segunda passagem (upscale), que derrubou a placa 3 vezes seguidas em 11/11/2026: amplia com o
ESRGAN no lugar, se o modelo dele estiver instalado.
"""
import json, threading, time

import config

ARQUIVO = "em_andamento.json"
REINICIOS_VIGIA = "vigia_placa.json"   # gravado pelo vigia_placa.py antes de reiniciar o PC
MAX_RETOMADAS = 1
VALIDADE = 12 * 3600                   # geracao mais antiga que isto nao volta sozinha
ESPERA_COMFY = 15 * 60                 # quanto esperar o ComfyUI ficar pronto depois de ligar o estudio
ultimo_motivo = ""                     # por que retomar_em_fundo nao retomou (a fila usa: "caiu de novo" a deixa pausada)


def _arq():
    return config.LOGS / ARQUIVO


def _gravar_json(arq, dados):
    arq.parent.mkdir(parents=True, exist_ok=True)
    tmp = arq.with_suffix(".tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(arq)


def registrar(texto):
    """Uma linha em logs/estudio.log. Nunca quebra quem chama."""
    try:
        config.LOGS.mkdir(parents=True, exist_ok=True)
        with open(config.LOGS / "estudio.log", "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} retomada: {texto}\n")
    except Exception:
        pass


def gravar(cmd, projeto, modo, tipo, inicio, retomada=0):
    try:
        _gravar_json(_arq(), {"cmd": [str(c) for c in cmd], "projeto": projeto, "modo": modo, "tipo": tipo,
                              "inicio": inicio, "retomada": retomada, "fim": None, "codigo": None})
    except OSError as e:
        registrar(f"nao consegui gravar {ARQUIVO}: {e!r}")


def terminou(codigo, parada):
    """Terminou bem ou foi parada: nada a retomar. Com erro, guarda o codigo: a queda da placa costuma
    derrubar o script antes de o vigia reiniciar o PC, e quem decide se retoma e quem liga o estudio."""
    try:
        if codigo == 0 or parada:
            _arq().unlink(missing_ok=True)
            return
        dados = ler()
        if dados:
            dados["fim"], dados["codigo"] = time.time(), codigo
            _gravar_json(_arq(), dados)
    except OSError as e:
        registrar(f"nao consegui atualizar {ARQUIVO}: {e!r}")


def ler():
    try:
        return json.loads(_arq().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def apagar():
    try:
        _arq().unlink(missing_ok=True)
    except OSError:
        pass


def reinicios_do_vigia():
    try:
        return json.loads((config.LOGS / REINICIOS_VIGIA).read_text(encoding="utf-8")).get("reinicios", [])
    except (OSError, ValueError, AttributeError):
        return []


def hora_do_boot():
    import psutil
    return psutil.boot_time()


def decidir(dados, agora, boot, reinicios):
    """(retomar?, motivo). `boot` e quando o Windows ligou; `reinicios`, quando o vigia da placa mandou reiniciar."""
    if not dados or not dados.get("cmd"):
        return False, "nada em andamento"
    inicio = dados.get("inicio") or 0
    if dados.get("retomada", 0) >= MAX_RETOMADAS:
        return False, "ja tinha sido retomada uma vez e caiu de novo"
    if agora - inicio > VALIDADE:
        return False, "a geracao e de mais de 12 horas atras"
    if boot <= inicio:
        return False, "o PC nao reiniciou depois que ela comecou (o estudio foi fechado ou caiu)"
    if dados.get("fim") is not None and not any(inicio <= r <= boot for r in reinicios):
        return False, f"terminou com erro (codigo {dados.get('codigo')}) e o vigia da placa nao reiniciou o PC"
    return True, "o PC reiniciou no meio da geracao"


def sem_segunda_passagem(projeto):
    """Antes de refazer uma troca que caiu: desliga a segunda passagem no interface.json do projeto e, com o modelo do
    ESRGAN instalado, liga a ampliacao com ele. Devolve True se mudou algo. Nunca quebra quem chama."""
    try:
        arq = config.PROJETOS / projeto / "interface.json"
        p = json.loads(arq.read_text(encoding="utf-8"))
        if p.get("tipo") != "troca" or not p.get("upscale"):
            return False
        import validacao
        p["upscale"] = False
        p["esrgan"] = validacao.MODELO_ESRGAN.is_file()
        p["segunda_passagem_desligada_na_retomada"] = True
        _gravar_json(arq, p)
        registrar(f"{projeto}: segunda passagem desligada para a retomada" + (" (amplia com o ESRGAN)." if p["esrgan"] else " (sem o ESRGAN instalado, sai sem ampliar)."))
        return True
    except Exception as e:
        registrar(f"nao consegui desligar a segunda passagem de {projeto}: {e!r}")
        return False


def pendente():
    """O que o vigia da placa consulta ao entrar no Windows: ha geracao para retomar?"""
    return decidir(ler(), time.time(), hora_do_boot(), reinicios_do_vigia())


def retomar_em_fundo(vigia, tarefa, esperar=ESPERA_COMFY, intervalo=5.0):
    """Chamado ao ligar o estudio. Decide uma vez; se nao for retomar, apaga o arquivo (a geracao dele ja morreu)."""
    dados = ler()
    if not dados:
        return None
    try:
        sim, motivo = decidir(dados, time.time(), hora_do_boot(), reinicios_do_vigia())
    except Exception as e:
        sim, motivo = False, f"erro ao decidir: {e!r}"
    if not sim:
        global ultimo_motivo
        ultimo_motivo = motivo
        registrar(f"nao retomei {dados.get('projeto')}: {motivo}.")
        apagar()
        return None

    def laco():
        limite = time.monotonic() + esperar
        while time.monotonic() < limite:
            if vigia.estado().get("situacao") == "pronto":
                try:
                    if dados.get("tipo") == "troca":
                        sem_segunda_passagem(dados["projeto"])
                    tarefa.relancar(dados)
                    registrar(f"retomando {dados['projeto']} ({dados['tipo']}): {motivo}.")
                except Exception as e:
                    registrar(f"nao consegui retomar {dados.get('projeto')}: {e!r}")
                    apagar()
                return
            time.sleep(intervalo)
        registrar(f"nao retomei {dados.get('projeto')}: o ComfyUI nao ficou pronto em {esperar // 60} min.")
        apagar()

    fio = threading.Thread(target=laco, daemon=True, name="retomada")
    fio.start()
    return fio
