import hashlib
import json
import re
from datetime import datetime
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from app.models import SessionLocal, CdaEvent, CdaLotResult

BASE_URL = "https://www.correadacosta.com.br"
RESULTS_URL = f"{BASE_URL}/resultados"
REQUEST_TIMEOUT = 40
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def _clean_text(value):
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


def _to_float(value):
    if value is None:
        return None
    txt = _clean_text(value)
    if not txt:
        return None
    txt = txt.replace("R$", "").replace("US$", "").replace("@", "")
    txt = txt.replace(".", "").replace(",", ".")
    txt = re.sub(r"[^0-9.\-]", "", txt)
    if not txt:
        return None
    try:
        return float(txt)
    except ValueError:
        return None


def _to_date(value):
    text = _clean_text(value)
    if not text:
        return None
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _normalize_header(value):
    txt = _clean_text(value)
    if not txt:
        return None
    txt = txt.lower()
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
    return txt


def _extract_results_links(html, base_url):
    soup = BeautifulSoup(html, "lxml")
    links = set()
    for anchor in soup.select("a[href]"):
        href = anchor.get("href")
        if not href:
            continue
        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        if parsed.netloc and "correadacosta.com.br" not in parsed.netloc:
            continue
        if "/resultado" in parsed.path:
            links.add(absolute)
    return sorted(links)


def _extract_table_rows(html, source_url):
    soup = BeautifulSoup(html, "lxml")
    rows = []
    for table in soup.find_all("table"):
        headers = [_normalize_header(th.get_text(" ", strip=True)) for th in table.find_all("th")]
        if not headers:
            first_row = table.find("tr")
            if first_row:
                headers = [_normalize_header(c.get_text(" ", strip=True)) for c in first_row.find_all(["th", "td"])]

        for tr in table.find_all("tr"):
            cols = tr.find_all("td")
            if not cols:
                continue
            cells = [_clean_text(td.get_text(" ", strip=True)) for td in cols]
            if not any(cells):
                continue

            mapped = {}
            for i, cell in enumerate(cells):
                key = headers[i] if i < len(headers) and headers[i] else f"col_{i+1}"
                mapped[key] = cell

            rows.append(
                {
                    "source_url": source_url,
                    "cells": mapped,
                    "row_text": " | ".join([c for c in cells if c]),
                }
            )
    return rows


def _infer_lot_payload(row):
    cells = row["cells"]
    keys = list(cells.keys())

    def pick(*candidates):
        for candidate in candidates:
            for key in keys:
                if candidate in key:
                    return cells.get(key)
        return None

    race = pick("raca", "raça", "tipo")
    sex = pick("sexo")
    era = pick("era", "idade", "categoria")
    lot = pick("lote")
    event_name = pick("leilao", "evento", "nome")
    event_date_raw = pick("data")
    location = pick("praca", "praça", "cidade", "local")
    weight_kg = _to_float(pick("peso", "kg"))
    arrobas = _to_float(pick("arroba", "@"))
    closed_price = _to_float(pick("valor fechado", "preco fechado", "preço fechado", "valor", "preco", "preço"))
    arroba_price = _to_float(pick("preco/@", "preço/@", "valor/@", "media/@", "média/@"))

    # Fallback: if no column mapping worked, try values by position.
    if not any([race, sex, era, lot, closed_price, arroba_price]):
        vals = [v for v in cells.values() if v]
        if len(vals) >= 4:
            lot = vals[0]
            race = vals[1] if len(vals) > 1 else None
            sex = vals[2] if len(vals) > 2 else None
            era = vals[3] if len(vals) > 3 else None
            closed_price = _to_float(vals[-1])

    if arroba_price is None and closed_price and arrobas:
        arroba_price = round(closed_price / arrobas, 4)

    event_date = _to_date(event_date_raw)
    return {
        "event_name": _clean_text(event_name),
        "event_date": event_date,
        "event_location": _clean_text(location),
        "lot_ref": _clean_text(lot),
        "race_raw": _clean_text(race),
        "sex_raw": _clean_text(sex),
        "era_raw": _clean_text(era),
        "weight_kg": weight_kg,
        "arrobas": arrobas,
        "closed_price_brl": closed_price,
        "price_per_arroba_brl": arroba_price,
    }


