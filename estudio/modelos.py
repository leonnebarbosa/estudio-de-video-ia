"""Tela de modelos: lista os arquivos da pasta `models` do ComfyUI, diz o que o aplicativo usa e apaga so o que ele nao usa.

Cuidado maximo ao apagar: esta maquina ja perdeu a pasta de modelos inteira por um apagar mal feito (02/11/2026).
Por isso so se apaga UM arquivo, com os.remove, depois de recusar tudo que for duvidoso (ver `alvo_apagar`).
Nunca se apaga pasta, nunca se segue link ou juncao, e nunca se le o conteudo de um modelo alem do cabecalho."""
import ast, json, os, re, stat, threading, time
from pathlib import Path

import config
import ambiente, tarefa
from validacao import Erro

EXTENSOES = {".safetensors", ".pth", ".ckpt", ".gguf", ".pt", ".bin"}
MAX_CABECALHO = 2**20
MAX_TEXTO = 200
MAX_VALOR_METADADO = 300
ARQUIVO_CATALOGO = "catalogo_modelos.json"  # no git: so os modelos oficiais dos pacotes
CATALOGO_LOCAL = "catalogo_local.json"     # na pasta do repositorio, fora do git: as anotacoes desta maquina, que valem por cima
REPARSE = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT: juncoes e links simbolicos do Windows

CONTINUAR, TROCAR, IMAGEM, ACABAMENTO = "Continuar vídeo", "Trocar personagem", "Imagem para vídeo", "Acabamento"
# Que aba usa o que esta escrito em cada modulo, grafo ou constante
ABA_DO_MODULO = {"continuar_video": CONTINUAR, "trocar_personagem": TROCAR, "imagem_para_video": IMAGEM, "acabamento": ACABAMENTO, "wan_para_video": IMAGEM}
ABA_DA_CONSTANTE = {("validacao", "PADRAO"): CONTINUAR, ("validacao", "PADRAO_TROCA"): TROCAR, ("validacao", "MODELO_ESRGAN"): ACABAMENTO, ("ambiente", "LORAS_TROCA"): TROCAR}
ABA_DO_GRAFO = {"seed_hunter_continuacao_api": CONTINUAR, "troca_personagem_api": TROCAR}
OUTROS = "Aplicativo"
ORDEM_ABAS = [CONTINUAR, TROCAR, IMAGEM, ACABAMENTO, OUTROS]

_trava = threading.Lock()
_cache = {"chave": None, "quando": 0.0, "valor": None}
SEGUNDOS_CACHE = 30


def _eh_link(p: Path) -> bool:
    """Link simbolico, juncao ou qualquer ponto de reanalise. Quem nao da para consultar conta como link."""
    try:
        s = os.lstat(p)
    except OSError:
        return True
    return stat.S_ISLNK(s.st_mode) or bool(getattr(s, "st_file_attributes", 0) & REPARSE)


def _nome_exato(pasta: Path, nome: str) -> bool:
    """O NTFS ignora maiusculas: so vale o nome igual, letra por letra, ao que esta gravado no disco."""
    try:
        return nome in os.listdir(pasta)
    except OSError:
        return False


def _texto(valor, limite=MAX_TEXTO) -> str:
    return str(valor if valor is not None else "").replace("<", "").replace(">", "").strip()[:limite].strip()


def _validar_caminho(caminho) -> list:
    """Caminho relativo a `models`, com `/`. Recusa o que escaparia da pasta ou nao e um nome de arquivo de modelo."""
    if not isinstance(caminho, str) or not caminho or len(caminho) > 300:
        raise Erro("Caminho inválido.")
    if "\0" in caminho or "\\" in caminho or ":" in caminho or caminho.startswith("/"):
        raise Erro("Caminho inválido.")
    partes = caminho.split("/")
    if len(partes) < 2 or any(p in ("", ".", "..") or p != p.strip() or p.endswith(".") for p in partes):
        raise Erro("Caminho inválido.")
    if Path(partes[-1]).suffix.lower() not in EXTENSOES:
        raise Erro("Isso não é um arquivo de modelo.")
    return partes


def _catalogo(caminho: Path) -> dict:
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return dados if isinstance(dados, dict) else {}


def _cabecalho(arq: Path, tamanho: int) -> dict:
    """So o `__metadata__` do cabecalho JSON de um .safetensors: 8 bytes de tamanho e o JSON. O resto do arquivo nao e lido."""
    if arq.suffix.lower() != ".safetensors":
        return {}
    try:
        with arq.open("rb") as f:
            n = int.from_bytes(f.read(8), "little")
            if n <= 0 or n > MAX_CABECALHO or n > tamanho - 8:
                return {}
            h = json.loads(f.read(n))
    except (OSError, ValueError):
        return {}
    m = h.get("__metadata__") if isinstance(h, dict) else None
    if not isinstance(m, dict):
        return {}
    return {str(k): (v if len(v) <= MAX_VALOR_METADADO else v[:MAX_VALOR_METADADO] + "…") for k, v in m.items() if isinstance(v, str)}


