"""
Scraper Correa da Costa — versão corrigida.

Problemas encontrados na versão anterior:
  1. Filtro de URL usava '/resultado' mas o site usa '/leiloes/<slug>'
  2. Os dados de lote estão nas páginas individuais /leiloes/<slug>,
     renderizados como <tr data-raca="..." data-sexo="..." ...>
  3. A API /HistoricoMedias/Historico requer X-Captcha-Token (impossível
     sem browser), então usamos scraping direto do HTML das páginas.

Estratégia:
  - /resultados → descobre slugs das páginas de leilão (padrão /leiloes/<slug>)
  - Cada página de leilão → extrai <tr> com data-raca / data-sexo / data-peso /
    data-valor ou colunas da <table> padrão
  - Persiste em CdaEvent + CdaLotResult com deduplicação via hash SHA-256
"""

import hashlib
import json
import re
from datetime import datetime
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from app.models import SessionLocal, CdaEvent, CdaLotResult

BASE_URL         = "https://www.correadacosta.com.br"
RESULTS_URL      = f"{BASE_URL}/resultados"
REQUEST_TIMEOUT  = 40
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# ── Utilidades ────────────────────────────────────────────────────────────────

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
    # "quinta, 11/junho/2026" → "11/junho/2026" → tenta vários formatos
    text = re.sub(r"^[a-zçãõáéíóúâêîôûà-]+,\s*", "", text, flags=re.IGNORECASE)
    MONTHS_PT = {
        "janeiro": "01", "fevereiro": "02", "março": "03", "marco": "03",
        "abril": "04", "maio": "05", "junho": "06", "julho": "07",
        "agosto": "08", "setembro": "09", "outubro": "10",
        "novembro": "11", "dezembro": "12",
    }
    for pt, num in MONTHS_PT.items():
        text = text.replace(pt, num)
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return datetime.strptime(text.strip(), fmt)
        except ValueError:
            continue
    return None


def _normalize_header(value):
    txt = _clean_text(value)
    if not txt:
        return None
    txt = txt.lower()
    for src, dst in [
        ("ç","c"),("ã","a"),("á","a"),("â","a"),("é","e"),("ê","e"),
        ("í","i"),("ó","o"),("ô","o"),("õ","o"),("ú","u"),
    ]:
        txt = txt.replace(src, dst)
    return txt

# ── Descoberta de URLs de leilão ──────────────────────────────────────────────

def fetch_cda_auction_urls(max_pages: int = 10) -> list:
    """
    Varre /resultados?page=N e coleta todas as URLs de leilão individuais.
    Padrão: https://www.correadacosta.com.br/leiloes/<slug>
    Exclui URLs de seções genéricas (/leiloes, /leiloes/medias, /resultados, etc.)
    """
    headers = {"User-Agent": USER_AGENT}
    found   = set()

    for page in range(1, max_pages + 1):
        page_url = RESULTS_URL if page == 1 else f"{RESULTS_URL}?page={page}"
        try:
            resp = requests.get(page_url, timeout=REQUEST_TIMEOUT, headers=headers)
        except Exception as e:
            print(f"[CDA] Erro ao acessar {page_url}: {e}", flush=True)
            break

        if resp.status_code != 200:
            if page == 1:
                raise RuntimeError(f"Falha ao acessar {page_url}: {resp.status_code}")
            break

        soup = BeautifulSoup(resp.text, "lxml")
        before = len(found)

        for anchor in soup.select("a[href]"):
            href = anchor.get("href", "")
            absolute = urljoin(BASE_URL, href)
            parsed   = urlparse(absolute)

            # Deve ser do domínio CDA
            if "correadacosta.com.br" not in parsed.netloc:
                continue

            # Deve estar em /leiloes/<slug> com um slug real (não apenas /leiloes)
            path = parsed.path.rstrip("/")
            if not re.match(r"^/leiloes/[^/]+$", path):
                continue

            # Excluir seções genéricas
            if path in ("/leiloes/medias", "/leiloes/agenda"):
                continue
            if "/medias/" in path:
                continue

            found.add(absolute)

        # Se não encontrou novos links, paginação terminou
        if page > 1 and len(found) == before:
            break

    return sorted(found)

# ── Scraping de uma página de leilão ─────────────────────────────────────────

