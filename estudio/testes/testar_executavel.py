"""estudio.exe: copia do pythonw.exe com o nome e o icone do estudio, para o Gerenciador de Tarefas mostrar "Estúdio de vídeo"."""
import ctypes, os, shutil, struct, subprocess, sys, tempfile, time, unittest
from ctypes import wintypes
from pathlib import Path
from unittest import mock

import config
import executavel


def descricao(exe: Path, campo: str = "FileDescription") -> str:
    """Le um texto da versao do .exe como o Windows (e o Gerenciador de Tarefas) le."""
    v = ctypes.WinDLL("version")
    v.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p]
    v.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    v.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT)]
    n = v.GetFileVersionInfoSizeW(str(exe), None)
    buf = ctypes.create_string_buffer(n)
    assert v.GetFileVersionInfoW(str(exe), 0, n, buf)
    p, tam = ctypes.c_void_p(), wintypes.UINT()
    assert v.VerQueryValueW(buf, r"\VarFileInfo\Translation", ctypes.byref(p), ctypes.byref(tam))
    idioma, pagina = struct.unpack("<HH", ctypes.string_at(p, 4))
    assert v.VerQueryValueW(buf, rf"\StringFileInfo\{idioma:04x}{pagina:04x}\{campo}", ctypes.byref(p), ctypes.byref(tam))
    return ctypes.wstring_at(p)


def assinatura(exe: Path) -> tuple:
    with open(exe, "rb") as f:
        f.seek(0x3C)
        pe = struct.unpack("<I", f.read(4))[0]
        f.seek(pe + 24)
        magico = struct.unpack("<H", f.read(2))[0]
        f.seek(pe + 24 + (96 if magico == 0x10B else 112) + 32)
        return struct.unpack("<II", f.read(8))


@unittest.skipUnless(sys.platform == "win32" and config.PYTHONW.is_file(), "precisa do pythonw.exe do ComfyUI portátil")
class TestarExecutavel(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.exe = self.tmp / "estudio.exe"

    def tearDown(self):
        self._tmp.cleanup()

    def test_copia_tem_o_nome_do_estudio_e_nenhuma_assinatura_quebrada(self):
        executavel.criar(config.PYTHONW, self.exe, executavel.ICONE)
        self.assertEqual(descricao(self.exe), "Estúdio de vídeo")
        self.assertEqual(descricao(self.exe, "ProductName"), "Estúdio de vídeo")
        self.assertEqual(descricao(self.exe, "OriginalFilename"), "estudio.exe")
        self.assertNotEqual(assinatura(config.PYTHONW), (0, 0))  # o original e assinado...
        self.assertEqual(assinatura(self.exe), (0, 0))           # ...a copia nao fica com a assinatura invalida
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), ["estudio.exe"])  # o temporario some

    def test_copia_roda_o_python_quando_fica_na_pasta_dele(self):
        """O estudio.exe de verdade (ao lado do python313.dll) roda o mesmo Python que o pythonw.exe."""
        exe = executavel.garantir()
        self.assertEqual(exe, executavel.EXE)
        saida = self.tmp / "saida.txt"
        r = subprocess.run([str(exe), "-I", "-c", f"import sys; open({str(saida)!r}, 'w').write(sys.prefix)"], timeout=60)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(Path(saida.read_text()), config.PYTHONW.parent)

    def test_refaz_quando_o_pythonw_e_mais_novo_e_nao_refaz_a_toa(self):
        origem = self.tmp / "pythonw.exe"
        shutil.copyfile(config.PYTHONW, origem)
        sem_icone = self.tmp / "nao_tem.ico"
        self.assertFalse(executavel.atualizado(origem, self.exe, sem_icone))
        self.assertEqual(executavel.garantir(origem, self.exe, sem_icone), self.exe)
        self.assertTrue(executavel.atualizado(origem, self.exe, sem_icone))
        with mock.patch.object(executavel, "criar") as criar:
            executavel.garantir(origem, self.exe, sem_icone)
            criar.assert_not_called()
        futuro = time.time() + 60
        os.utime(origem, (futuro, futuro))  # Python atualizado
        self.assertFalse(executavel.atualizado(origem, self.exe, sem_icone))

    def test_falha_ao_criar_segue_com_o_pythonw(self):
        with mock.patch.object(executavel, "criar", side_effect=OSError("disco cheio")):
            self.assertIsNone(executavel.garantir(config.PYTHONW, self.exe, executavel.ICONE))
        with mock.patch.object(executavel, "garantir", return_value=None):
            self.assertEqual(executavel.lancador(), config.PYTHONW)


class TestarPartes(unittest.TestCase):
    def test_icone_vira_grupo_com_numeros_1_2_3(self):
        imgs = [b"A" * 10, b"B" * 20]
        ico = struct.pack("<HHH", 0, 1, 2)
        ofs = 6 + 16 * 2
        for i, img in enumerate(imgs):
            ico += struct.pack("<BBBBHHII", 16 * (i + 1), 16 * (i + 1), 0, 0, 1, 32, len(img), ofs)
            ofs += len(img)
        ico += b"".join(imgs)
        imagens, grupo = executavel.icones_do_ico(ico)
        self.assertEqual(imagens, imgs)
        self.assertEqual(struct.unpack_from("<HHH", grupo), (0, 1, 2))
        self.assertEqual(struct.unpack_from("<BBBBHHIH", grupo, 6)[-1], 1)
        self.assertEqual(struct.unpack_from("<BBBBHHIH", grupo, 20)[-1], 2)

    def test_icone_invalido_e_recusado(self):
        with self.assertRaises(ValueError):
            executavel.icones_do_ico(b"\x89PNG....")

    def test_bloco_de_versao_alinhado(self):
        r = executavel.recurso_versao({"FileDescription": "Estúdio de vídeo"})
        self.assertEqual(struct.unpack_from("<H", r)[0], len(r))
        self.assertIn("Estúdio de vídeo\0".encode("utf-16-le"), r)
        self.assertEqual(struct.unpack_from("<I", r, 40)[0], 0xFEEF04BD)  # VS_FIXEDFILEINFO logo depois da chave


if __name__ == "__main__":
    unittest.main()
