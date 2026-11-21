"""Mede o tempo real das gerações do estúdio para conferir as estimativas da página.

  coletar   lê os tempos que já ficaram gravados nos projetos (estado.json) e grava projetos/_medicoes/historico.csv
  medir     pede gerações de teste ao estúdio aberto (porta do config), uma de cada vez, e grava projetos/_medicoes/medicoes.csv
            --ate 07:00  para de pedir novas gerações nesse horário
            --so h3|texto  roda só um grupo

Rodar com o Python embutido do ComfyUI, com o estúdio (estudio.pyw) aberto. Retoma de onde parou: caso já medido não roda de novo.
Os projetos de teste se chamam medida_<caso> e podem ser apagados pela galeria depois."""
import csv, json, sys, time, urllib.request, urllib.error
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config

BASE = f"http://127.0.0.1:{config.PORTA}"
SAIDA = config.PROJETOS / "_medicoes"
CENA = "A young woman with curly brown hair sits at a wooden desk in a bright home office, with a laptop and a green plant beside her, soft daylight from a window"


def api(caminho, dados=None, espera=60):
    req = urllib.request.Request(BASE + caminho, data=None if dados is None else json.dumps(dados).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=espera) as r:
            corpo = r.read()
            return 200, (json.loads(corpo) if corpo else {})
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {}


def casos():
    """H3 em texto para vídeo (uma tomada, mesma cena), do mais rápido ao mais lento, e o Texto para imagem."""
    lista = []
    for mp in (0.4746, 0.8, 1.0, 1.1, 1.2):
        for dur in (3.0, 5.0, 7.0, 10.0):
            for primeira in (None, "singularity"):
                lista.append(("h3", f"h3_{mp}_{dur:g}s_{primeira or 'oficial'}", mp, dur, primeira))
    lista.sort(key=lambda c: c[2] * c[3])
    for mp in (0.5, 0.9, 1.3):
        lista.insert(0, ("texto", f"texto_z_{mp}", mp, None, None))
    return lista


def modelo_singularity():
    _, est = api("/api/estado")
    nomes = [m for m in (est.get("opcoes") or {}).get("modelos", []) if "ingularity" in m]
    return nomes[0] if nomes else None


def pedido(grupo, nome, mp, dur, primeira):
    if grupo == "texto":
        return "/api/iniciar-texto", {"projeto": nome, "ajustes": {"modelo": "z_image_turbo", "prompt": CENA, "megapixels": mp, "quantidade": 1, "passos": 8, "semente": 8800}}
    ajustes = {"tipo": "imagem", "modelo": "h3", "proporcao": "16:9 (Widescreen)", "megapixels": mp, "semente": 8800, "quem": "the main character",
               "voz": "natural, friendly voice", "referencias": [], "acabamento": "nenhum", "loras": [], "cena": CENA, "primeira": primeira,
               "tomadas": [{"acao": "She smiles and gestures with her hands while she talks", "fala": "Oi, tudo bem? Hoje eu vou te mostrar uma coisa nova.",
                            "som": "", "camera": "parada", "olhar": True, "duracao": dur}]}
    return "/api/iniciar-imagem", {"projeto": nome, "foto": None, "ajustes": ajustes}


def livre():
    _, est = api("/api/estado")
    t, f = est.get("tarefa") or {}, est.get("fila") or {}
    return not t.get("rodando") and not (f.get("pedidos") or f.get("itens"))


def esperar(nome, limite=3600):
    comeco = time.time()
    while time.time() - comeco < limite:
        time.sleep(20)
        _, est = api("/api/estado")
        t = est.get("tarefa") or {}
        if t.get("projeto") == nome and not t.get("rodando"):
            return t
    return {"codigo": "tempo esgotado"}


