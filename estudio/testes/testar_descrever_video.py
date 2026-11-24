"""Descrever um video de exemplo para o pedido (descrever_video.py): das medidas do rosto por quadro saem frases com o momento de
cada expressao. Sem ComfyUI, sem MediaPipe e sem transcritor: as medidas aqui sao inventadas.

Uso: python -I testar_descrever_video.py
"""
import json, sys, tempfile, types, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import acoes, config, entrada, fidelidade, validacao
import descrever_video as dv

PARADO = {"boca": 0.0, "bico": 0.0, "sorriso": 0.0, "labios_fechados": 0.0, "piscada": 0.0, "olho_arregalado": 0.0, "sobrancelha": 0.3}


def rosto(quadros=120, **trechos):
    """`quadros` linhas paradas; cada trecho e medida=[(inicio, fim, valor), ...] em quadros."""
    linhas = [dict(PARADO) for _ in range(quadros)]
    for medida, partes in trechos.items():
        for ini, fim, valor in partes:
            for i in range(ini, fim):
                linhas[i][medida] = valor
    return linhas


class Intervalos(unittest.TestCase):
    def test_so_conta_o_que_dura(self):
        valores = [0.0] * 10 + [0.9] * 3 + [0.0] * 10 + [0.9] * 12 + [0.0] * 10
        self.assertEqual(dv.intervalos(valores, 0.5, 8), [(23, 35)])

    def test_junta_o_que_esta_separado_por_um_instante(self):
        valores = [0.9] * 10 + [0.0] * 2 + [0.9] * 10 + [0.0] * 20
        self.assertEqual(dv.intervalos(valores, 0.5, 8), [(0, 22)])


class Expressoes(unittest.TestCase):
    def test_sobrancelha_levantada_com_o_momento(self):
        e = dv.eventos(rosto(sobrancelha=[(0, 24, 0.9)]))
        self.assertIn({"inicio": 0.0, "fim": 1.0, "texto": "the character's eyebrows are raised high"}, e)

    def test_sorriso_de_boca_fechada_ou_falando(self):
        fechado = dv.eventos(rosto(sorriso=[(24, 48, 0.7)]))
        self.assertIn("the character gives a closed-lip smile", [x["texto"] for x in fechado])
        falando = dv.eventos(rosto(sorriso=[(24, 48, 0.7)], boca=[(24, 48, 0.3)]))
        self.assertIn("the character smiles with the mouth open", [x["texto"] for x in falando])

    def test_bico_curto_e_vogal_e_nao_entra(self):
        # A vogal "o" ou "u" arredonda os labios por um instante: so um bico que dura vira frase
        textos = [x["texto"] for x in dv.eventos(rosto(bico=[(10, 14, 0.6)]))]
        self.assertNotIn("the character pushes the lips forward into a pout", textos)
        textos = [x["texto"] for x in dv.eventos(rosto(bico=[(10, 24, 0.6)]))]
        self.assertIn("the character pushes the lips forward into a pout", textos)

    def test_piscadas_viram_instantes(self):
        e = [x for x in dv.eventos(rosto(piscada=[(36, 38, 0.8), (78, 80, 0.8)])) if x["texto"] == "the character blinks once, fully"]
        self.assertEqual([(x["inicio"], x["fim"]) for x in e], [(1.5, None), (3.25, None)])

    def test_olho_fechado_por_muito_tempo_nao_e_piscada(self):
        textos = [x["texto"] for x in dv.eventos(rosto(piscada=[(20, 60, 0.9)]))]
        self.assertIn("the character keeps the eyes closed", textos)
        self.assertNotIn("the character blinks once, fully", textos)

    def test_boca_fechada_no_fim(self):
        e = dv.eventos(rosto(boca=[(0, 90, 0.3)]))
        self.assertIn({"inicio": 3.75, "fim": 5.0, "texto": "the character's mouth is closed and still"}, e)

    def test_ordem_do_tempo(self):
        e = dv.eventos(rosto(sorriso=[(60, 90, 0.7)], sobrancelha=[(0, 24, 0.9)], piscada=[(36, 38, 0.8)]))
        self.assertEqual([x["inicio"] for x in e], sorted(x["inicio"] for x in e))


