"""Testes dos temporarios das geracoes na entrada do ComfyUI (entrada_temp.py) e da limpeza no fim da tarefa.

Uso: python -I testar_entrada_temp.py
"""
import os, sys, tempfile, time, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config, entrada_temp, tarefa


class Base(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory(prefix="estudio_entrada_")
        self.addCleanup(d.cleanup)
        self.entrada = Path(d.name) / "input"
        self.entrada.mkdir()
        p = mock.patch.object(config, "ENTRADA", self.entrada)
        p.start()
        self.addCleanup(p.stop)


class Arquivo(Base):
    def test_caminho_e_nome_para_o_grafo(self):
        caminho, nome = entrada_temp.arquivo("proj", "x.png")
        self.assertEqual(nome, "estudio/temp/proj/x.png")
        self.assertEqual(caminho, self.entrada / "estudio" / "temp" / "proj" / "x.png")
        self.assertTrue(caminho.parent.is_dir())
        # O nome com a subpasta leva ao mesmo arquivo quando juntado a entrada (como fazem os scripts)
        self.assertEqual(config.ENTRADA / nome, caminho)
        self.assertEqual(entrada_temp.caminho(nome), caminho)

    def test_outra_entrada(self):
        outra = self.entrada.parent / "outra"
        caminho, nome = entrada_temp.arquivo("p", "a.png", outra)
        self.assertEqual(caminho, outra / "estudio" / "temp" / "p" / "a.png")
        self.assertEqual(nome, "estudio/temp/p/a.png")

    def test_recusa_separador_e_ponto_ponto(self):
        for dono, nome in (("a/b", "x.png"), ("a\\b", "x.png"), ("..", "x.png"), ("p", "../x.png"), ("p", "a/x.png"), ("", "x.png"),
                           ("p", ""), ("c:", "x.png"), ("p", "a..b")):
            with self.assertRaises(ValueError, msg=(dono, nome)):
                entrada_temp.arquivo(dono, nome)
        self.assertFalse((self.entrada / "estudio").exists())

    def test_dono_do_personagem(self):
        self.assertEqual(entrada_temp.dono_personagem("abc"), "personagem_abc")


class Apagar(Base):
    def test_apaga_so_a_pasta_do_dono(self):
        a, _ = entrada_temp.arquivo("p1", "x.png")
        b, _ = entrada_temp.arquivo("p2", "y.png")
        a.write_bytes(b"1")
        b.write_bytes(b"2")
        solta = self.entrada / "na_raiz.png"
        solta.write_bytes(b"3")
        self.assertEqual(entrada_temp.apagar("p1"), [a.parent])
        self.assertFalse(a.parent.exists())
        self.assertTrue(b.is_file() and solta.is_file())

    def test_sem_pasta_ou_nome_ruim_nao_apaga_nada(self):
        self.assertEqual(entrada_temp.apagar("nao_existe"), [])
        self.assertEqual(entrada_temp.apagar(".."), [])
        self.assertEqual(entrada_temp.apagar("../input"), [])
        self.assertEqual(entrada_temp.apagar(""), [])
        self.assertTrue(self.entrada.is_dir())

    def test_arquivo_no_lugar_da_pasta_fica(self):
        entrada_temp.pasta().mkdir(parents=True)
        arq = entrada_temp.pasta() / "p"
        arq.write_bytes(b"x")
        self.assertEqual(entrada_temp.apagar("p"), [])
        self.assertTrue(arq.is_file())

    def test_link_nao_e_seguido(self):
        fora = self.entrada.parent / "fora"
        fora.mkdir()
        (fora / "importante.png").write_bytes(b"x")
        entrada_temp.pasta().mkdir(parents=True)
        link = entrada_temp.pasta() / "p"
        try:
            os.symlink(fora, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("sem permissao para criar link neste Windows")
        self.assertEqual(entrada_temp.apagar("p"), [])
        self.assertTrue((fora / "importante.png").is_file())

    def test_pasta_do_dono(self):
        self.assertIsNone(entrada_temp.pasta_do_dono("p"))
        a, _ = entrada_temp.arquivo("p", "x.png")
        self.assertEqual(entrada_temp.pasta_do_dono("p"), a.parent)
        self.assertIsNone(entrada_temp.pasta_do_dono("../p"))


class Varrer(Base):
    def test_apaga_so_as_pastas_antigas(self):
        velho, _ = entrada_temp.arquivo("velho", "x.png")
        novo, _ = entrada_temp.arquivo("novo", "x.png")
        misto, _ = entrada_temp.arquivo("misto", "x.png")
        for f in (velho, novo, misto):
            f.write_bytes(b"x")
        recente = misto.parent / "recente.png"
        recente.write_bytes(b"x")
        antes = time.time() - 3 * 86400
        for f in (velho, velho.parent, misto, misto.parent):
            os.utime(f, (antes, antes))
        apagadas = entrada_temp.varrer()
        self.assertEqual([p.name for p in apagadas], ["velho"])
        self.assertFalse(velho.parent.exists())
        self.assertTrue(novo.is_file() and recente.is_file())

    def test_agora_e_dias(self):
        a, _ = entrada_temp.arquivo("p", "x.png")
        a.write_bytes(b"x")
        self.assertEqual(entrada_temp.varrer(dias=2), [])
        self.assertEqual([p.name for p in entrada_temp.varrer(dias=2, agora=time.time() + 3 * 86400)], ["p"])

    def test_sem_pasta_de_temporarios(self):
        self.assertEqual(entrada_temp.varrer(), [])


class ApagarProjeto(Base):
    def test_a_pasta_de_temporarios_entra_no_que_sai(self):
        import projetos
        raiz = self.entrada.parent
        for nome in ("projetos", "saida"):
            (raiz / nome).mkdir()
        for alvo, valor in (("PROJETOS", raiz / "projetos"), ("SAIDA", raiz / "saida")):
            p = mock.patch.object(config, alvo, valor)
            p.start()
            self.addCleanup(p.stop)
        (raiz / "projetos" / "proj").mkdir()
        (raiz / "projetos" / "proj" / "estado.json").write_text("{}", encoding="utf-8")
        a, _ = entrada_temp.arquivo("proj", "x.png")
        a.write_bytes(b"x")
        b, _ = entrada_temp.arquivo("proj2", "x.png")
        b.write_bytes(b"x")
        pastas, _ = projetos.alvos_apagar("proj")
        self.assertIn(a.parent, pastas)
        self.assertNotIn(b.parent, pastas)
        a.unlink()
        a.parent.rmdir()
        pastas, _ = projetos.alvos_apagar("proj")
        self.assertEqual(pastas, [raiz / "projetos" / "proj"])


class Proc:
    def __init__(self, codigo):
        self.codigo = codigo

    def wait(self):
        return self.codigo


class FimDaTarefa(Base):
    def esperar(self, projeto, tipo, codigo, parada=False):
        t = tarefa.Tarefa()
        t.projeto, t.tipo, t.parada = projeto, tipo, parada
        with mock.patch.object(tarefa.retomada, "terminou", lambda *a: None), mock.patch.object(t.fila, "terminou", lambda *a: None):
            t._esperar(Proc(codigo))

    def test_terminou_bem_apaga(self):
        a, _ = entrada_temp.arquivo("proj", "x.png")
        a.write_bytes(b"x")
        outro, _ = entrada_temp.arquivo("outro", "x.png")
        outro.write_bytes(b"x")
        self.esperar("proj", "troca", 0)
        self.assertFalse(a.parent.exists())
        self.assertTrue(outro.is_file())

    def test_personagem_usa_o_dono_do_personagem(self):
        a, _ = entrada_temp.arquivo("personagem_abc", "x.png")
        a.write_bytes(b"x")
        b, _ = entrada_temp.arquivo("abc", "x.png")
        b.write_bytes(b"x")
        self.esperar("abc", "personagem", 0)
        self.assertFalse(a.exists())
        self.assertTrue(b.is_file())

    def test_falhou_ou_parada_fica(self):
        a, _ = entrada_temp.arquivo("proj", "x.png")
        a.write_bytes(b"x")
        self.esperar("proj", "imagem", 4)
        self.assertTrue(a.is_file())
        self.esperar("proj", "imagem", 0, parada=True)
        self.assertTrue(a.is_file())


if __name__ == "__main__":
    unittest.main()