def medir(ate, so, so_oficial=False):
    SAIDA.mkdir(exist_ok=True)
    arq = SAIDA / "medicoes.csv"
    feitos = set()
    if arq.exists():
        feitos = {l["caso"] for l in csv.DictReader(arq.open(encoding="utf-8")) if l["codigo"] == "0"}
    sing = modelo_singularity()
    falhas = 0
    for grupo, caso, mp, dur, primeira in casos():
        if (so and grupo != so) or caso in feitos:
            continue
        if primeira == "singularity" and (not sing or so_oficial):
            continue
        if ate and datetime.now().strftime("%H:%M") >= ate and datetime.now().hour < 12:
            print("Horário limite, parando."); break
        while not livre():
            time.sleep(60)
        nome = f"medida_{caso}_{datetime.now():%H%M}".replace(".", "")
        rota, dados = pedido(grupo, nome, mp, dur, sing if primeira else None)
        codigo, resp = api(rota, dados)
        if codigo == 409 and "omfy" in json.dumps(resp, ensure_ascii=False):
            api("/api/ligar-comfy", {}); time.sleep(180)
            codigo, resp = api(rota, dados)
        linha = {"quando": f"{datetime.now():%Y-%m-%d %H:%M}", "caso": caso, "grupo": grupo, "megapixels": mp, "duracao": dur or "", "primeira": primeira or "oficial", "projeto": nome}
        if codigo != 200:
            linha.update(codigo=f"recusado {codigo}", erro=str(resp.get("erro") or resp)[:200])
            print(caso, "recusado:", linha["erro"])
        else:
            print(f"{linha['quando']} {caso} rodando...", flush=True)
            t = esperar(nome)
            linha.update(codigo=str(t.get("codigo")), segundos_total=t.get("segundos"))
            try:
                e = json.loads((config.PROJETOS / nome / "estado.json").read_text(encoding="utf-8"))
                tom = (e.get("tomadas") or [{}])[0]
                linha.update(segundos_tomada=tom.get("segundos"), pico_vram=tom.get("pico_vram"), temp_max=tom.get("temp_max"))
            except Exception:
                pass
            print(f"   código {linha['codigo']}, {linha.get('segundos_total')} s", flush=True)
            falhas = 0 if linha["codigo"] == "0" else falhas + 1
        novo = not arq.exists()
        with arq.open("a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["quando", "caso", "grupo", "megapixels", "duracao", "primeira", "projeto", "codigo", "segundos_total", "segundos_tomada", "pico_vram", "temp_max", "erro"])
            if novo:
                w.writeheader()
            w.writerow(linha)
        if falhas >= 2:
            print("Duas falhas seguidas (a placa pode ter caído). Parando."); break
        time.sleep(15)


def coletar():
    SAIDA.mkdir(exist_ok=True)
    linhas = []
    for pasta in sorted(config.PROJETOS.iterdir()):
        try:
            e = json.loads((pasta / "estado.json").read_text(encoding="utf-8"))
            p = json.loads((pasta / "interface.json").read_text(encoding="utf-8")) if (pasta / "interface.json").exists() else {}
        except Exception:
            continue
        durs = [t.get("duracao") for t in p.get("tomadas", [])]
        for i, t in enumerate(e.get("tomadas") or []):
            if t.get("segundos"):
                linhas.append({"projeto": pasta.name, "tipo": e.get("tipo"), "modelo": p.get("modelo"), "primeira": p.get("primeira") or "", "megapixels": p.get("megapixels"),
                               "tomada": t.get("n", i + 1), "duracao": durs[i] if i < len(durs) else "", "quadros": t.get("total"), "segundos": t.get("segundos"),
                               "pico_vram": t.get("pico_vram"), "temp_max": t.get("temp_max")})
    arq = SAIDA / "historico.csv"
    with arq.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(linhas[0]) if linhas else ["projeto"])
        w.writeheader(); w.writerows(linhas)
    print(f"{len(linhas)} tomadas com tempo gravado em {arq}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] == "coletar":
        coletar()
    elif args[0] == "medir":
        opc = dict(zip(args[1::2], args[2::2]))
        medir(opc.get("--ate"), opc.get("--so"), opc.get("--primeira") == "oficial")