class Texto(unittest.TestCase):
    def test_frases_com_o_tempo_no_formato_do_h3(self):
        t = dv.texto_das_expressoes(rosto(sobrancelha=[(0, 24, 0.9)], piscada=[(36, 38, 0.8)], sorriso=[(96, 120, 0.7)]))
        self.assertIn("From 00:00.000 to 00:01.000, the character's eyebrows are raised high.", t)
        self.assertIn("At 00:01.500, the character blinks once, fully.", t)
        self.assertIn("From 00:04.000 to the end, the character gives a closed-lip smile.", t)

    def test_diz_quando_nunca_arregala_os_olhos(self):
        # Sem isto o modelo tende a exagerar: levantar a sobrancelha vira olho arregalado
        self.assertIn("The character never opens the eyes wide.", dv.texto_das_expressoes(rosto(sobrancelha=[(0, 24, 0.9)])))
        self.assertNotIn("never opens the eyes wide", dv.texto_das_expressoes(rosto(olho_arregalado=[(0, 24, 0.6)])))

    def test_olho_arregalado_mede_pouco(self):
        # No reel de 23/11 a pessoa arregala os olhos e a medida fica em 0,11 a 0,19: com o limite em 0,30 o evento sumia e a frase
        # "nunca arregala" saia no lugar, ao contrario do video
        t = dv.texto_das_expressoes(rosto(olho_arregalado=[(24, 48, 0.18)]))
        self.assertIn("From 00:01.000 to 00:02.000, the character's eyes open wide.", t)
        self.assertNotIn("never opens the eyes wide", t)
        # Na duvida (um pouco aberto, sem chegar a arregalar), nem o evento nem a negacao
        t = dv.texto_das_expressoes(rosto(olho_arregalado=[(24, 48, 0.1)], sobrancelha=[(0, 24, 0.9)]))
        self.assertNotIn("eyes", t.replace("eyebrows", ""))

    def test_rosto_parado_nao_inventa_nada(self):
        self.assertEqual(dv.texto_das_expressoes(rosto(quadros=10)), "")

    def test_sem_sinais_de_referencia(self):
        # O texto vai para o campo da acao, onde < e > sao apagados (imagem_para_video.limpar)
        t = dv.texto_das_expressoes(rosto(sobrancelha=[(0, 24, 0.9)], sorriso=[(60, 90, 0.7)]))
        self.assertNotIn("<", t)
        self.assertNotIn(">", t)

    def test_video_a_30_quadros_por_segundo(self):
        # O reel do Instagram vem a 30: o tempo sai da cadencia do video, e o minimo de duracao vale mais quadros
        t = dv.texto_das_expressoes(rosto(150, sobrancelha=[(0, 30, 0.9)], bico=[(60, 68, 0.6)]), 30)
        self.assertIn("From 00:00.000 to 00:01.000, the character's eyebrows are raised high.", t)
        self.assertNotIn("pout", t)                                   # 8 quadros a 30 sao 0,27 s: ainda e uma vogal


class Fala(unittest.TestCase):
    def test_palavras_vao_para_a_tomada_onde_cai_o_meio_delas(self):
        p = [[0.0, 0.6, "Liberei"], [0.6, 1.0, "meu..."], [1.1, 1.5, "E"], [2.0, 2.6, "aguentou."]]
        self.assertEqual(dv.fala_do_trecho(p, 0.0, 1.2), "Liberei meu...")
        self.assertEqual(dv.fala_do_trecho(p, 1.2, 3.0), "E aguentou.")

    def test_cabe_sem_partir_palavra_nem_frase(self):
        self.assertEqual(dv.caber("um dois tres", 8), "um dois")
        self.assertEqual(dv.caber("curto", 8), "curto")
        # O ponto de "00:01.500" nao e fim de frase
        self.assertEqual(dv.caber("At 00:01.500, a. From 00:02.000 to the end, b.", 20, frases=True), "At 00:01.500, a.")