def _extract_event_meta(soup, source_url: str) -> dict:
    """Extrai nome, data e local do evento a partir do <h1> e do texto da página."""
    meta = {"event_name": None, "event_date": None, "event_location": None}

    h1 = soup.find("h1")
    if h1:
        meta["event_name"] = _clean_text(h1.get_text(" ", strip=True))

    # Data: tenta capturar da URL ou de algum texto "dd/mês/aaaa"
    date_match = re.search(r"\d{4}-\d{2}-\d{2}", source_url)
    if date_match:
        meta["event_date"] = datetime.strptime(date_match.group(), "%Y-%m-%d")
    else:
        # Busca no body algo como "quinta, 11/junho/2026"
        body_text = soup.get_text(" ")
        date_match2 = re.search(
            r"(?:segunda|terça|quarta|quinta|sexta|sábado|domingo),?\s*"
            r"(\d{1,2})[/\s]([a-záêçõ]+)[/\s](\d{4})",
            body_text, re.IGNORECASE
        )
        if date_match2:
            day, month_pt, year = date_match2.groups()
            meta["event_date"] = _to_date(f"{day}/{month_pt}/{year}")

    # Local: busca "Local:" no texto
    local_match = re.search(r"[Ll]ocal:\s*(.+?)(?:[/\n]|Leiloeiro|$)", soup.get_text(" "))
    if local_match:
        meta["event_location"] = _clean_text(local_match.group(1))

    return meta


def _parse_lot_rows_from_data_attrs(soup) -> list:
    """
    Extrai lotes dos <tr> com data-attributes:
    data-raca, data-sexo, data-peso, data-valor (ou data-preco)
    """
    rows = []
    for tr in soup.find_all("tr"):
        raca   = tr.get("data-raca") or tr.get("data-classificacao")
        sexo   = tr.get("data-sexo")
        peso   = tr.get("data-peso")
        valor  = tr.get("data-valor") or tr.get("data-preco")
        status = tr.get("data-status", "")

        # Ignora lotes não vendidos
        if status and "vendid" not in status.lower() and "negociad" not in status.lower():
            # Se o status não contém nada útil, tenta mesmo assim
            if status.strip():
                continue

        if not any([raca, sexo, peso, valor]):
            continue

        peso_f  = _to_float(peso)
        valor_f = _to_float(valor)

        # Tenta extrair arroba e preço/@
        arrobas = round(peso_f / 15, 2) if peso_f else None
        arroba_price = round(valor_f / arrobas, 2) if valor_f and arrobas else None

        # Número do lote (pode estar em <td> dentro do <tr>)
        tds = tr.find_all("td")
        lot_ref = _clean_text(tds[0].get_text(" ", strip=True)) if tds else None

        rows.append({
            "lot_ref":            lot_ref,
            "race_raw":           _clean_text(raca),
            "sex_raw":            _clean_text(sexo),
            "era_raw":            None,
            "weight_kg":          peso_f,
            "arrobas":            arrobas,
            "closed_price_brl":   valor_f,
            "price_per_arroba_brl": arroba_price,
        })
    return rows


def _parse_lot_rows_from_table(soup) -> list:
    """
    Fallback: extrai lotes de uma <table> convencional com cabeçalhos.
    Tenta mapear colunas por nome normalizado.
    """
    rows = []
    for table in soup.find_all("table"):
        headers = []
        # Cabeçalhos podem estar em <th> ou primeira <tr>
        ths = table.find_all("th")
        if ths:
            headers = [_normalize_header(th.get_text(" ", strip=True)) for th in ths]
        else:
            first_tr = table.find("tr")
            if first_tr:
                headers = [_normalize_header(c.get_text(" ", strip=True))
                           for c in first_tr.find_all(["th", "td"])]

        def pick_idx(*candidates):
            for c in candidates:
                for i, h in enumerate(headers):
                    if h and c in h:
                        return i
            return None

        idx_lot    = pick_idx("lote")
        idx_raca   = pick_idx("raca", "raça", "classificacao", "tipo")
        idx_sexo   = pick_idx("sexo")
        idx_era    = pick_idx("era", "idade", "categoria")
        idx_peso   = pick_idx("peso", "kg")
        idx_arr    = pick_idx("arroba", "@")
        idx_valor  = pick_idx("valor fechado", "preco fechado", "preco", "valor")
        idx_prarr  = pick_idx("preco/@", "preço/@", "valor/@", "media/@")

        for tr in table.find_all("tr"):
            tds = tr.find_all("td")
            if not tds:
                continue
            cells = [_clean_text(td.get_text(" ", strip=True)) for td in tds]
            if not any(cells):
                continue

            def get(idx):
                return cells[idx] if idx is not None and idx < len(cells) else None

            race        = get(idx_raca)
            sex         = get(idx_sexo)
            era         = get(idx_era)
            lot_ref     = get(idx_lot)
            peso_f      = _to_float(get(idx_peso))
            arrobas     = _to_float(get(idx_arr))
            closed_price = _to_float(get(idx_valor))
            arroba_price = _to_float(get(idx_prarr))

            # Fallback posicional se nenhum mapeamento funcionou
            if not any([race, sex, closed_price, arroba_price]) and len(cells) >= 4:
                lot_ref  = cells[0]
                race     = cells[1] if len(cells) > 1 else None
                sex      = cells[2] if len(cells) > 2 else None
                era      = cells[3] if len(cells) > 3 else None
                closed_price = _to_float(cells[-1])

            if not any([race, sex, era, closed_price, arroba_price]):
                continue

            if arroba_price is None and closed_price and arrobas:
                arroba_price = round(closed_price / arrobas, 4)

            rows.append({
                "lot_ref":              _clean_text(lot_ref),
                "race_raw":             _clean_text(race),
                "sex_raw":              _clean_text(sex),
                "era_raw":              _clean_text(era),
                "weight_kg":            peso_f,
                "arrobas":              arrobas,
                "closed_price_brl":     closed_price,
                "price_per_arroba_brl": arroba_price,
            })
    return rows


