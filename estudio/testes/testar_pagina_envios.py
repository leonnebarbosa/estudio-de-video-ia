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


if __name__ == "__main__":
    unittest.main()