class Transcricao(unittest.TestCase):
    def _rodar(self, saida, codigo=0, guardar=None):
        def rodar(comando, **k):
            if guardar is not None:
                guardar.extend(comando)
            return types.SimpleNamespace(returncode=codigo, stdout=saida if isinstance(saida, bytes) else json.dumps(saida, ensure_ascii=False).encode("utf-8"))
        return rodar

    def test_sem_transcritor_diz_o_motivo(self):
        with mock.patch.object(dv, "python_do_transcritor", lambda: None):
            self.assertEqual(dv.transcrever("a.wav"), (None, "este computador não tem um transcritor configurado"))

    def test_le_as_palavras_com_acento(self):
        # No primeiro teste a saida veio em cp1252 e "não" virou "n?o": o script escreve bytes UTF-8 e aqui se le UTF-8
        comando = []
        with mock.patch.object(dv, "python_do_transcritor", lambda: "py.exe"), mock.patch.object(config, "MODELO_TRANSCRICAO", "small"):
            r = dv.transcrever("a.wav", rodar=self._rodar({"palavras": [[0, 0.5, "não"]]}, guardar=comando))
        self.assertEqual(r, ([[0.0, 0.5, "não"]], ""))
        self.assertEqual(comando, ["py.exe", "-I", str(dv.TRANSCRITOR), "a.wav", "small", "pt"])

    def test_erro_do_transcritor_vira_motivo(self):
        with mock.patch.object(dv, "python_do_transcritor", lambda: "py.exe"):
            r = dv.transcrever("a.wav", rodar=self._rodar({"erro": "o modelo de transcrição large-v3 não está baixado"}, codigo=4))
            self.assertEqual(r, (None, "o transcritor falhou (o modelo de transcrição large-v3 não está baixado)"))
            self.assertEqual(dv.transcrever("a.wav", rodar=self._rodar(b"Traceback...", codigo=1)), (None, "o transcritor falhou"))

    def test_o_script_do_transcritor_nao_depende_do_estudio(self):
        # Ele roda noutro Python, que nao tem o config nem as bibliotecas do ComfyUI
        fonte = dv.TRANSCRITOR.read_text(encoding="utf-8")
        self.assertNotRegex(fonte, r"(?m)^\s*(import|from) (config|fidelidade|acoes|validacao|cv2|numpy)\b")
        self.assertIn("local_files_only=True", fonte)


class PorTomada(unittest.TestCase):
    def _descrever(self, linhas, sem_rosto=0, palavras=None, motivo="", fps=24):
        with mock.patch.object(fidelidade, "disponivel", lambda: True), mock.patch.object(fidelidade, "curvas", lambda v: (linhas, sem_rosto)), \
             mock.patch.object(dv, "transcrever", lambda a: (palavras, motivo)):
            return dv.descrever("v.mp4", fps, [[0.0, 5.0], [5.0, 10.0]], "a.wav", 2000, 300)

    def test_cada_tomada_conta_o_tempo_do_seu_comeco(self):
        # Cada tomada e gerada sozinha: o que acontece aos 5 s do video e o segundo 0 da tomada 2
        r = self._descrever(rosto(240, sobrancelha=[(120, 144, 0.9)]), palavras=[[0.5, 1.0, "Oi"], [6.0, 6.5, "tchau"]])
        self.assertEqual(r["tomadas"][0], {"acao": "", "fala": "Oi"})
        self.assertIn("From 00:00.000 to 00:01.000, the character's eyebrows are raised high.", r["tomadas"][1]["acao"])
        self.assertEqual(r["tomadas"][1]["fala"], "tchau")
        self.assertTrue(any("Gestos das mãos" in a for a in r["avisos"]))

    def test_sem_transcritor_as_expressoes_saem_e_o_aviso_explica(self):
        r = self._descrever(rosto(240, sorriso=[(0, 48, 0.7)]), palavras=None, motivo="este computador não tem um transcritor configurado")
        self.assertIn("closed-lip smile", r["tomadas"][0]["acao"])
        self.assertEqual([t["fala"] for t in r["tomadas"]], ["", ""])
        self.assertTrue(any(a.startswith("Não transcrevi a fala (este computador") for a in r["avisos"]))

    def test_sem_rosto_nao_inventa_expressao(self):
        r = self._descrever(rosto(240, sorriso=[(0, 48, 0.7)]), sem_rosto=200, palavras=[])
        self.assertEqual([t["acao"] for t in r["tomadas"]], ["", ""])
        self.assertTrue(any("Não achei um rosto" in a for a in r["avisos"]))
        self.assertTrue(any("Não ouvi fala" in a for a in r["avisos"]))

    def test_o_texto_cabe_nos_campos_da_tela(self):
        linhas = rosto(240, piscada=[(i, i + 2, 0.9) for i in range(0, 110, 12)], boca=[(0, 60, 0.3)])
        with mock.patch.object(fidelidade, "disponivel", lambda: True), mock.patch.object(fidelidade, "curvas", lambda v: (linhas, 0)), \
             mock.patch.object(dv, "transcrever", lambda a: ([[0.1 * i, 0.1 * i + 0.05, "palavra"] for i in range(40)], "")):
            r = dv.descrever("v.mp4", 24, [[0.0, 5.0]], "a.wav", 120, 30)
        self.assertLessEqual(len(r["tomadas"][0]["acao"]), 120)
        self.assertTrue(r["tomadas"][0]["acao"].endswith("."))
        self.assertEqual(r["tomadas"][0]["fala"], "palavra palavra palavra")


