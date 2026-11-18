"""Gravação do estado.json que resiste a uma queda do PC (caminhos.gravar_json).

Em 17/11/2026 o PC desligou de repente logo depois de criar um projeto de troca em foto: o estado.json ficou com o
tamanho certo e só zeros dentro, o projeto sumiu da lista e não dava para apagar pela tela. Gravar num temporário,
forçar a ida ao disco (fsync) e só então trocar pelo arquivo final deixa o estado antigo ou o novo, nunca zeros.

Uso: python -I testar_gravacao_segura.py
"""
import json, re, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import caminhos

ESTUDIO = Path(__file__).resolve().parent.parent


class GravarJson(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.pasta = Path(d.name)

    def test_grava_forca_o_disco_e_nao_deixa_temporario(self):
        arq = self.pasta / "estado.json"
        sincronizados = []
        real = caminhos.os.fsync
        with mock.patch.object(caminhos.os, "fsync", lambda fd: (sincronizados.append(fd), real(fd))):
            caminhos.gravar_json(arq, {"tipo": "texto", "nome": "ação"})
        self.assertEqual(len(sincronizados), 1)
        self.assertEqual(json.loads(arq.read_text(encoding="utf-8")), {"tipo": "texto", "nome": "ação"})
        self.assertEqual([p.name for p in self.pasta.iterdir()], ["estado.json"])

    def test_falha_no_meio_mantem_o_estado_antigo(self):
        arq = self.pasta / "estado.json"
        arq.write_text('{"a": 1}', encoding="utf-8")
        with self.assertRaises(TypeError):
            caminhos.gravar_json(arq, {"a": object()})
        self.assertEqual(json.loads(arq.read_text(encoding="utf-8")), {"a": 1})
        self.assertEqual([p.name for p in self.pasta.iterdir()], ["estado.json"])


class QuemGravaOEstado(unittest.TestCase):
    def test_nenhum_codigo_grava_o_estado_direto(self):
        """O estado.json de um projeto só é gravado por caminhos.gravar_json (gravar direto deixa zeros numa queda)."""
        direto = re.compile(r'(arq_estado|arq_e|estado\.json"\))\.write_text|json\.dumps\((estado|e), ensure_ascii=False, indent=1\)')
        achados = [f"{p.name}:{n}" for p in ESTUDIO.glob("*.py") for n, linha in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
                   if direto.search(linha)]
        self.assertEqual(achados, [])


if __name__ == "__main__":
    unittest.main()
