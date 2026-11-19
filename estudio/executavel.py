"""O estudio aparece como "Estúdio de vídeo" no Gerenciador de Tarefas, e nao como "Python".

O Gerenciador mostra a descricao gravada dentro do .exe (FileDescription), e o do estudio era o pythonw.exe do
ComfyUI portatil. Aqui se faz uma copia dele, estudio.exe, na mesma pasta (para achar o python313.dll e o ._pth),
com a descricao e o icone do estudio. Os processos que o estudio liga (ComfyUI, geracoes) aparecem agrupados
debaixo dele. A copia e refeita se o pythonw.exe ou o icone mudarem.

A assinatura digital do Python deixaria de valer com a mudanca: e tirada, e a copia fica sem assinatura.
Qualquer falha aqui so faz o estudio seguir com o pythonw.exe."""
import ctypes, os, shutil, struct, subprocess, sys
from ctypes import wintypes
from pathlib import Path

import config

NOME = "Estúdio de vídeo"
EXE = config.PYTHONW.with_name("estudio.exe")
ICONE = config.PAGINA / "icone.ico"

RT_ICON, RT_VERSION, RT_GROUP_ICON = 3, 16, 14
IDIOMA = 0x0409  # ingles (EUA), com a pagina de codigo Unicode (1200): o par que o Windows le por padrao


# ---------- recursos de versao ----------

def _no(chave: str, valor: bytes = b"", tipo: int = 1, filhos: bytes = b"", tam_valor: int | None = None) -> bytes:
    """Um bloco do VS_VERSIONINFO: tamanho, tamanho do valor, tipo, chave UTF-16, alinhamento a 4, valor, filhos."""
    corpo = (chave + "\0").encode("utf-16-le")
    cab = 6 + len(corpo)
    pad1 = b"\0" * ((4 - cab % 4) % 4)
    meio = corpo + pad1 + valor
    pad2 = b"\0" * ((4 - (6 + len(meio)) % 4) % 4) if filhos else b""
    dados = meio + pad2 + filhos
    tv = len(valor) if tam_valor is None else tam_valor
    return struct.pack("<HHH", 6 + len(dados), tv, tipo) + dados


def _alinhar(b: bytes) -> bytes:
    return b + b"\0" * ((4 - len(b) % 4) % 4)


def recurso_versao(textos: dict, versao=(1, 0, 0, 0)) -> bytes:
    a, b, c, d = versao
    fixo = struct.pack("<13I", 0xFEEF04BD, 0x00010000, (a << 16) | b, (c << 16) | d, (a << 16) | b, (c << 16) | d,
                       0x3F, 0, 0x00040004, 1, 0, 0, 0)  # VOS_NT_WINDOWS32, VFT_APP
    strings = b"".join(_alinhar(_no(k, (v + "\0").encode("utf-16-le"), 1, tam_valor=len(v) + 1)) for k, v in textos.items())
    tabela = _no(f"{IDIOMA:04x}04b0", filhos=strings)
    sfi = _no("StringFileInfo", filhos=_alinhar(tabela))
    var = _no("Translation", struct.pack("<HH", IDIOMA, 1200), tipo=0)
    vfi = _no("VarFileInfo", filhos=_alinhar(var))
    return _no("VS_VERSION_INFO", fixo, tipo=0, filhos=_alinhar(sfi) + _alinhar(vfi))


def icones_do_ico(dados: bytes) -> tuple[list[bytes], bytes]:
    """Imagens de um .ico e o grupo (GRPICONDIR) que aponta para elas pelos numeros 1, 2, 3..."""
    reservado, tipo, n = struct.unpack_from("<HHH", dados, 0)
    if reservado != 0 or tipo != 1 or n == 0:
        raise ValueError("ícone inválido")
    imagens, grupo = [], struct.pack("<HHH", 0, 1, n)
    for i in range(n):
        w, h, cores, res, planos, bits, tam, ofs = struct.unpack_from("<BBBBHHII", dados, 6 + 16 * i)
        imagens.append(dados[ofs:ofs + tam])
        grupo += struct.pack("<BBBBHHIH", w, h, cores, res, planos, bits, tam, i + 1)
    return imagens, grupo


