"""
Coletor DATAGRO Pecuária — https://portal.datagro.com/pt/livestock

O portal é uma SPA; os números vêm da API pública de preços:
  GET https://precos.api.datagro.com/paginas/?mercado=5&minihome=&pos=1&idioma=pt-br

Resposta: {"quadros": [{"id", "titulo", "ativos": [{"cod", "dados": {...}}]}]}
Cada ativo traz só o último valor ("ult") e sua data ("dia"). O histórico
(/dados/) exige login, então a base é construída com o snapshot diário.

Quadros relevantes (mercado 5):
  49  Indicador do Boi DATAGRO   D_PEPR_<UF>_BR    R$/@
  119 Vacas                      D_PEPRVA_<UF>_BR  R$/@
  120 Novilhas                   D_PEPRNO_<UF>_BR  R$/@
  121 Bônus                      D_PEBO_<UF>_BR    R$/@
  110 Escala                     D_PEES_<UF>_BR    dias
  92  Diferencial %              D_PEDI_<UF>_BR    %
  50  Boi Futuro B3 / 71 CME, 130 Boi no Mundo (semanal), exportações (mensal)
"""

import re
from datetime import datetime

import requests

from app.models import SessionLocal, DatagroQuote

API_URL         = "https://precos.api.datagro.com/paginas/"
LIVESTOCK_ID    = 5
REQUEST_TIMEOUT = 30
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# Prefixo do código D_PE<X>_<UF>_BR → categoria
_PRACA_CATEGORIES = {
    "PR":   "boi",
    "PRVA": "vaca",
    "PRNO": "novilha",
    "BO":   "bonus",
    "ES":   "escala",
    "DI":   "diferencial",
}
_PRACA_RE = re.compile(r"^D_PE([A-Z]+)_([A-Z]{2})_BR$")


def _to_float(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_date(value):
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _unit_from_long_name(long_name):
    text = long_name or ""
    if "BRL/@" in text:
        return "R$/@"
    if "US$/@" in text:
        return "US$/@"
    if "US$/kg" in text:
        return "US$/kg"
    if "Dias" in text:
        return "dias"
    if "%" in text:
        return "%"
    return None


def _classify(code):
    """Retorna (category, region) a partir do código do ativo."""
    m = _PRACA_RE.match(code)
    if m:
        return _PRACA_CATEGORIES.get(m.group(1), m.group(1).lower()), m.group(2)
    if code.startswith("BGI@"):
        return "futuro_b3", "SP"
    if code.startswith("LE@"):
        return "futuro_cme", "US"
    if code.startswith("PEPR_"):
        return "boi_mundo", code.split("_", 1)[1]
    for prefix, category in (("BOEX_", "export_bovinos"), ("SWEX_", "export_suinos"), ("CHEX_", "export_aves")):
        if code.startswith(prefix):
            return category, "BR"
    return "outros", None


def fetch_datagro_livestock() -> list:
    """Busca o snapshot atual de todos os quadros de Pecuária."""
    resp = requests.get(
        API_URL,
        params={"mercado": LIVESTOCK_ID, "minihome": "", "pos": 1, "idioma": "pt-br"},
        headers={"User-Agent": USER_AGENT, "Referer": "https://portal.datagro.com/"},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    payload = resp.json()

    records = []
    for board in payload.get("quadros") or []:
        for asset in board.get("ativos") or []:
            code = asset.get("cod")
            data = asset.get("dados") or {}
            value    = _to_float(data.get("ult"))
            ref_date = _to_date(data.get("dia"))
            if not code or value is None or ref_date is None:
                continue

            category, region = _classify(code)
            records.append({
                "code":        code,
                "board_id":    int(board["id"]) if str(board.get("id", "")).isdigit() else None,
                "board_title": board.get("titulo"),
                "name":        data.get("nome"),
                "long_name":   data.get("longo"),
                "category":    category,
                "region":      region,
                "unit":        _unit_from_long_name(data.get("longo")),
                "ref_date":    ref_date,
                "value":       value,
                "change_pct":  _to_float(data.get("var")),
            })
    return records


def save_datagro_quotes(records: list) -> dict:
    """Upsert por (code, ref_date): o mesmo dia pode ser revisado pela DATAGRO."""
    inserted = updated = 0
    session = SessionLocal()
    try:
        codes = {r["code"] for r in records}
        dates = {r["ref_date"] for r in records}
        existing = {
            (q.code, q.ref_date): q
            for q in session.query(DatagroQuote).filter(
                DatagroQuote.code.in_(codes),
                DatagroQuote.ref_date.in_(dates),
            )
        }

        now = datetime.utcnow()
        for rec in records:
            row = existing.get((rec["code"], rec["ref_date"]))
            if row is None:
                session.add(DatagroQuote(**rec, collected_at=now, updated_at=now))
                inserted += 1
            elif row.value != rec["value"] or row.change_pct != rec["change_pct"]:
                row.value      = rec["value"]
                row.change_pct = rec["change_pct"]
                row.updated_at = now
                updated += 1

        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    return {"fetched": len(records), "inserted": inserted, "updated": updated}


def run_datagro_daily_cycle() -> dict:
    print("[DATAGRO] Coletando cotações de Pecuária...", flush=True)
    records = fetch_datagro_livestock()
    if not records:
        raise RuntimeError("API DATAGRO não retornou nenhuma cotação")
    summary = save_datagro_quotes(records)
    summary["latest_date"] = max(r["ref_date"] for r in records).isoformat()
    print(f"[DATAGRO] ✅ {summary}", flush=True)
    return summary


if __name__ == "__main__":
    for r in fetch_datagro_livestock():
        print(f"{r['ref_date']} {r['category']:12} {r['region'] or '-':3} {r['value']:>12.2f} {r['unit'] or ''}  {r['name']}")