def scrape_cda_url(url: str) -> list:
    """Faz o request e extrai os lotes de uma página de leilão individual."""
    headers = {"User-Agent": USER_AGENT}
    resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers=headers)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")
    event_meta = _extract_event_meta(soup, url)

    # Tenta primeiro os data-attributes (mais limpo), depois tabela
    rows = _parse_lot_rows_from_data_attrs(soup)
    if not rows:
        rows = _parse_lot_rows_from_table(soup)

    # Anexa metadados do evento a cada linha e calcula hash
    parsed = []
    for row in rows:
        row.update(event_meta)
        row_text = "|".join(str(v) for v in row.values() if v is not None)
        stable = {
            "source_url":          url,
            "event_name":          row.get("event_name"),
            "event_date":          row["event_date"].isoformat() if row.get("event_date") else None,
            "lot_ref":             row.get("lot_ref"),
            "race_raw":            row.get("race_raw"),
            "sex_raw":             row.get("sex_raw"),
            "era_raw":             row.get("era_raw"),
            "weight_kg":           row.get("weight_kg"),
            "arrobas":             row.get("arrobas"),
            "closed_price_brl":    row.get("closed_price_brl"),
            "price_per_arroba_brl":row.get("price_per_arroba_brl"),
            "row_text":            row_text,
        }
        row["hash_key"] = hashlib.sha256(
            json.dumps(stable, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        row["row_raw"] = row_text
        parsed.append(row)

    return parsed

# ── Persistência ──────────────────────────────────────────────────────────────

def _get_or_create_event(session, source_url: str, payload: dict):
    event_name     = payload.get("event_name")
    event_date     = payload.get("event_date")
    event_location = payload.get("event_location")

    existing = (
        session.query(CdaEvent)
        .filter(
            CdaEvent.source_url == source_url,
            CdaEvent.event_name == event_name,
            CdaEvent.event_date == event_date,
        )
        .first()
    )
    now = datetime.utcnow()
    if existing:
        existing.event_location = event_location or existing.event_location
        existing.updated_at = now
        return existing

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


def persist_cda_results(source_url: str, parsed_rows: list) -> dict:
    session  = SessionLocal()
    inserted = updated = skipped = 0
    try:
        now = datetime.utcnow()
        for payload in parsed_rows:
            existing = (
                session.query(CdaLotResult)
                .filter(CdaLotResult.hash_key == payload["hash_key"])
                .first()
            )
            if existing:
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

# ── Ciclos de execução ────────────────────────────────────────────────────────

def run_cda_backfill(max_pages: int = 10, max_urls: int = None) -> dict:
    """Descobre leilões e processa cada um. Usado para backfill histórico."""
    urls = fetch_cda_auction_urls(max_pages=max_pages)
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
            summary["rows_scraped"]   += len(parsed)
            summary["inserted"]       += result["inserted"]
            summary["updated"]        += result["updated"]
            print(
                f"[CDA] {url} → rows={len(parsed)} "
                f"inserted={result['inserted']} updated={result['updated']}",
                flush=True,
            )
        except Exception as exc:
            summary["failed_urls"].append({"url": url, "error": str(exc)})
            print(f"[CDA] ERROR {url}: {exc}", flush=True)

    print(f"[CDA] Backfill summary: {summary}", flush=True)
    return summary


def run_cda_daily_cycle() -> dict:
    """
    Ciclo diário:
    - Se banco vazio → backfill histórico completo (10 páginas de listagem)
    - Caso contrário → incremental: só as 2 últimas páginas (~40 leilões recentes)
    """
    session = SessionLocal()
    try:
        lot_count = session.query(CdaLotResult.id).count()
    finally:
        session.close()

    if lot_count == 0:
        print("[CDA] Banco vazio. Iniciando backfill histórico completo...", flush=True)
        return run_cda_backfill(max_pages=10, max_urls=None)

    # Incremental: últimas 2 páginas de resultados
    print(f"[CDA] {lot_count} lotes já no banco. Rodando ciclo incremental...", flush=True)
    return run_cda_backfill(max_pages=2, max_urls=None)


# ── Alias de compatibilidade (nome antigo) ────────────────────────────────────
def fetch_cda_history_urls(max_pages=100):
    return fetch_cda_auction_urls(max_pages=max_pages)
