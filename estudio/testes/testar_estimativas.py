"""Testes de estimativas.py: o tempo estimado das geracoes (as formulas da pagina, em Python) e a frase da fila.
Sem rede, sem GPU e sem ComfyUI: a tarefa e trocada por um duble. Uso: python -I testar_estimativas.py"""
import sys, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import estimativas, tarefa


class Constantes(unittest.TestCase):
    def test_video_h3_fixa_as_constantes_da_pagina(self):
        self.assertEqual(estimativas.video_h3([5], 0.4746), 226)
        self.assertAlmostEqual(estimativas.video_h3([5], 1.2), 496, delta=3)

    def test_video_h3_soma_as_tomadas_e_a_segunda_custa_mais(self):
        um, dois = estimativas.video_h3([5], 0.4746), estimativas.video_h3([5, 5], 0.4746)
        self.assertGreater(dois, 2 * um)  # a tomada que nao e a primeira carrega 48 quadros de contexto
        self.assertEqual(estimativas.video_h3([3, 7], 0.4746), 531)  # 193 + 338: a tomada 7 s com os 48 quadros de contexto

    def test_video_livre_soma_17_por_cento_as_medicoes_do_modo_livre(self):
        # Medido: 5 s a 540p levou 230, 280 e 278 s contra 226 da formula; na maxima, cerca de 580 contra 496
        self.assertAlmostEqual(estimativas.video_livre(5, 0.4746), 264, delta=2)
        self.assertAlmostEqual(estimativas.video_livre(5, 1.2), 580, delta=2)
        self.assertEqual(estimativas.video_livre(5, 0.4746), round(estimativas.video_h3([5], 0.4746) * 1.17))
        self.assertIsInstance(estimativas.video_livre(5, 0.4746), int)

    def test_video_audio_segue_as_medicoes(self):
        # Tomadas do modo audio ja geradas (real contra esta conta): 2,9 s a 0,4746 MP levou 368 s; 4,5 s a 1,1 MP, de 457
        # a 501 s; 8,7 s a 1,2 MP, 1466 s
        self.assertAlmostEqual(estimativas.video_audio([2.9], 0.4746), 295, delta=6)
        self.assertAlmostEqual(estimativas.video_audio([4.5], 1.1), 530, delta=12)
        self.assertEqual(estimativas.video_audio([4.5, 5.9], 1.1), round(estimativas.video_h3([4.5, 5.9], 1.1, pele=True) * 1.15 + 45))
        self.assertIsInstance(estimativas.video_audio([3], 0.4746), int)

    def test_video_h3_pele_natural_multiplica_por_350_sobre_312(self):
        sem = estimativas.video_h3([5], 1.2)
        com = estimativas.video_h3([5], 1.2, pele=True)
        self.assertAlmostEqual(com, sem * 350 / 312, delta=1)

    def test_imagem_fixa_as_constantes_da_pagina(self):
        self.assertEqual(estimativas.imagem("z_image_turbo", 1, 8, 0.9), 25)
        self.assertEqual(estimativas.imagem("chroma_flash", 2, 12, 0.9), 15 + 2 * 35)
        self.assertEqual(estimativas.imagem("qwen21_edit", 1, 8, 0.9), 15 + 55)

    def test_imagem_loras_extras_e_modelo_desconhecido(self):
        self.assertEqual(estimativas.imagem("z_image_turbo", 1, 8, 0.9, n_loras=2), 45)
        # Na edicao cada imagem extra soma 18 s, menos no qwen21_edit
        self.assertEqual(estimativas.imagem("klein_edit", 1, 4, 0.9, n_extras=2, edicao=True), 15 + 25 + 36)
        self.assertEqual(estimativas.imagem("klein_edit", 1, 4, 0.9, n_extras=2, edicao=False), 15 + 25)
        self.assertEqual(estimativas.imagem("qwen21_edit", 1, 8, 0.9, n_extras=2, edicao=True), 15 + 55)
        self.assertEqual(estimativas.imagem("modelo_local", 1, 8, 0.9), 15 + 35)

    def test_texto(self):
        self.assertEqual(estimativas.texto(40), "cerca de 40 s")
        self.assertEqual(estimativas.texto(89), "cerca de 89 s")
        self.assertEqual(estimativas.texto(90), "cerca de 2 min")
        self.assertEqual(estimativas.texto(226), "cerca de 4 min")
        self.assertEqual(estimativas.texto(496), "cerca de 8 min")