class Releitura(unittest.TestCase):
    """Mudar a resolucao muda os cortes e a tela pede a leitura de novo: o rosto e a fala do ultimo video ficam guardados."""
    def setUp(self):
        dv._lido.clear()
        self.addCleanup(dv._lido.clear)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.video = Path(self.tmp.name) / "v.mp4"
        self.video.write_bytes(b"video")
        self.medidas, self.transcricoes, self.fala = 0, 0, ([[0.5, 1.0, "Oi"]], "")
        for alvo, nome, valor in ((fidelidade, "disponivel", lambda: True), (fidelidade, "curvas", self._curvas), (dv, "transcrever", self._transcrever)):
            p = mock.patch.object(alvo, nome, valor)
            p.start()
            self.addCleanup(p.stop)

    def _curvas(self, video):
        self.medidas += 1
        return rosto(240, sobrancelha=[(0, 24, 0.9)]), 0

    def _transcrever(self, audio):
        self.transcricoes += 1
        return self.fala

    def test_a_segunda_leitura_do_mesmo_video_nao_mede_de_novo(self):
        a = dv.descrever(self.video, 24, [[0.0, 10.0]], "a.wav", 2000, 300)
        b = dv.descrever(self.video, 24, [[0.0, 5.0], [5.0, 10.0]], "a.wav", 2000, 300)
        self.assertEqual((self.medidas, self.transcricoes), (1, 1))
        self.assertEqual(a["tomadas"][0]["fala"], "Oi")
        self.assertEqual([t["fala"] for t in b["tomadas"]], ["Oi", ""])
        self.assertIn("eyebrows are raised high", b["tomadas"][0]["acao"])

    def test_outro_arquivo_e_lido_do_zero(self):
        dv.descrever(self.video, 24, [[0.0, 10.0]], "a.wav", 2000, 300)
        self.video.write_bytes(b"outro video, maior")
        dv.descrever(self.video, 24, [[0.0, 10.0]], "a.wav", 2000, 300)
        self.assertEqual((self.medidas, self.transcricoes), (2, 2))

    def test_transcricao_que_falhou_e_tentada_de_novo(self):
        self.fala = (None, "a transcrição demorou demais")
        dv.descrever(self.video, 24, [[0.0, 10.0]], "a.wav", 2000, 300)
        self.fala = ([[0.5, 1.0, "Oi"]], "")
        r = dv.descrever(self.video, 24, [[0.0, 10.0]], "a.wav", 2000, 300)
        self.assertEqual((self.medidas, self.transcricoes), (1, 2))
        self.assertEqual(r["tomadas"][0]["fala"], "Oi")


class Pagina(unittest.TestCase):
    PAGINA = Path(__file__).resolve().parent.parent / "pagina"

    def test_o_video_de_exemplo_fica_no_campo_do_audio(self):
        import re
        html = (self.PAGINA / "index.html").read_text(encoding="utf-8")
        campo = re.search(r'<div class="campo so-imagem" id="campo-iaudio">(.*?)<div class="campo so-imagem" id="campo-icenario"', html, re.S)
        self.assertIsNotNone(campo)
        for i in ("zona-ivideo", "ivideo", "ivideo-texto", "ivideo-aviso", "ivideo-nota"):
            self.assertIn(f'id="{i}"', campo.group(1))
        self.assertIn('accept=".mp4"', campo.group(1))

    def test_a_tela_pede_a_leitura_e_trava_o_gerar_enquanto_espera(self):
        imagem = (self.PAGINA / "js" / "imagem.js").read_text(encoding="utf-8")
        self.assertIn('postar("/api/descrever-video", { video: v.arquivo, megapixels: mp })', imagem)
        self.assertIn('if (S.lendoExemplo) falta.push("Lendo o vídeo de exemplo");', imagem)
        # Uma resposta atrasada de um video ja trocado nao pode preencher a tela
        self.assertIn("if (S.ivideo?.arquivo !== v.arquivo) return;", imagem)
        self.assertIn('if (tipo === "ivideo") aoEscolherVideoExemplo(r);', (self.PAGINA / "js" / "envio.js").read_text(encoding="utf-8"))

    def test_tirar_o_audio_ou_limpar_a_tela_tira_o_video_de_exemplo(self):
        import re
        imagem = (self.PAGINA / "js" / "imagem.js").read_text(encoding="utf-8")
        for funcao in ("tirarAudio", "zerarImagem"):
            corpo = re.search(rf"function {funcao}\(\) \{{(.*?)\n\}}", imagem, re.S)
            self.assertIsNotNone(corpo, funcao)
            self.assertIn("tirarVideoExemplo();", corpo.group(1), funcao)

    def test_a_rota_esta_no_servidor(self):
        import servidor
        self.assertIn("/api/descrever-video", servidor.ROTAS_POST)