def tirar_assinatura(caminho: Path) -> None:
    """Zera a entrada da assinatura (diretorio de seguranca do PE) e corta o certificado do fim do arquivo."""
    with open(caminho, "r+b") as f:
        f.seek(0x3C)
        pe = struct.unpack("<I", f.read(4))[0]
        f.seek(pe)
        if f.read(4) != b"PE\0\0":
            raise ValueError("não é um executável do Windows")
        opcional = pe + 24
        f.seek(opcional)
        magico = struct.unpack("<H", f.read(2))[0]
        entrada = opcional + (96 if magico == 0x10B else 112) + 8 * 4  # diretorio 4: IMAGE_DIRECTORY_ENTRY_SECURITY
        f.seek(entrada)
        ofs, tam = struct.unpack("<II", f.read(8))
        if not ofs:
            return
        f.seek(entrada)
        f.write(b"\0" * 8)
        f.seek(0, os.SEEK_END)
        if ofs + tam >= f.tell() - 8:  # o certificado fica no fim; so corta se for mesmo o fim
            f.truncate(ofs)


# ---------- gravar no .exe (API do Windows) ----------

def _api():
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.BeginUpdateResourceW.restype = wintypes.HANDLE
    k.BeginUpdateResourceW.argtypes = [wintypes.LPCWSTR, wintypes.BOOL]
    k.UpdateResourceW.restype = wintypes.BOOL
    k.UpdateResourceW.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, wintypes.WORD, ctypes.c_void_p, wintypes.DWORD]
    k.EndUpdateResourceW.restype = wintypes.BOOL
    k.EndUpdateResourceW.argtypes = [wintypes.HANDLE, wintypes.BOOL]
    k.LoadLibraryExW.restype = wintypes.HMODULE
    k.LoadLibraryExW.argtypes = [wintypes.LPCWSTR, wintypes.HANDLE, wintypes.DWORD]
    k.FreeLibrary.argtypes = [wintypes.HMODULE]
    return k


def _recursos(k, caminho: Path, tipos) -> list:
    """(tipo, nome, idioma) de cada recurso desses tipos. Nome: numero ou texto."""
    achados = []
    nomes_cb = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMODULE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
    idiomas_cb = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMODULE, ctypes.c_void_p, ctypes.c_void_p, wintypes.WORD, ctypes.c_void_p)
    k.EnumResourceNamesW.argtypes = [wintypes.HMODULE, ctypes.c_void_p, nomes_cb, ctypes.c_void_p]
    k.EnumResourceLanguagesW.argtypes = [wintypes.HMODULE, ctypes.c_void_p, ctypes.c_void_p, idiomas_cb, ctypes.c_void_p]
    m = k.LoadLibraryExW(str(caminho), None, 0x22)  # LOAD_LIBRARY_AS_DATAFILE | AS_IMAGE_RESOURCE
    if not m:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        for tipo in tipos:
            nomes = []

            def ao_nome(_m, _t, nome, _p):
                nomes.append(nome if nome <= 0xFFFF else ctypes.wstring_at(nome))
                return True
            k.EnumResourceNamesW(m, tipo, nomes_cb(ao_nome), None)
            for nome in nomes:
                ref = ctypes.c_wchar_p(nome) if isinstance(nome, str) else nome

                def ao_idioma(_m, _t, _n, idioma, _p):
                    achados.append((tipo, nome, idioma))
                    return True
                k.EnumResourceLanguagesW(m, tipo, ctypes.cast(ref, ctypes.c_void_p) if isinstance(nome, str) else nome, idiomas_cb(ao_idioma), None)
    finally:
        k.FreeLibrary(m)
    return achados


def _gravar(k, caminho: Path, apagar: list, novos: list) -> None:
    h = k.BeginUpdateResourceW(str(caminho), False)
    if not h:
        raise ctypes.WinError(ctypes.get_last_error())
    ok = False
    try:
        for tipo, nome, idioma in apagar:
            ref = ctypes.c_wchar_p(nome) if isinstance(nome, str) else nome
            if not k.UpdateResourceW(h, tipo, ctypes.cast(ref, ctypes.c_void_p) if isinstance(nome, str) else nome, idioma, None, 0):
                raise ctypes.WinError(ctypes.get_last_error())
        for tipo, nome, idioma, dados in novos:
            buf = ctypes.create_string_buffer(dados, len(dados))
            if not k.UpdateResourceW(h, tipo, nome, idioma, buf, len(dados)):
                raise ctypes.WinError(ctypes.get_last_error())
        ok = True
    finally:
        if not k.EndUpdateResourceW(h, not ok) and ok:
            raise ctypes.WinError(ctypes.get_last_error())