def _varrer(models: Path):
    """Arquivos de modelo debaixo de `models`, sem entrar em link nem juncao."""
    pilha = [models]
    while pilha:
        pasta = pilha.pop()
        try:
            entradas = sorted(os.scandir(pasta), key=lambda e: e.name)
        except OSError:
            continue
        for e in entradas:
            p = Path(e.path)
            if _eh_link(p):
                continue
            if e.is_dir(follow_symlinks=False):
                pilha.append(p)
            elif e.is_file(follow_symlinks=False) and p.suffix.lower() in EXTENSOES:
                yield p


def _trechos_do_codigo(codigo: Path) -> list:
    """(texto, aba) de cada pedaco do codigo: cada comando de topo dos .py e cada grafo .json inteiro."""
    trechos = []
    for f in sorted(codigo.glob("*.py")):
        if f.name == "modelos.py":
            continue
        try:
            fonte = f.read_text(encoding="utf-8")
        except OSError:
            continue
        aba = ABA_DO_MODULO.get(f.stem, OUTROS)
        try:
            arvore = ast.parse(fonte)
        except SyntaxError:
            trechos.append((fonte, aba))
            continue
        for no in arvore.body:
            nomes = [a.id for a in getattr(no, "targets", []) if isinstance(a, ast.Name)]
            nomes += [no.target.id] if isinstance(getattr(no, "target", None), ast.Name) else []
            a = next((ABA_DA_CONSTANTE[(f.stem, n)] for n in nomes if (f.stem, n) in ABA_DA_CONSTANTE), aba)
            trechos.append((ast.get_source_segment(fonte, no) or "", a))
    for g in sorted((codigo / "grafos").glob("*.json")):
        try:
            trechos.append((g.read_text(encoding="utf-8"), ABA_DO_GRAFO.get(g.stem, OUTROS)))
        except OSError:
            pass
    # Os modelos da comunidade vem do arquivo local, nao do codigo: sem isto apareceriam como nao usados, com o botao Apagar
    import extras
    for secao, aba in (("texto", OUTROS), ("wan", IMAGEM), ("pagina", OUTROS)):
        if extras.secao(secao):
            trechos.append((json.dumps(extras.secao(secao), ensure_ascii=False), aba))
    return trechos


def _abas_que_usam(arq: Path, trechos: list) -> list:
    """Abas cujo codigo ou grafo cita o arquivo. Alguns nos citam o modelo sem extensao ("BiRefNet-general"): vale entre aspas."""
    nome = arq.name
    entre_aspas = f'"{arq.stem}"' if len(arq.stem) >= 8 else None
    abas = []
    for texto, aba in trechos:
        if (nome in texto or (entre_aspas and entre_aspas in texto)) and aba not in abas:
            abas.append(aba)
    return sorted(abas, key=ORDEM_ABAS.index)


def _eh_opcao_da_aba_continuar(caminho: str) -> bool:
    """Mesma regra de `ambiente.ler_opcoes`, sem precisar do ComfyUI ligado: LoRAs do H3 e modelos ref2va."""
    partes = caminho.split("/")
    if partes[0] == "diffusion_models":
        return "ref2va" in "/".join(partes[1:])
    return partes[0] == "loras" and bool(ambiente.SO_FLUXO_LORA.search(partes[-1])) and not ambiente.FORA_LORA.search("/".join(partes[1:]))


def _uso(caminho: str, arq: Path, trechos: list):
    abas = _abas_que_usam(arq, trechos)
    if abas:
        return "fixo", abas
    if _eh_opcao_da_aba_continuar(caminho):
        return "opcao", [CONTINUAR]
    return "nenhum", []


def listar(models=None, catalogo=None, codigo=None) -> list:
    models = Path(models or config.MODELOS)
    catalogo = Path(catalogo or config.ESTUDIO / ARQUIVO_CATALOGO)
    trechos = _trechos_do_codigo(Path(codigo or config.ESTUDIO))
    notas = {**_catalogo(catalogo), **_catalogo(Path(config.WORKFLOWS) / CATALOGO_LOCAL)}
    itens = []
    for arq in _varrer(models):
        caminho = arq.relative_to(models).as_posix()
        try:
            tamanho = arq.stat().st_size
        except OSError:
            continue  # sumiu entre a varredura e agora
        c = notas.get(caminho) if isinstance(notas.get(caminho), dict) else {}
        uso, onde = _uso(caminho, arq, trechos)
        itens.append({"caminho": caminho, "tipo": caminho.split("/")[0], "tamanho": tamanho,
                      "nome": _texto(c.get("nome")) or arq.name, "serve_para": _texto(c.get("serve_para"), 400), "faz": _texto(c.get("faz"), 600),
                      "testado": _texto(c.get("testado"), 600), "nota": _texto(c.get("nota")), "uso": uso, "onde": onde, "metadados": _cabecalho(arq, tamanho)})
    return sorted(itens, key=lambda i: (i["tipo"].lower(), i["caminho"].lower()))


