"""Roda os testes do editar.js (aba Editar video) no Node: editar_pagina.test.js. Pula se o Node nao estiver instalado.

Uso: python -I testar_editar_pagina.py
"""
import shutil, subprocess, sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

NODE = shutil.which("node")


@unittest.skipUnless(NODE, "Node não instalado")
class PaginaEditar(unittest.TestCase):
    def test_editar_js(self):
        r = subprocess.run([NODE, str(Path(__file__).resolve().parent / "editar_pagina.test.js")], capture_output=True, text=True,
                           encoding="utf-8", timeout=60, creationflags=config.SEM_JANELA)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
