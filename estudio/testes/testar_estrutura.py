"""Testes da estrutura: caminhos relativos, subprocess sem janela, config como unica fonte de caminhos."""
import ast, sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import caminhos

ESTUDIO = Path(__file__).resolve().parent.parent
GERACOES = {"continuar_video.py", "trocar_personagem.py", "imagem_para_video.py", "acabamento.py"}


def _fontes():
    for f in ESTUDIO.rglob("*.py"):
        if "testes" in f.relative_to(ESTUDIO).parts or "__pycache__" in f.parts:
            continue
        yield f


class Estrutura(unittest.TestCase):
    def test_caminho_relativo_ida_e_volta(self):
        p = Path(r"D:\estudio\projetos\barata")
        self.assertEqual(caminhos.guardar(p, p / "tomada1_v1.mp4"), "tomada1_v1.mp4")
        self.assertEqual(caminhos.abrir(p, caminhos.guardar(p, p / "tomada1_v1.mp4")), p / "tomada1_v1.mp4")
        fora = Path(r"D:\outro\x.mp4")
        self.assertEqual(caminhos.guardar(p, fora), str(fora))
        antigo = r"D:\estudio\continuacao\x\t.mp4"
        self.assertEqual(caminhos.abrir(p, antigo), Path(antigo))

    def test_nenhum_subprocess_sem_janela_oculta(self):
        faltando = []
        for f in _fontes():
            if f.name in GERACOES:
                continue
            for no in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
                if not isinstance(no, ast.Call):
                    continue
                fn = no.func
                nome = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
                dono = fn.value.id if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name) else ""
                if dono == "subprocess" and nome in ("run", "Popen") and "creationflags" not in {k.arg for k in no.keywords}:
                    faltando.append(f"{f.name}:{no.lineno}")
        self.assertEqual(faltando, [])

    def test_sem_avisos_de_sintaxe(self):
        """Escape invalido (como "\\A" fora de string crua) vira SyntaxWarning em toda rodada dos testes."""
        import warnings
        ruins = []
        for f in ESTUDIO.rglob("*.py*"):
            if "__pycache__" in f.parts or f.suffix not in (".py", ".pyw"):
                continue
            with warnings.catch_warnings():
                warnings.simplefilter("error")
                try:
                    compile(f.read_text(encoding="utf-8"), str(f), "exec")
                except SyntaxError as e:
                    ruins.append(f"{f.name}: {e}")
        self.assertEqual(ruins, [])

    def test_taskkill_tem_limite_de_tempo(self):
        """Um taskkill travado nao pode prender o vigia nem o botao Parar."""
        sem = []
        for f in _fontes():
            for no in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
                if isinstance(no, ast.Call) and no.args and isinstance(no.args[0], ast.List) and no.args[0].elts \
                        and isinstance(no.args[0].elts[0], ast.Constant) and no.args[0].elts[0].value == "taskkill" \
                        and "timeout" not in {k.arg for k in no.keywords}:
                    sem.append(f"{f.name}:{no.lineno}")
        self.assertEqual(sem, [])

    def test_comando_comfy_nao_abre_navegador(self):
        """--windows-standalone-build liga o auto-launch do ComfyUI; o estudio ja abre a sua pagina."""
        import config
        self.assertEqual(config.COMANDO_COMFY[1:], ["-u", "-s", r"ComfyUI\main.py", "--windows-standalone-build", "--lowvram", "--reserve-vram", "1.5",
                                                    "--disable-pinned-memory", "--cache-none", "--fast-disk", "--disable-auto-launch", "--port", "8188"])

    def test_scripts_usam_config(self):
        for f in _fontes():
            if f.name == "config.py":
                continue
            for n, linha in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if "Path(__file__)" in linha and "sys.path.insert" not in linha:
                    self.fail(f"{f.name}:{n} usa Path(__file__): {linha.strip()}")


if __name__ == "__main__":
    unittest.main()