def esquecer():
    with _trava:
        _cache.update(chave=None, quando=0.0, valor=None)


def listagem() -> list:
    """`listar()` guardada por 30 s; apagar e anotar esquecem."""
    with _trava:
        chave = (str(config.MODELOS), str(config.ESTUDIO))
        if _cache["chave"] != chave or time.time() - _cache["quando"] >= SEGUNDOS_CACHE:
            _cache.update(chave=chave, quando=time.time(), valor=listar())
        return _cache["valor"]


def anotar(caminho: str, nome: str, nota: str) -> None:
    partes = _validar_caminho(caminho)
    models = Path(config.MODELOS)
    alvo = models.joinpath(*partes)
    if not alvo.is_file() or any(_eh_link(p) for p in [models, *(models.joinpath(*partes[:i]) for i in range(1, len(partes) + 1))])             or not all(_nome_exato(models.joinpath(*partes[:i]), partes[i]) for i in range(len(partes))):
        raise Erro("Modelo não encontrado.", 404)
    # Anotacao e coisa desta maquina: vai para o catalogo local, fora do git. O que ja estava no oficial serve de ponto de partida
    arq = Path(config.WORKFLOWS) / CATALOGO_LOCAL
    oficial = _catalogo(Path(config.ESTUDIO) / ARQUIVO_CATALOGO)
    with _trava:
        if arq.exists():
            try:
                dados = json.loads(arq.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                dados = None
            if not isinstance(dados, dict):
                raise Erro("O catálogo de modelos está ilegível; não foi alterado.", 500)
        else:
            dados = {}
        e = dados.get(caminho) if isinstance(dados.get(caminho), dict) else oficial.get(caminho) if isinstance(oficial.get(caminho), dict) else {}
        dados[caminho] = {"nome": _texto(nome), "serve_para": e.get("serve_para", ""), "faz": e.get("faz", ""), "testado": e.get("testado", ""), "nota": _texto(nota)}
        tmp = arq.with_name(arq.name + ".tmp")
        tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        os.replace(tmp, arq)
        _cache.update(chave=None, quando=0.0, valor=None)


def alvo_apagar(caminho: str) -> Path:
    """O arquivo que seria apagado, depois de todas as recusas. Levanta Erro se qualquer coisa for duvidosa."""
    partes = _validar_caminho(caminho)
    if tarefa.tarefa.rodando():
        raise Erro("Há uma geração em andamento. Espere terminar para apagar modelos.", 409)
    models = Path(config.MODELOS)
    if _eh_link(models) or not models.is_dir():
        raise Erro("A pasta de modelos não é uma pasta comum; nada foi apagado.", 403)
    atual = models
    for p in partes[:-1]:
        if not _nome_exato(atual, p):
            raise Erro("O caminho não confere com os nomes gravados no disco (maiúsculas e minúsculas contam); nada foi apagado.", 403)
        atual = atual / p
        if _eh_link(atual) or not atual.is_dir():
            raise Erro("O caminho passa por um link ou por uma pasta que não existe; nada foi apagado.", 403)
    if not _nome_exato(atual, partes[-1]):
        raise Erro("O caminho não confere com os nomes gravados no disco (maiúsculas e minúsculas contam); nada foi apagado.", 403)
    alvo = atual / partes[-1]
    if _eh_link(alvo) or not alvo.is_file():
        raise Erro("Modelo não encontrado, ou não é um arquivo comum.", 404)
    if not alvo.resolve().is_relative_to(models.resolve()) or alvo.resolve().parent != atual.resolve():
        raise Erro("O arquivo fica fora da pasta de modelos; nada foi apagado.", 403)
    uso, onde = _uso("/".join(partes), alvo, _trechos_do_codigo(Path(config.ESTUDIO)))
    if uso == "fixo":
        raise Erro(f"O aplicativo usa este modelo ({', '.join(onde)}); ele não pode ser apagado.", 409)
    return alvo


def apagar(caminho: str, confirmar: bool) -> dict:
    alvo = alvo_apagar(caminho)
    r = {"caminho": caminho, "tamanho": alvo.stat().st_size}
    if confirmar is not True:
        return r
    # Confere de novo logo antes: um link posto entre a primeira conferencia e agora nao pode passar
    alvo = alvo_apagar(caminho)
    try:
        os.remove(alvo)
    except FileNotFoundError:
        esquecer()  # a listagem guardada ainda mostraria o arquivo
        raise Erro("O arquivo não existe mais.", 404)
    except OSError:
        raise Erro("O arquivo está em uso pelo ComfyUI (espere a geração terminar ou feche o estúdio) e não foi apagado.", 409)
    esquecer()
    return r
