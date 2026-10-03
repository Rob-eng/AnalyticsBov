"""
Mercado na plataforma web (Fase 4): mesmos dados do bot.

- Praça (DATAGRO): boi, vaca, novilha (R$/@), escala (dias), bônus, diferencial vs SP,
  com variação contra a cotação anterior e o histórico gravado.
- Curva projetada B3: app/futures_projection (boi B3 + basis da praça; vaca e novilha
  pela relação com o boi à vista), últimos 10 pregões.
- Scot internacional (US$/@ carcaça) e leilões CDA (R$/kg vivo por sexo e faixa de peso).
- Valor estimado do rebanho da propriedade com os preços da praça dela.
"""
from datetime import date, timedelta

from sqlalchemy import text

from app.models import SessionLocal
from app.futures_projection import UFS, normalize_uf, load_from_db
from app.web.properties import PropertyError

SPOT_CATS = ("boi", "vaca", "novilha", "escala", "bonus", "diferencial")
# faixas de peso dos leilões CDA (kg vivo) — usadas para reposição (bezerro, garrote, novilha)
CDA_BANDS = ((0, 210, "até 210 kg"), (210, 300, "210–300 kg"), (300, 400, "300–400 kg"), (400, 9999, "acima de 400 kg"))
CDA_DAYS = 30
ARROBA_KG = 15
YIELD = {"boi": 0.52, "touro": 0.52, "vaca": 0.50}   # rendimento de carcaça usual


def _spot(db, uf: str) -> dict:
    """{categoria: {value, unit, ref_date, change, history: [[data, valor], ...]}} da praça."""
    rows = db.execute(text("""
        SELECT category, unit, ref_date, value FROM datagro_quotes
        WHERE region = :uf AND category = ANY(:cats) ORDER BY ref_date
    """), {"uf": uf, "cats": list(SPOT_CATS)}).fetchall()
    out = {}
    for r in rows:
        c = out.setdefault(r.category, {"unit": r.unit, "history": []})
        c["history"].append([r.ref_date.isoformat(), round(r.value, 2)])
    for c in out.values():
        h = c["history"]
        c["value"], c["ref_date"] = h[-1][1], h[-1][0]
        c["change"] = round(h[-1][1] - h[-2][1], 2) if len(h) > 1 else None
    return out


def _praças(db) -> list:
    """Boi, vaca e novilha da última data em cada praça (para comparar)."""
    rows = db.execute(text("""
        SELECT DISTINCT ON (region, category) region, category, value, ref_date FROM datagro_quotes
        WHERE category IN ('boi', 'vaca', 'novilha', 'escala') AND region = ANY(:ufs)
        ORDER BY region, category, ref_date DESC
    """), {"ufs": list(UFS)}).fetchall()
    by = {}
    for r in rows:
        by.setdefault(r.region, {"uf": r.region})[r.category] = round(r.value, 2)
    return sorted(by.values(), key=lambda x: -(x.get("boi") or 0))


def _scot(db) -> dict:
    rows = db.execute(text("""
        SELECT country, price, date FROM price_history
        WHERE date >= (SELECT max(date) FROM price_history) - interval '8 days' ORDER BY date
    """)).fetchall()
    last, prev = {}, {}
    for r in rows:
        if r.country in last:
            prev[r.country] = last[r.country]
        last[r.country] = (r.price, r.date)
    if not last:
        return {"date": None, "countries": []}
    ref = max(d for _, d in last.values())
    countries = [{"country": c, "usd": round(p, 2), "change": round(p - prev[c][0], 2) if c in prev else None}
                 for c, (p, d) in last.items() if d == ref]
    return {"date": ref.date().isoformat(), "countries": sorted(countries, key=lambda x: -x["usd"])}


def _cda(db) -> dict:
    """R$/kg vivo (média ponderada por cabeças) por sexo e faixa de peso, leilões dos últimos 30 dias."""
    since = date.today() - timedelta(days=CDA_DAYS)
    rows = db.execute(text("""
        SELECT lower(left(l.sex_raw, 1)) AS sex, l.weight_kg AS kg, l.price_per_kg_brl AS rkg, COALESCE(l.qtde_animals, 1) AS n
        FROM cda_lot_results l JOIN cda_events e ON e.id = l.event_id
        WHERE e.event_date >= :since AND l.price_per_kg_brl > 0 AND l.weight_kg > 0 AND lower(left(l.sex_raw, 1)) IN ('m', 'f')
    """), {"since": since}).fetchall()
    bands = []
    for lo, hi, label in CDA_BANDS:
        for sex in ("m", "f"):
            sel = [r for r in rows if r.sex == sex and lo <= r.kg < hi]
            heads = sum(r.n for r in sel)
            if heads:
                bands.append({"sex": sex, "band": label, "lo": lo, "hi": hi, "heads": heads, "lots": len(sel),
                              "rkg": round(sum(r.rkg * r.n for r in sel) / heads, 2),
                              "avg_kg": round(sum(r.kg * r.n for r in sel) / heads)})
    events = db.execute(text("""
        SELECT e.event_name, e.event_date, e.event_location, count(l.id) AS lots, sum(COALESCE(l.qtde_animals, 1)) AS heads
        FROM cda_events e LEFT JOIN cda_lot_results l ON l.event_id = e.id
        WHERE e.event_date IS NOT NULL GROUP BY e.id ORDER BY e.event_date DESC LIMIT 6
    """)).fetchall()
    return {"days": CDA_DAYS, "bands": bands,
            "events": [{"name": e.event_name, "date": e.event_date.date().isoformat(), "location": e.event_location,
                        "lots": e.lots, "heads": e.heads} for e in events]}