def _build_hash(payload, source_url, row_text):
    stable = {
        "source_url": source_url,
        "event_name": payload.get("event_name"),
        "event_date": payload.get("event_date").isoformat() if payload.get("event_date") else None,
        "lot_ref": payload.get("lot_ref"),
        "race_raw": payload.get("race_raw"),
        "sex_raw": payload.get("sex_raw"),
        "era_raw": payload.get("era_raw"),
        "weight_kg": payload.get("weight_kg"),
        "arrobas": payload.get("arrobas"),
        "closed_price_brl": payload.get("closed_price_brl"),
        "price_per_arroba_brl": payload.get("price_per_arroba_brl"),
        "row_text": row_text,
    }
    raw = json.dumps(stable, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def fetch_cda_history_urls(max_pages=100):
    headers = {"User-Agent": USER_AGENT}
    found = set()

    for page in range(1, max_pages + 1):
        page_url = RESULTS_URL if page == 1 else f"{RESULTS_URL}?page={page}"
        response = requests.get(page_url, timeout=REQUEST_TIMEOUT, headers=headers)
        if response.status_code != 200:
            if page == 1:
                raise RuntimeError(f"Falha ao acessar {page_url}: {response.status_code}")
            break

        links = _extract_results_links(response.text, page_url)
        before = len(found)
        found.update(links)
        if page > 1 and len(found) == before:
            # Pagination ended or no new links found.
            break

    if not found:
        # Fallback to at least parse the listing page itself.
        found.add(RESULTS_URL)
    return sorted(found)


def scrape_cda_url(url):
    headers = {"User-Agent": USER_AGENT}
    response = requests.get(url, timeout=REQUEST_TIMEOUT, headers=headers)
    response.raise_for_status()

    table_rows = _extract_table_rows(response.text, url)
    parsed = []
    for row in table_rows:
        payload = _infer_lot_payload(row)
        # Keep rows that have at least a plausible price or at least category fields.
        if not any(
            [
                payload.get("closed_price_brl"),
                payload.get("price_per_arroba_brl"),
                payload.get("race_raw"),
                payload.get("sex_raw"),
                payload.get("era_raw"),
            ]
        ):
            continue

        payload["hash_key"] = _build_hash(payload, url, row["row_text"])
        payload["row_raw"] = row["row_text"]
        parsed.append(payload)
    return parsed


def _get_or_create_event(session, source_url, payload):
    event_name = payload.get("event_name")
    event_date = payload.get("event_date")
    event_location = payload.get("event_location")

    event = (
        session.query(CdaEvent)
        .filter(CdaEvent.source_url == source_url, CdaEvent.event_name == event_name, CdaEvent.event_date == event_date)
        .first()
    )
    now = datetime.utcnow()
    if event:
        event.event_location = event_location or event.event_location
        event.updated_at = now
        return event

    event = CdaEvent(
        event_name=event_name,
        event_date=event_date,
        event_location=event_location,
        source_url=source_url,
        source_page=RESULTS_URL,
        collected_at=now,
        updated_at=now,
    )
    session.add(event)
    session.flush()
    return event


def persist_cda_results(source_url, parsed_rows):
    session = SessionLocal()
    inserted = 0
    updated = 0
    skipped = 0
    try:
        now = datetime.utcnow()
        for payload in parsed_rows:
            existing = session.query(CdaLotResult).filter(CdaLotResult.hash_key == payload["hash_key"]).first()
            if existing:
                # Touch updated_at only when we confirm presence in source again.
                existing.updated_at = now
                updated += 1
                continue

            event = _get_or_create_event(session, source_url, payload)
            lot = CdaLotResult(
                event_id=event.id if event else None,
                source_url=source_url,
                source_page=RESULTS_URL,
                lot_ref=payload.get("lot_ref"),
                race_raw=payload.get("race_raw"),
                sex_raw=payload.get("sex_raw"),
                era_raw=payload.get("era_raw"),
                weight_kg=payload.get("weight_kg"),
                arrobas=payload.get("arrobas"),
                closed_price_brl=payload.get("closed_price_brl"),
                price_per_arroba_brl=payload.get("price_per_arroba_brl"),
                currency="BRL",
                row_raw=payload.get("row_raw"),
                hash_key=payload["hash_key"],
                collected_at=now,
                updated_at=now,
            )
            session.add(lot)
            inserted += 1

        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    return {"inserted": inserted, "updated": updated, "skipped": skipped}


def run_cda_backfill(max_pages=100, max_urls=None):
    urls = fetch_cda_history_urls(max_pages=max_pages)
    if max_urls:
        urls = urls[:max_urls]

    summary = {
        "urls_discovered": len(urls),
        "urls_processed": 0,
        "rows_scraped": 0,
        "inserted": 0,
        "updated": 0,
        "failed_urls": [],
    }

    for url in urls:
        try:
            parsed = scrape_cda_url(url)
            result = persist_cda_results(url, parsed)
            summary["urls_processed"] += 1
            summary["rows_scraped"] += len(parsed)
            summary["inserted"] += result["inserted"]
            summary["updated"] += result["updated"]
            print(
                f"[CDA] {url} -> rows={len(parsed)} inserted={result['inserted']} updated={result['updated']}",
                flush=True,
            )
        except Exception as exc:
            summary["failed_urls"].append({"url": url, "error": str(exc)})
            print(f"[CDA] ERROR {url}: {exc}", flush=True)

    print(f"[CDA] Backfill summary: {summary}", flush=True)
    return summary


def run_cda_daily_cycle():
    session = SessionLocal()
    try:
        lot_count = session.query(CdaLotResult.id).count()
    finally:
        session.close()

    if lot_count == 0:
        # First run on empty DB: perform a full historical backfill.
        print("[CDA] Empty database detected. Running initial full backfill...", flush=True)
        return run_cda_backfill(max_pages=100, max_urls=None)

    # Daily cycle is incremental after initial load.
    return run_cda_backfill(max_pages=3, max_urls=20)