class Falsa:
    def __init__(self, rodando=False, itens=0, pausada=False):
        self._rodando = rodando
        self.fila = mock.Mock()
        self.fila.resumo.return_value = {"pausada": pausada, "motivo": "", "intervalo": 15, "proxima_em": None,
                                         "itens": [{"id": f"i{n}", "projeto": f"p{n}", "modo": "gerar", "tipo": "imagem", "criado": 0} for n in range(itens)]}

    def rodando(self):
        return self._rodando


LIVRE = {"ligado": True, "ocupado": False}


class Fila(unittest.TestCase):
    def frase(self, comfy=LIVRE, **k):
        with mock.patch.object(tarefa, "tarefa", Falsa(**k)), mock.patch.object(estimativas, "comfy", lambda: comfy):
            return estimativas.fila()

    def test_comfyui_ocupado_por_fora_nao_promete_inicio(self):
        # 22/11/2026: com alguem gerando direto no ComfyUI, o resumo dizia "A placa está livre" e a confirmacao falhava
        t = self.frase(comfy={"ligado": True, "ocupado": True})
        self.assertIn("O ComfyUI está ocupado", t)
        self.assertNotIn("começa assim que você confirmar", t)
        self.assertIn("ver_estado", t)
        t = self.frase(comfy={"ligado": True, "ocupado": True}, itens=2, pausada=True)
        self.assertIn("O ComfyUI está ocupado", t)

    def test_comfyui_desligado(self):
        t = self.frase(comfy={"ligado": False, "ocupado": False})
        self.assertIn("O ComfyUI está desligado", t)
        self.assertNotIn("começa assim que você confirmar", t)

    def test_com_geracao_do_estudio_ou_fila_ativa_nem_olha_o_comfyui(self):
        def proibido():
            raise AssertionError("não devia consultar o ComfyUI")
        for k in ({"rodando": True}, {"rodando": True, "itens": 2}, {"itens": 1}, {"rodando": True, "pausada": True}):
            with mock.patch.object(tarefa, "tarefa", Falsa(**k)), mock.patch.object(estimativas, "comfy", proibido):
                self.assertIn("entra", estimativas.fila(), k)

    def test_placa_livre(self):
        self.assertEqual(self.frase(), "A placa está livre: começa assim que você confirmar.")

    def test_em_andamento_e_fila(self):
        self.assertEqual(self.frase(rodando=True, itens=2), "Há 1 geração em andamento e 2 na fila: este pedido entra atrás delas.")

    def test_so_em_andamento(self):
        self.assertEqual(self.frase(rodando=True), "Há 1 geração em andamento: este pedido entra na fila atrás dela.")

    def test_so_fila_ativa(self):
        self.assertEqual(self.frase(itens=1), "Há 1 na fila: este pedido entra atrás dela.")

    def test_fila_pausada_com_itens(self):
        self.assertEqual(self.frase(itens=3, pausada=True), "A fila está pausada com 3 pedidos; este começa assim que você confirmar.")
        self.assertEqual(self.frase(itens=1, pausada=True), "A fila está pausada com 1 pedido; este começa assim que você confirmar.")

    def test_fila_pausada_com_geracao_rodando_diz_que_so_comeca_depois_de_retomar_fila(self):
        # parar_geracao sempre pausa a fila: um pedido feito com outra geracao rodando entra na fila pausada e nao comeca sozinho
        self.assertEqual(self.frase(rodando=True, pausada=True),
                         "Há 1 geração em andamento e a fila está pausada: este pedido entra na fila e só começa depois de retomar_fila. Pergunte ao usuário se quer retomar.")
        self.assertEqual(self.frase(rodando=True, itens=2, pausada=True),
                         "Há 1 geração em andamento e a fila está pausada com 2 pedidos: este pedido entra na fila e só começa depois de retomar_fila. Pergunte ao usuário se quer retomar.")
        self.assertEqual(self.frase(rodando=True, itens=1, pausada=True),
                         "Há 1 geração em andamento e a fila está pausada com 1 pedido: este pedido entra na fila e só começa depois de retomar_fila. Pergunte ao usuário se quer retomar.")

    def test_fila_pausada_vazia_conta_como_livre(self):
        self.assertEqual(self.frase(pausada=True), "A placa está livre: começa assim que você confirmar.")


if __name__ == "__main__":
    unittest.main()