def market_for(uf: str = None) -> dict:
    uf = normalize_uf(uf)
    db = SessionLocal()
    try:
        out = {"uf": uf, "ufs": list(UFS), "spot": _spot(db, uf), "praças": _praças(db), "scot": _scot(db), "cda": _cda(db)}
    finally:
        db.close()
    try:
        sessions = load_from_db(uf=uf, sessions=10)
        out["curve"] = [{
            "session_date": s["session_date"].isoformat(), "spot_date": s["spot_date"].isoformat(),
            "spot": {k: round(v, 2) for k, v in s["spot"].items()},
            "curve": {cat: [[m.strftime("%Y-%m"), round(v, 2)] for m, v in pts] for cat, pts in s["curve"].items()},
            "methods": {cat: r["method"] for cat, r in s["relations"].items()},
        } for s in sessions]
    except Exception as e:
        print(f"[WEB MERCADO] Curva indisponível ({uf}): {e}", flush=True)
        out["curve"] = []
    return out


# ── Valor estimado do rebanho ────────────────────────────────────────────────

def _br(v: float, nd: int = 2) -> str:
    """Número no formato brasileiro (1.234,56)."""
    return f"{v:,.{nd}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def herd_value_for(property_id: int) -> dict:
    from app.web.herd import CATEGORIES
    from app.web.properties import get_property
    prop = get_property(property_id)
    uf = normalize_uf(prop.get("uf"))
    db = SessionLocal()
    try:
        spot = _spot(db, uf)
        cda = _cda(db)
        lots = db.execute(text("SELECT id, name, category, head_count, avg_weight_kg FROM property_lots WHERE property_id = :pid ORDER BY name"),
                          {"pid": property_id}).fetchall()
    finally:
        db.close()
    if not lots:
        raise PropertyError("Cadastre os lotes do rebanho para estimar o valor.")

    def cda_rkg(sexes, kg):
        sel = [b for b in cda["bands"] if b["sex"] in sexes and b["lo"] <= kg < b["hi"]]
        heads = sum(b["heads"] for b in sel)
        return (round(sum(b["rkg"] * b["heads"] for b in sel) / heads, 2), sel[0]["band"]) if heads else (None, None)

    items, total = [], 0.0
    for l in lots:
        kg = l.avg_weight_kg or CATEGORIES.get(l.category, ("", 450))[1]
        value = price = None
        if l.category in ("boi", "vaca", "touro"):
            ref = "boi" if l.category == "boi" else "vaca"
            at = spot.get(ref, {}).get("value")
            if at:
                arrobas = kg * YIELD[l.category] / ARROBA_KG
                price = at
                value = l.head_count * arrobas * at
                method = (f"Indicador {ref} DATAGRO {uf}: R$ {_br(at)}/@ × {_br(arrobas, 1)} @ por cabeça "
                          f"(rendimento {int(YIELD[l.category] * 100)}%)")
            else:
                method = f"Sem cotação DATAGRO de {ref} para {uf}"
        else:
            sexes = {"bezerro": ("m", "f"), "novilho": ("m",), "novilha": ("f",)}.get(l.category, ("m", "f"))
            rkg, band = cda_rkg(sexes, kg)
            if rkg:
                price = rkg
                value = l.head_count * kg * rkg
                method = f"Leilões CDA ({CDA_DAYS} dias), {'machos' if sexes == ('m',) else 'fêmeas' if sexes == ('f',) else 'machos e fêmeas'} {band}: R$ {_br(rkg)}/kg vivo"
            else:
                method = "Sem leilões CDA recentes nessa faixa de peso"
        if value:
            total += value
        items.append({"id": l.id, "name": l.name, "category": l.category, "heads": l.head_count, "kg": kg,
                      "price": price, "unit": "R$/@" if l.category in ("boi", "vaca", "touro") else "R$/kg",
                      "value": round(value, 2) if value else None,
                      "per_head": round(value / l.head_count, 2) if value else None, "method": method})
    return {"uf": uf, "uf_from_property": prop.get("uf") == uf, "total": round(total, 2), "lots": items,
            "ref_date": spot.get("boi", {}).get("ref_date"),
            "note": "Estimativa de referência: preço de praça e de leilão, sem descontar frete, comissão nem qualidade do lote."}