def criar(origem: Path, destino: Path, icone: Path | None, nome: str = NOME) -> None:
    """Copia `origem` para `destino` com a descricao `nome` e o icone `icone`. Grava num temporario e troca no fim."""
    temporario = destino.with_name(destino.stem + ".novo.exe")
    shutil.copyfile(origem, temporario)
    try:
        tirar_assinatura(temporario)
        k = _api()
        tipos = [RT_VERSION] + ([RT_GROUP_ICON, RT_ICON] if icone else [])
        apagar = _recursos(k, temporario, tipos)
        textos = {"CompanyName": nome, "FileDescription": nome, "FileVersion": "1.0", "InternalName": destino.stem,
                  "LegalCopyright": "Python: Copyright (c) Python Software Foundation", "OriginalFilename": destino.name,
                  "ProductName": nome, "ProductVersion": "1.0"}
        novos = [(RT_VERSION, 1, IDIOMA, recurso_versao(textos))]
        if icone:
            imagens, grupo = icones_do_ico(icone.read_bytes())
            novos += [(RT_ICON, i + 1, IDIOMA, img) for i, img in enumerate(imagens)] + [(RT_GROUP_ICON, 1, IDIOMA, grupo)]
        _gravar(k, temporario, apagar, novos)
        os.replace(temporario, destino)
    finally:
        temporario.unlink(missing_ok=True)


def atualizado(origem: Path = config.PYTHONW, destino: Path = EXE, icone: Path = ICONE) -> bool:
    if not destino.is_file():
        return False
    fontes = [origem] + ([icone] if icone.is_file() else [])
    return destino.stat().st_mtime >= max(f.stat().st_mtime for f in fontes)


def garantir(origem: Path = config.PYTHONW, destino: Path = EXE, icone: Path = ICONE) -> Path | None:
    """O estudio.exe pronto e em dia; None se nao der (o estudio segue com o pythonw.exe)."""
    if sys.platform != "win32" or not origem.is_file():
        return None
    try:
        if not atualizado(origem, destino, icone):
            criar(origem, destino, icone if icone.is_file() else None)
        return destino
    except Exception as e:
        print(f"executavel: sigo com o pythonw.exe ({type(e).__name__}: {e})", flush=True)
        return destino if destino.is_file() else None


def lancador() -> Path:
    """O .exe que liga o estudio: o estudio.exe se der, senao o pythonw.exe."""
    return garantir() or config.PYTHONW


ATALHO_PS = ("$d = [Environment]::GetFolderPath('Desktop'); $l = Join-Path $d ($env:E_NOME + '.lnk'); "
             "if (Test-Path -LiteralPath $l) { $s = (New-Object -ComObject WScript.Shell).CreateShortcut($l); "
             "if ($s.TargetPath -ieq $env:E_DE) { $s.TargetPath = $env:E_PARA; $s.Save(); 'trocado' } }")


def migrar_atalho(exe: Path) -> bool:
    """Instalacoes de antes: o atalho "Estúdio de vídeo" da area de trabalho que abre o pythonw.exe passa a abrir o estudio.exe.
    So mexe se o atalho apontar mesmo para o pythonw.exe deste estudio."""
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ATALHO_PS], capture_output=True, text=True, timeout=60,
                       creationflags=config.SEM_JANELA, env={**os.environ, "E_NOME": NOME, "E_DE": str(config.PYTHONW), "E_PARA": str(exe)})
    return "trocado" in r.stdout


def preparar_em_fundo() -> None:
    """Chamado ao ligar o estudio: faz o estudio.exe se faltar e, se o estudio foi aberto pelo pythonw.exe (atalho antigo),
    aponta o atalho para ele. Aberto pelo estudio.exe ou pelo Abrir estudio.bat (python.exe), o atalho nem e lido."""
    def rodar():
        pelo_pythonw = Path(sys.executable).name.lower() == "pythonw.exe"
        exe = garantir()
        if exe and pelo_pythonw:
            try:
                if migrar_atalho(exe):
                    print("executavel: atalho da área de trabalho agora abre o estudio.exe", flush=True)
            except Exception as e:
                print(f"executavel: não troquei o atalho ({type(e).__name__})", flush=True)
    import threading
    threading.Thread(target=rodar, daemon=True, name="executavel").start()
