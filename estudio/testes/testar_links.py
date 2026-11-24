"""Testes dos links temporarios do MCP (links.py). Uso: python -I testar_links.py"""
import json, sys, tempfile, time, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import caminhos, config, links


class Base(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.arq = Path(d.name) / "final.mp4"
        self.arq.write_bytes(b"mp4")
        self.pasta = Path(d.name)
        # Nada vai para logs/ de verdade: cada teste grava no seu arquivo
        antigo = links.ARQUIVO
        links.ARQUIVO = self.pasta / "links.json"
        self.addCleanup(setattr, links, "ARQUIVO", antigo)
        links.recarregar()
        self.addCleanup(links._itens.clear)


class Links(Base):
    def test_os_testes_nao_gravam_em_logs(self):
        self.assertIsNotNone(links.ARQUIVO)
        self.assertNotEqual(Path(links.ARQUIVO).parent, config.LOGS)

    def test_baixar_vale_varias_vezes_e_vence(self):
        c = links.criar_baixar(self.arq, "video.mp4")
        self.assertEqual(links.ler(c)["acao"], "baixar")
        self.assertEqual(links.ler(c)["arquivo"], self.arq)
        self.assertEqual(links.ler(c)["nome"], "video.mp4")
        links._itens[c]["criado"] -= links.VALIDADE + 1
        self.assertIsNone(links.ler(c))

    def test_enviar_gasta_uma_vez(self):
        c = links.criar_enviar("foto")
        self.assertEqual(links.ler(c), {"acao": "enviar", "arquivo": None, "nome": None, "tipo": "foto"})
        links.gastar(c)
        self.assertIsNone(links.ler(c))

    def test_codigo_desconhecido_e_tipo_invalido(self):
        self.assertIsNone(links.ler("nao-existe"))
        self.assertIsNone(links.ler(""))
        with self.assertRaises(ValueError):
            links.criar_enviar("pdf")

    def test_limite_de_links(self):
        for _ in range(links.MAXIMO + 5):
            links.criar_enviar("foto")
        self.assertLessEqual(len(links._itens), links.MAXIMO)

    def test_baixar_do_mesmo_arquivo_e_nome_devolve_o_mesmo_codigo(self):
        c = links.criar_baixar(self.arq, "video.mp4")
        self.assertEqual(links.criar_baixar(self.arq, "video.mp4"), c)
        self.assertEqual(links.criar_baixar(str(self.arq), "video.mp4"), c)
        self.assertEqual(len(links._itens), 1)
        # Outro nome ou outro arquivo e outro link
        self.assertNotEqual(links.criar_baixar(self.arq, "outro.mp4"), c)
        outro = self.pasta / "outro.mp4"
        outro.write_bytes(b"x")
        self.assertNotEqual(links.criar_baixar(outro, "video.mp4"), c)
        self.assertEqual(len(links._itens), 3)

    def test_baixar_com_menos_de_meia_validade_nao_e_reaproveitado(self):
        c = links.criar_baixar(self.arq, "video.mp4")
        links._itens[c]["criado"] -= links.VALIDADE / 2 - 60  # ainda resta mais de meia validade
        self.assertEqual(links.criar_baixar(self.arq, "video.mp4"), c)
        links._itens[c]["criado"] -= 120  # agora restam menos de 30 min
        novo = links.criar_baixar(self.arq, "video.mp4")
        self.assertNotEqual(novo, c)
        # O antigo segue valendo ate vencer, e os dois baixam o mesmo arquivo
        self.assertEqual(links.ler(c)["arquivo"], self.arq)
        self.assertEqual(links.ler(novo)["arquivo"], self.arq)
        # O novo e o que passa a ser reaproveitado
        self.assertEqual(links.criar_baixar(self.arq, "video.mp4"), novo)

    def test_baixar_vencido_nao_e_reaproveitado(self):
        c = links.criar_baixar(self.arq, "video.mp4")
        links._itens[c]["criado"] -= links.VALIDADE + 1
        novo = links.criar_baixar(self.arq, "video.mp4")
        self.assertNotEqual(novo, c)
        self.assertEqual(links.ler(novo)["arquivo"], self.arq)

    def test_ao_criar_remove_vencidos_e_os_mais_antigos_saem_primeiro(self):
        velho = links.criar_enviar("foto")
        links._itens[velho]["criado"] -= links.VALIDADE + 1
        links.criar_enviar("audio")
        self.assertNotIn(velho, links._itens)
        primeiro = links.criar_enviar("video")
        for _ in range(links.MAXIMO):
            links.criar_enviar("foto")
        self.assertNotIn(primeiro, links._itens)


class Persistencia(Base):
    """Os links sobrevivem ao religamento do estudio (links.recarregar() esvazia a memoria e le o arquivo de novo)."""

    def test_baixar_vale_depois_de_recarregar(self):
        c = links.criar_baixar(self.arq, "video.mp4")
        links.recarregar()
        self.assertEqual(links.ler(c), {"acao": "baixar", "arquivo": self.arq, "nome": "video.mp4", "tipo": None})
        self.assertIsInstance(links.ler(c)["arquivo"], Path)

    def test_enviar_vale_depois_de_recarregar(self):
        c = links.criar_enviar("audio")
        links.recarregar()
        self.assertEqual(links.ler(c), {"acao": "enviar", "arquivo": None, "nome": None, "tipo": "audio"})

    def test_link_gasto_continua_gasto(self):
        c = links.criar_enviar("foto")
        links.gastar(c)
        links.recarregar()
        self.assertIsNone(links.ler(c))

    def test_o_arquivo_nao_guarda_vencidos_nem_gastos_ao_gravar(self):
        a, b, c = links.criar_enviar("foto"), links.criar_enviar("audio"), links.criar_enviar("video")
        links._itens[b]["criado"] -= links.VALIDADE + 1
        links.gastar(a)  # grava: o gasto e o vencido saem do arquivo
        guardados = json.loads(links.ARQUIVO.read_text(encoding="utf-8"))
        self.assertEqual(set(guardados), {c})
        self.assertIsNone(links.ler(a))
        self.assertIsNone(links.ler(b))
        self.assertIsNotNone(links.ler(c))

    def test_ao_carregar_o_arquivo_perde_o_que_venceu_ou_foi_gasto(self):
        agora = time.time()
        bom = {"acao": "enviar", "arquivo": None, "nome": None, "tipo": "foto", "criado": agora, "gasto": False}
        links.ARQUIVO.write_text(json.dumps({"ok": bom, "velho": {**bom, "criado": agora - links.VALIDADE - 5}, "gasto": {**bom, "gasto": True}}), encoding="utf-8")
        links.recarregar()
        self.assertIsNotNone(links.ler("ok"))
        self.assertEqual(set(json.loads(links.ARQUIVO.read_text(encoding="utf-8"))), {"ok"})

    def test_ao_carregar_sem_nada_a_tirar_nao_regrava(self):
        c = links.criar_enviar("foto")
        antes = links.ARQUIVO.stat().st_mtime_ns
        links.recarregar()
        with mock.patch.object(caminhos, "gravar_json") as gravar:
            self.assertIsNotNone(links.ler(c))
        gravar.assert_not_called()
        self.assertEqual(links.ARQUIVO.stat().st_mtime_ns, antes)

    def test_link_vencido_some_ao_recarregar(self):
        c = links.criar_enviar("foto")
        dados = json.loads(links.ARQUIVO.read_text(encoding="utf-8"))
        dados[c]["criado"] -= links.VALIDADE + 1
        links.ARQUIVO.write_text(json.dumps(dados), encoding="utf-8")
        links.recarregar()
        self.assertIsNone(links.ler(c))
        self.assertNotIn(c, links._itens)

    def test_baixar_de_arquivo_que_sumiu_segue_listado(self):
        c = links.criar_baixar(self.arq, "video.mp4")
        self.arq.unlink()
        links.recarregar()
        i = links.ler(c)
        self.assertIsNotNone(i)
        self.assertFalse(i["arquivo"].is_file())  # quem serve o link responde 404 (servidor.servir_link)

    def test_arquivo_corrompido_vale_como_vazio(self):
        links.ARQUIVO.write_text("{isto nao e json", encoding="utf-8")
        links.recarregar()
        self.assertIsNone(links.ler("qualquer"))
        c = links.criar_enviar("foto")
        self.assertIsNotNone(links.ler(c))

    def test_arquivo_ausente_vale_como_vazio(self):
        links.recarregar()
        self.assertIsNone(links.ler("qualquer"))
        self.assertEqual(links._itens, {})

    def test_itens_malformados_sao_descartados(self):
        agora = time.time()
        bom = {"acao": "enviar", "arquivo": None, "nome": None, "tipo": "foto", "criado": agora, "gasto": False}
        ruins = {"a": "texto", "b": {**bom, "acao": "apagar"}, "c": {**bom, "criado": "ontem"}, "d": {**bom, "tipo": "pdf"},
                 "e": {**bom, "acao": "baixar", "arquivo": None}, "f": {**bom, "arquivo": 7}, "g": {k: v for k, v in bom.items() if k != "gasto"}}
        links.ARQUIVO.write_text(json.dumps({**ruins, "ok": bom}), encoding="utf-8")
        links.recarregar()
        self.assertIsNotNone(links.ler("ok"))
        for c in ruins:
            self.assertIsNone(links.ler(c), c)
        self.assertEqual(set(links._itens), {"ok"})

    def test_esvaziar_a_memoria_na_mao_nao_recarrega_do_arquivo(self):
        c = links.criar_enviar("foto")
        links._itens.clear()
        self.assertIsNone(links.ler(c))

    def test_gravacao_que_falha_ao_gastar_nao_reabre_o_link(self):
        c = links.criar_enviar("foto")
        with mock.patch.object(caminhos, "gravar_json", side_effect=PermissionError):
            links.gastar(c)
            self.assertIsNone(links.ler(c))  # em memoria ja esta gasto
        links.recarregar()
        self.assertIsNone(links.ler(c))

    def test_falha_ao_gravar_nao_quebra(self):
        links.ARQUIVO = self.pasta  # uma pasta no lugar do arquivo
        c = links.criar_enviar("foto")
        self.assertEqual(links.ler(c)["tipo"], "foto")
        links.gastar(c)
        self.assertIsNone(links.ler(c))

    def test_o_arquivo_guarda_o_caminho_como_texto(self):
        c = links.criar_baixar(self.arq, "video.mp4")
        self.assertEqual(json.loads(links.ARQUIVO.read_text(encoding="utf-8"))[c]["arquivo"], str(self.arq))


if __name__ == "__main__":
    unittest.main()
