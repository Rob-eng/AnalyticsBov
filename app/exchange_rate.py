"""
Câmbio USD/BRL em tempo real.
Primário: AwesomeAPI (economia.awesomeapi.com.br) — gratuito, sem auth.
Fallback:  BCB PTAX  (olinda.bcb.gov.br) — taxa oficial do Banco Central.
Cache de 6h em memória para não bater a API a cada request.
"""

import time
from datetime import date, timedelta

import requests

_CACHE: dict = {"rate": None, "ts": 0.0}
_TTL = 6 * 3600  # 6 horas
_DEFAULT = 5.90  # fallback se todas as fontes falharem


def get_usd_brl_rate() -> float:
    """Retorna a taxa de câmbio USD → BRL (quanto 1 USD vale em BRL)."""
    now = time.time()
    if _CACHE["rate"] and (now - _CACHE["ts"]) < _TTL:
        return _CACHE["rate"]

    rate = _fetch_awesome() or _fetch_bcb() or _CACHE.get("rate") or _DEFAULT
    _CACHE["rate"] = rate
    _CACHE["ts"] = now
    return rate


def _fetch_awesome():
    try:
        resp = requests.get(
            "https://economia.awesomeapi.com.br/last/USD-BRL",
            timeout=5,
        )
        resp.raise_for_status()
        bid = resp.json()["USDBRL"]["bid"]
        return round(float(bid), 4)
    except Exception:
        return None


def _fetch_bcb():
    """BCB PTAX — tenta o dia de hoje e ontem (não disponível antes das ~13h)."""
    for delta in (0, 1, 2):
        try:
            day = (date.today() - timedelta(days=delta)).strftime("%m-%d-%Y")
            url = (
                "https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/"
                f"CotacaoDolarDia(dataCotacao=@d)?@d=%27{day}%27"
                "&$format=json&$top=1&$select=cotacaoVenda"
            )
            resp = requests.get(url, timeout=6)
            resp.raise_for_status()
            values = resp.json().get("value", [])
            if values:
                return round(float(values[-1]["cotacaoVenda"]), 4)
        except Exception:
            continue
    return None