class Acao(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        pasta = Path(self.tmp.name)
        (pasta / "envios").mkdir()
        (pasta / "entrada").mkdir()
        (pasta / "envios" / "reel.mp4").write_bytes(b"video")
        self.entrada = pasta / "entrada"
        for alvo, nome, valor in ((config, "ENVIOS", pasta / "envios"), (config, "ENTRADA", self.entrada),
                                  (acoes, "examinar_video", lambda v: {"audio": True, "fps": 30.0, "quadros": 300}),
                                  (dv, "som_do_video", lambda v, destino: destino.write_bytes(b"x" * 2000) > 0),
                                  (validacao, "cortes_do_audio", lambda arquivo, mp: ([0] * 160000, [[0.0, 5.0], [5.0, 10.0]])),
                                  (dv, "descrever", self._descrever)):
            p = mock.patch.object(alvo, nome, valor)
            p.start()
            self.addCleanup(p.stop)

    def _descrever(self, video, fps, cortes, audio, max_acao, max_fala):
        self.pedido = (video.name, fps, cortes, audio.name, max_acao, max_fala)
        return {"tomadas": [{"acao": "a", "fala": "f"}, {"acao": "", "fala": ""}], "avisos": ["aviso"]}

    def test_devolve_o_som_e_as_tomadas(self):
        r = acoes.acao_descrever_video({"video": "reel.mp4", "megapixels": 0.5})
        json.dumps(r)
        self.assertEqual(r["audio"], {"arquivo": "exemplo_reel.wav", "duracao": 10.0})
        self.assertEqual(r["tomadas"], [{"acao": "a", "fala": "f"}, {"acao": "", "fala": ""}])
        self.assertEqual(r["avisos"], ["aviso"])
        self.assertTrue((entrada.pasta_envios() / "exemplo_reel.wav").is_file())
        self.assertEqual(self.pedido, ("reel.mp4", 30.0, [[0.0, 5.0], [5.0, 10.0]], "exemplo_reel.wav", validacao.MAX_ACAO, validacao.MAX_FALA))

    def test_video_que_nao_existe_ou_sem_som(self):
        with self.assertRaises(validacao.Erro) as e:
            acoes.acao_descrever_video({"video": "outro.mp4"})
        self.assertEqual(e.exception.codigo, 404)
        with mock.patch.object(acoes, "examinar_video", lambda v: {"audio": False, "fps": 30.0}):
            with self.assertRaises(validacao.Erro) as e:
                acoes.acao_descrever_video({"video": "reel.mp4"})
        self.assertIn("não tem som", str(e.exception))

    def test_um_video_de_cada_vez(self):
        self.assertTrue(acoes._lendo_exemplo.acquire(blocking=False))
        try:
            with self.assertRaises(validacao.Erro) as e:
                acoes.acao_descrever_video({"video": "reel.mp4"})
            self.assertEqual(e.exception.codigo, 409)
        finally:
            acoes._lendo_exemplo.release()
        acoes.acao_descrever_video({"video": "reel.mp4"})              # a trava solta depois de cada leitura


class Configuracao(unittest.TestCase):
    def test_python_do_transcritor_so_vale_se_existir(self):
        self.assertEqual(config._python_transcricao({"python_transcricao": sys.executable}), Path(sys.executable))
        for local in ({}, {"python_transcricao": ""}, {"python_transcricao": "Z:/nao/existe/python.exe"}, {"python_transcricao": 3}):
            self.assertIsNone(config._python_transcricao(local))

    def test_modelo_do_transcritor(self):
        self.assertEqual(config._modelo_transcricao({}), "large-v3")
        self.assertEqual(config._modelo_transcricao({"modelo_transcricao": "small"}), "small")
        self.assertEqual(config._modelo_transcricao({"modelo_transcricao": "x; rm -rf"}), "large-v3")


if __name__ == "__main__":
    unittest.main()
