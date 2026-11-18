"""Modelos que so existem nesta maquina: ficam em modelos_locais.json, na pasta do repositorio, fora do git.

O codigo versionado so conhece os modelos oficiais (os dos pacotes do instalador). Um modelo da comunidade testado aqui
entra pelo arquivo local, com os mesmos campos que teria no codigo, e aparece nas telas so nesta maquina. Secoes:
  texto              {id: entrada como em texto_para_imagem.MODELOS_TEXTO}
  wan                {id: entrada como em wan_para_video.MODELOS_WAN}
  ajuda_wan          {id: texto de ajuda do modelo no seletor da aba Imagem para video}
  pagina             {nomes_modelo, segundos_texto, ajuda_passos_texto, segundos_wan, base_wan, nomes_modelo_wan, ajuda_primeira}:
                     mesclados nas tabelas do JavaScript da pagina (ver base.js aplicarExtras)
Arquivo ausente ou quebrado: nenhum extra, e o estudio funciona so com os oficiais."""
import json

import config

ARQUIVO = "modelos_locais.json"
_lido = None


def ler() -> dict:
    global _lido
    if _lido is None:
        try:
            d = json.loads((config.WORKFLOWS / ARQUIVO).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            d = {}
        _lido = d if isinstance(d, dict) else {}
    return _lido


def secao(nome: str) -> dict:
    v = ler().get(nome)
    return v if isinstance(v, dict) else {}
