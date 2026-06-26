import hashlib
import json
import re
from datetime import datetime, timedelta

from sqlalchemy import func

from app.models import (
    SessionLocal,
    CdaEvent,
    CdaLotResult,
    CdaMarketComparison,
    PriceHistory,
)


def _norm_label(value):
    if not value:
        return None
    txt = re.sub(r"\s+", " ", str(value)).strip().lower()
    txt = (
        txt.replace("ç", "c")
        .replace("ã", "a")
        .replace("á", "a")
        .replace("â", "a")
        .replace("é", "e")
        .replace("ê", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ô", "o")
        .replace("õ", "o")
        .replace("ú", "u")
    )
    return txt or None


def _as_day(value):
    if value is None:
        return None
    return datetime(value.year, value.month, value.day)


def _hash_payload(payload):
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _get_scot_prices_map(session, country_candidates, start_date=None, end_date=None):
    query = session.query(PriceHistory.country, PriceHistory.price, PriceHistory.date)
    if start_date is not None:
        query = query.filter(PriceHistory.date >= start_date)
    if end_date is not None:
        query = query.filter(PriceHistory.date <= end_date)

    rows = query.order_by(PriceHistory.date.asc()).all()
    result = {}
    for country, price, dt in rows:
        if _norm_label(country) not in country_candidates:
            continue
        day = _as_day(dt)
        if day is None:
            continue
        result[day] = float(price) if price is not None else None
    return result


def _nearest_scot_price(scot_prices: dict, ref_day, max_delta_days: int = 3):
    """Busca o preço Scot no dia mais próximo de ref_day (até max_delta_days de diferença)."""
    if not ref_day or not scot_prices:
        return None
    # Tenta exato primeiro
    if ref_day in scot_prices:
        return scot_prices[ref_day]
    # Busca pelo dia mais próximo dentro da janela
    best_price = None
    best_delta = max_delta_days + 1
    for day, price in scot_prices.items():
        delta = abs((day - ref_day).days)
        if delta <= max_delta_days and delta < best_delta and price is not None:
            best_delta = delta
            best_price = price
    return best_price


def build_cda_scot_comparisons(
    scot_country_candidates=("brasil", "brazil"),
    lookback_days=3650,
):
    session = SessionLocal()
    inserted = 0
    updated = 0

    try:
        now = datetime.utcnow()
        cutoff = now - timedelta(days=lookback_days)

        # Usa coalesce(event_date, collected_at) para não perder eventos sem data no slug
        ref_day_expr = func.date_trunc(
            "day",
            func.coalesce(CdaEvent.event_date, CdaEvent.collected_at)
        )

        grouped = (
            session.query(
                ref_day_expr.label("reference_day"),
                CdaLotResult.race_raw,
                CdaLotResult.sex_raw,
                func.avg(CdaLotResult.price_per_kg_brl).label("avg_price_kg"),
                func.avg(CdaLotResult.closed_price_brl).label("avg_closed"),
                func.count(CdaLotResult.id).label("lots_count"),
            )
            .join(CdaEvent, CdaEvent.id == CdaLotResult.event_id)
            .filter(
                func.coalesce(CdaEvent.event_date, CdaEvent.collected_at) >= cutoff
            )
            .filter(CdaLotResult.price_per_kg_brl.isnot(None))
            .filter(CdaLotResult.price_per_kg_brl > 1.0)
            .filter(
                (CdaLotResult.scrape_mode == "individual") |
                (CdaLotResult.scrape_mode.is_(None))
            )
            .group_by(
                ref_day_expr,
                CdaLotResult.race_raw,
                CdaLotResult.sex_raw,
            )
            .all()
        )

        scot_prices = _get_scot_prices_map(
            session,
            country_candidates={_norm_label(c) for c in scot_country_candidates},
            start_date=cutoff,
        )

        for row in grouped:
            ref_day      = _as_day(row.reference_day)
            race_norm    = _norm_label(row.race_raw)
            sex_norm     = _norm_label(row.sex_raw)
            avg_price_kg = float(row.avg_price_kg) if row.avg_price_kg is not None else None
            avg_closed   = float(row.avg_closed)   if row.avg_closed   is not None else None
            lots_count   = int(row.lots_count or 0)

            # R$/@ mantido para retrocompat — usa ×15 (animais jovens; suficiente p/ série histórica)
            avg_arroba = round(avg_price_kg * 15, 2) if avg_price_kg else None

            scot_price = _nearest_scot_price(scot_prices, ref_day, max_delta_days=3)

            # Ratio: compara R$/@ com Scot USD/cab — mantido para séries históricas
            ratio = None
            if avg_arroba and scot_price:
                ratio = avg_arroba / scot_price

            payload = {
                "reference_date": ref_day.isoformat() if ref_day else None,
                "race_norm": race_norm,
                "sex_norm": sex_norm,
                "scot_country": "Brasil",
            }
            hash_key = _hash_payload(payload)

            existing = session.query(CdaMarketComparison).filter_by(hash_key=hash_key).first()
            if existing:
                existing.avg_cda_price_per_kg_brl    = avg_price_kg
                existing.avg_cda_price_per_arroba_brl = avg_arroba
                existing.avg_cda_closed_price_brl     = avg_closed
                existing.lots_count    = lots_count
                existing.scot_price_usd    = scot_price
                existing.cda_to_scot_ratio = ratio
                existing.updated_at        = now
                updated += 1
            else:
                session.add(
                    CdaMarketComparison(
                        reference_date=ref_day,
                        race_norm=race_norm,
                        sex_norm=sex_norm,
                        era_norm=None,
                        avg_cda_price_per_kg_brl=avg_price_kg,
                        avg_cda_price_per_arroba_brl=avg_arroba,
                        avg_cda_closed_price_brl=avg_closed,
                        lots_count=lots_count,
                        scot_country="Brasil",
                        scot_price_usd=scot_price,
                        cda_to_scot_ratio=ratio,
                        hash_key=hash_key,
                        created_at=now,
                        updated_at=now,
                    )
                )
                inserted += 1

        session.commit()
        return {
            "groups": len(grouped),
            "inserted": inserted,
            "updated": updated,
            "scot_days": len(scot_prices),
        }
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
