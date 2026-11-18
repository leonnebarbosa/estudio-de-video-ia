"""Guardar e abrir caminhos de arquivos nos estados dos projetos.
Dentro da pasta do projeto guarda so o nome relativo (a pasta pode mudar de lugar); fora dela, o caminho absoluto.
Valores absolutos gravados antes continuam abrindo como vieram."""
import json, os
from pathlib import Path

import config


def gravar_json(arquivo, dados):
    """Grava o JSON de um jeito que resiste a uma queda do PC: temporário, fsync, troca. Fica o arquivo antigo ou o
    novo, nunca um cheio de zeros (17/11/2026: o PC desligou logo depois de criar um projeto, o estado.json ficou só
    com zeros e o projeto sumiu da lista)."""
    arquivo = Path(arquivo)
    temporario = arquivo.with_name(arquivo.name + ".tmp")
    try:
        texto = json.dumps(dados, ensure_ascii=False, indent=1)
        with open(temporario, "w", encoding="utf-8") as f:
            f.write(texto)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporario, arquivo)
    finally:
        temporario.unlink(missing_ok=True)


def guardar(pasta: Path, arquivo: Path) -> str:
    arquivo = Path(arquivo)
    try:
        return str(arquivo.relative_to(pasta))
    except ValueError:
        return str(arquivo)


def abrir(pasta: Path, valor: str) -> Path:
    p = Path(valor)
    return p if p.is_absolute() else Path(pasta) / p


def guardar_envio(arquivo: Path) -> str:
    return guardar(config.ENVIOS, arquivo)


def abrir_envio(valor: str) -> Path:
    return abrir(config.ENVIOS, valor)
