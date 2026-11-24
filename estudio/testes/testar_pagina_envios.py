"""Cada area de envio ligada em eventos.js precisa dos elementos que envio.js usa: <tipo>, zona-<tipo>, <tipo>-texto e
<tipo>-aviso. Sem o <tipo>-aviso, escolher a foto quebrava em limparZona antes de enviar e nada acontecia na tela
(foto de personagem novo, 17/11/2026).

Uso: python -I testar_pagina_envios.py
"""
import re, unittest
from pathlib import Path

PAGINA = Path(__file__).resolve().parent.parent / "pagina"


class AreasDeEnvio(unittest.TestCase):
    def test_cada_area_tem_os_elementos_do_envio(self):
        eventos = (PAGINA / "js" / "eventos.js").read_text(encoding="utf-8")
        lista = re.search(r'for \(const tipo of \[([^\]]+)\]\) \{\s*\$\(tipo\)\.addEventListener\("change"', eventos)
        self.assertIsNotNone(lista, "não achei a lista de áreas de envio em eventos.js")
        tipos = re.findall(r'"([^"]+)"', lista.group(1))
        self.assertIn("pfoto", tipos)
        html = (PAGINA / "index.html").read_text(encoding="utf-8")
        ids = set(re.findall(r'\bid="([^"]+)"', html))
        faltam = [i for t in tipos for i in (t, f"zona-{t}", f"{t}-texto", f"{t}-aviso") if i not in ids]
        self.assertEqual(faltam, [], "elementos que faltam no index.html")

    def test_cada_area_tem_o_texto_de_quando_esta_vazia(self):
        # limparZona (envio.js) escreve AJUDA[tipo] na area. Sem a entrada do fundo novo (tfundo), limpar a aba Trocar quebrava:
        # "Usar de novo" de uma troca, "Limpar tudo" e "Tirar o fundo novo" davam "Cannot read properties of undefined" (23/11/2026)
        eventos = (PAGINA / "js" / "eventos.js").read_text(encoding="utf-8")
        lista = re.search(r'for \(const tipo of \[([^\]]+)\]\) \{\s*\$\(tipo\)\.addEventListener\("change"', eventos)
        tipos = re.findall(r'"([^"]+)"', lista.group(1))
        base = (PAGINA / "js" / "base.js").read_text(encoding="utf-8")
        ajuda = re.search(r"const AJUDA = \{(.*?)\};", base, re.S)
        self.assertIsNotNone(ajuda, "não achei a lista AJUDA em base.js")
        chaves = set(re.findall(r"(\w+): \[", ajuda.group(1)))
        self.assertEqual([t for t in tipos if t not in chaves], [], "áreas de envio sem texto em AJUDA (base.js)")


class UsarDeNovo(unittest.TestCase):
    def test_troca_de_video_abre_no_modo_video(self):
        # A aba Trocar lembra o ultimo modo (Foto por padrao): o "Usar de novo" de uma troca de video abria na tela da
        # troca em foto, com o formulario preenchido na outra (23/11/2026)
        eventos = (PAGINA / "js" / "eventos.js").read_text(encoding="utf-8")
        ramo = re.search(r'if \(r\.tipo === "troca"\) \{(.*?)\n      \}', eventos, re.S)
        self.assertIsNotNone(ramo, "não achei o reuso de troca em eventos.js")
        self.assertRegex(ramo.group(1), r'trocarModoTroca\("video"\);\s*irPara\("troca"\)')


if __name__ == "__main__":
    unittest.main()
