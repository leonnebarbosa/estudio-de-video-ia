"""Chaves de acesso remoto: quem chega pela VPN prova quem e com uma chave do local.json (config.REMOTO).
Dois niveis: "operador" (opera o estudio) e "completo" (tudo). A chave vem no cabecalho Authorization: Bearer
ou no cookie estudio_chave. Uso: python -I acesso.py --gerar  (imprime um trecho do local.json; nao grava nada)."""
import hmac, json, secrets, sys
from http.cookies import SimpleCookie
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # com -I a pasta do script nao entra sozinha
import config

PAUSA_ERRO = 1.0  # segundos de espera depois de uma chave errada (dificulta tentativa em serie)
COOKIE = "estudio_chave"


def nivel(chave):
    """"operador", "completo" ou None. Compara em tempo constante e testa os dois niveis sempre."""
    if not isinstance(chave, str) or not chave:
        return None
    achado = None
    for n, valor in config.REMOTO["chaves"].items():
        if hmac.compare_digest(chave.encode("utf-8"), valor.encode("utf-8")):
            achado = n
    return achado


def chave_do_pedido(headers):
    """Chave do pedido: Authorization: Bearer ..., ou o cookie estudio_chave; None se nao houver."""
    auth = headers.get("Authorization") or ""
    if auth[:7].lower() == "bearer " and auth[7:].strip():
        return auth[7:].strip()
    try:
        c = SimpleCookie(headers.get("Cookie") or "")
    except Exception:
        return None
    return c[COOKIE].value if COOKIE in c and c[COOKIE].value else None


def remoto_pronto():
    """True se o local.json tem o IP onde escutar e as duas chaves. O IP ja e validado em config._remoto."""
    r = config.REMOTO
    return bool(r["escutar"]) and "operador" in r["chaves"] and "completo" in r["chaves"]


def _gerar():
    print(json.dumps({"remoto": {"escutar": "<IPv4 da VPN desta maquina>",
                                 "chaves": {"operador": secrets.token_urlsafe(32), "completo": secrets.token_urlsafe(32)}}},
                     indent=2))


if __name__ == "__main__":
    if "--gerar" in sys.argv[1:]:
        _gerar()
    else:
        print(__doc__)
