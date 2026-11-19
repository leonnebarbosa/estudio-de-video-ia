"""Instalador: extracao dos zips do GitHub (nucleo do ComfyUI e nos extras), sem rede.

O zip do GitHub tem uma pasta de topo com o commit inteiro no nome (repo-<40 caracteres>/). Extrair essa pasta
numa pasta temporaria estourava o limite de 260 caracteres do Windows quando o estudio ficava numa pasta funda
(ex.: Downloads\\estudio-de-video-ia-main\\estudio-de-video-ia-main\\). Agora o conteudo vai direto para o destino."""
import sys, tempfile, unittest, zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "instalador"))
import onboarding  # noqa: E402
from erros import Erro  # noqa: E402

TOPO = "repo-40316cf008b2fd8663263270669eb4da23f89d2c/"


def fazer_zip(pasta: Path, membros: dict) -> Path:
    arq = pasta / "codigo.zip"
    with zipfile.ZipFile(arq, "w") as z:
        for nome, dados in membros.items():
            z.writestr(nome, dados)
    return arq


class TestarExtracao(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_conteudo_vai_direto_para_o_destino_sem_a_pasta_de_topo(self):
        arq = fazer_zip(self.tmp, {TOPO: "", TOPO + "a.txt": "a", TOPO + "workflow_templates/": "",
                                   TOPO + "workflow_templates/exemplo com espaco.json": "{}"})
        destino = self.tmp / "no"
        onboarding._extrair_zip_de_repositorio(arq, destino)
        self.assertEqual((destino / "a.txt").read_text(), "a")
        self.assertEqual((destino / "workflow_templates" / "exemplo com espaco.json").read_text(), "{}")
        # nada da pasta de topo em lugar nenhum: era ela que alongava o caminho
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), ["codigo.zip", "no"])
        self.assertFalse(any(TOPO[:-1] in str(p) for p in self.tmp.rglob("*")))

    def test_destino_existente_recebe_por_cima_e_mantem_o_resto(self):
        destino = self.tmp / "ComfyUI"
        (destino / "models").mkdir(parents=True)
        (destino / "models" / "meu.safetensors").write_text("x")
        (destino / "main.py").write_text("velho")
        arq = fazer_zip(self.tmp, {TOPO + "main.py": "novo"})
        onboarding._extrair_zip_de_repositorio(arq, destino)
        self.assertEqual((destino / "main.py").read_text(), "novo")
        self.assertEqual((destino / "models" / "meu.safetensors").read_text(), "x")

    def test_recusa_caminho_que_sai_do_destino(self):
        arq = fazer_zip(self.tmp, {TOPO + "a.txt": "a", TOPO + "../../fora.txt": "x"})
        with self.assertRaises(Erro):
            onboarding._extrair_zip_de_repositorio(arq, self.tmp / "no")
        self.assertFalse((self.tmp / "fora.txt").exists())
        self.assertFalse((self.tmp / "no").exists())

    def test_recusa_zip_sem_uma_pasta_de_topo(self):
        arq = fazer_zip(self.tmp, {"a.txt": "a", "outra/b.txt": "b"})
        with self.assertRaises(Erro):
            onboarding._extrair_zip_de_repositorio(arq, self.tmp / "no")


if __name__ == "__main__":
    unittest.main()
