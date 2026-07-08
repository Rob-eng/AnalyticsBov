"""
Scraper Correa da Costa — versão final com estrutura HTML real confirmada.

Estrutura real de cada <tr> de lote (confirmada via inspeção do browser):
  <tr data-sexo="F" data-raca="NELORE" data-status="vendido" data-peso="276.00" ...>
    <td> <img ...> </td>                              ← col 0: foto
    <td id="leilao-lote-458276">                      ← col 1: badge de status/preço
        <span class="badge bg-success">Vendido<br>R$ 3050,00</span>
    </td>
    <td>015</td>                                      ← col 2: número do lote
    <td>10</td>                                       ← col 3: quantidade de animais
    <td>F</td>                                        ← col 4: sexo
    <td>NELORE</td>                                   ← col 5: raça
    <td>276kg</td>                                    ← col 6: peso médio/animal
    <td>R$ 11,05</td>                                 ← col 7: preço R$/kg vivo
    <td></td>                                         ← col 8: obs
  </tr>

O preço fechado está no badge. Não existe coluna "Valor/@" direta.
Calculamos: arroba = peso_kg / 15; price_arroba = preco_fechado / arrobas
"""

import hashlib
import json
import os
import re
from datetime import datetime
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from app.models import SessionLocal, CdaEvent, CdaLotResult

BASE_URL        = "https://www.correadacosta.com.br"
RESULTS_URL     = f"{BASE_URL}/resultados"
REQUEST_TIMEOUT = 40
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# ── Sessão autenticada ────────────────────────────────────────────────────────

_session: requests.Session | None = None

def _get_session() -> requests.Session:
    """
    Retorna uma requests.Session autenticada no CDA.
    Faz login apenas na primeira chamada; reutiliza o cookie nas seguintes.
    """
    global _session
    if _session is not None:
        return _session

    email    = os.getenv("CDA_EMAIL", "")
    password = os.getenv("CDA_PASSWORD", "")

    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept-Language": "pt-BR,pt;q=0.9",
    })

    if not email or not password:
        print("[CDA] ⚠️ CDA_EMAIL/CDA_PASSWORD não configurados — scraping sem login.", flush=True)
        _session = s
        return _session

    # 1. GET /login → extrai CSRF token
    try:
        login_page = s.get(f"{BASE_URL}/login", timeout=REQUEST_TIMEOUT)
        soup = BeautifulSoup(login_page.text, "lxml")
        token_input = soup.find("input", {"name": "__RequestVerificationToken"})
        csrf_token = token_input["value"] if token_input else ""
    except Exception as e:
        print(f"[CDA] ❌ Falha ao carregar página de login: {e}", flush=True)
        _session = s
        return _session

    # 2. POST /Login com credenciais
    try:
        resp = s.post(
            f"{BASE_URL}/Login",
            data={
                "Apelido":                    email,
                "Password":                   password,
                "__RequestVerificationToken": csrf_token,
            },
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )
        # Login bem-sucedido redireciona para / ou /perfil (não para /login)
        if "/login" in resp.url.lower():
            print("[CDA] ❌ Login falhou — verifique CDA_EMAIL e CDA_PASSWORD.", flush=True)
        else:
            print(f"[CDA] ✅ Login efetuado com sucesso (redirect → {resp.url})", flush=True)
    except Exception as e:
        print(f"[CDA] ❌ Erro durante POST /Login: {e}", flush=True)

    _session = s
    return _session


def _reset_session():
    """Força novo login na próxima chamada (usar se receber 401/redirect para login)."""
    global _session
    _session = None

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
    txt = re.sub(r"[Rr]\$|US\$|@|kg", "", txt).strip()
    # PT-BR format uses "." as thousands sep and "," as decimal: "3.050,00"
    # If no comma present, the "." is the decimal separator (US format): "423.00"
    if "," in txt:
        txt = txt.replace(".", "").replace(",", ".")
    txt = re.sub(r"[^0-9.\-]", "", txt)
    if not txt:
        return None
    try:
        return float(txt)
    except ValueError:
        return None


def _to_date(value):
    """Converte strings de data variadas para datetime.
    Suporta: '11/junho/2026', '2026-06-11', 'quinta, 11/junho/2026'
    """
    text = _clean_text(value)
    if not text:
        return None
    # Remove dia da semana
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


# ── Descoberta de URLs de leilão ──────────────────────────────────────────────

def fetch_cda_auction_urls(max_pages: int = 10) -> list:
    """
    Varre /resultados?page=N e coleta URLs de leilão individuais.
    Padrão válido: /leiloes/<slug> onde slug tem pelo menos um hífen (é uma página de evento).
    Exclui: /leiloes, /leiloes/medias/*, /leiloes/agenda, etc.
    """
    session = _get_session()
    found   = set()

    for page in range(1, max_pages + 1):
        page_url = RESULTS_URL if page == 1 else f"{RESULTS_URL}?page={page}"
        try:
            resp = session.get(page_url, timeout=REQUEST_TIMEOUT)
        except Exception as e:
            print(f"[CDA] Erro ao acessar {page_url}: {e}", flush=True)
            break

        if resp.status_code != 200:
            if page == 1:
                raise RuntimeError(f"Falha ao acessar {page_url}: {resp.status_code}")
            break

        soup   = BeautifulSoup(resp.text, "lxml")
        before = len(found)

        for anchor in soup.select("a[href]"):
            href     = anchor.get("href", "")
            absolute = urljoin(BASE_URL, href)
            parsed   = urlparse(absolute)

            if "correadacosta.com.br" not in parsed.netloc:
                continue

            path = parsed.path.rstrip("/")

            # Deve seguir /leiloes/<slug> com slug real (contém hífen)
            if not re.match(r"^/leiloes/[a-z0-9]+-[a-z0-9].*$", path):
                continue

            # Exclui sub-seções
            if any(x in path for x in ["/medias", "/agenda", "/lote-"]):
                continue

            found.add(absolute)

        if page > 1 and len(found) == before:
            print(f"[CDA] Paginação encerrada na página {page} (sem novos links).", flush=True)
            break

    print(f"[CDA] {len(found)} URLs de leilão descobertas.", flush=True)
    return sorted(found)


# ── Metadados do evento ───────────────────────────────────────────────────────

def _extract_event_meta(soup, source_url: str) -> dict:
    """Extrai nome, data e local do evento a partir do H1 e da URL."""
    meta = {"event_name": None, "event_date": None, "event_location": None}

    h1 = soup.find("h1")
    if h1:
        meta["event_name"] = _clean_text(h1.get_text(" ", strip=True))

    # Data a partir do slug na URL: /leiloes/4809-...-2026-06-11
    date_match = re.search(r"(\d{4}-\d{2}-\d{2})", source_url)
    if date_match:
        try:
            meta["event_date"] = datetime.strptime(date_match.group(1), "%Y-%m-%d")
        except ValueError:
            pass

    # Fallback: procura data no texto da página em vários formatos
    if not meta["event_date"]:
        body_text = soup.get_text(" ")
        # "quinta, 11/junho/2026" ou "quinta-feira 11 junho 2026"
        dm = re.search(
            r"(?:segunda|terça|terca|quarta|quinta|sexta|sábado|sabado|domingo)"
            r"(?:-feira)?,?\s*"
            r"(\d{1,2})[/\s]+([a-záêçõãíóú]+)[/\s]+(\d{4})",
            body_text, re.IGNORECASE
        )
        if dm:
            meta["event_date"] = _to_date(f"{dm.group(1)}/{dm.group(2)}/{dm.group(3)}")

    if not meta["event_date"]:
        # "07/07/2026" ou "07-07-2026"
        dm2 = re.search(r"\b(\d{2})[/\-](\d{2})[/\-](202\d)\b", soup.get_text(" "))
        if dm2:
            try:
                meta["event_date"] = datetime.strptime(
                    f"{dm2.group(1)}/{dm2.group(2)}/{dm2.group(3)}", "%d/%m/%Y"
                )
            except ValueError:
                pass

    if not meta["event_date"]:
        # <time datetime="2026-07-07"> ou similar no HTML
        time_tag = soup.find("time", attrs={"datetime": True})
        if time_tag:
            try:
                meta["event_date"] = datetime.strptime(
                    time_tag["datetime"][:10], "%Y-%m-%d"
                )
            except ValueError:
                pass

    # Local: "Local: Estância Orsi / Leiloeiro: ..."
    local_m = re.search(r"[Ll]ocal:\s*(.+?)(?:[/\n]|Leiloeiro|$)", soup.get_text(" "))
    if local_m:
        meta["event_location"] = _clean_text(local_m.group(1))

    return meta


# ── Extração de lotes ─────────────────────────────────────────────────────────

def _extract_price_from_badge(td) -> float | None:
    """
    Extrai o preço do badge de status:
      <span class="badge bg-success">Vendido<br>R$ 3.050,00</span>
    """
    badge = td.find("span", class_="badge")
    if not badge:
        return None
    # Remove o texto "Vendido" e captura apenas o valor monetário
    badge_text = badge.get_text(" ", strip=True)
    # Extrai padrão R$ 3.050,00 ou R$ 4000,00
    m = re.search(r"R\$\s*([\d.,]+)", badge_text)
    if m:
        return _to_float("R$ " + m.group(1))
    return None


def _parse_lot_rows(soup) -> list:
    """
    Extrai lotes das <tr> com data-raca / data-sexo / data-peso.
    Estrutura real (confirmada):
      col 0: foto
      col 1: badge Vendido/R$
      col 2: número do lote
      col 3: quantidade animais
      col 4: sexo
      col 5: raça
      col 6: peso médio (kg)
      col 7: R$/kg vivo
      col 8: obs
    """
    rows = []
    for tr in soup.find_all("tr", attrs={"data-raca": True}):
        raca   = _clean_text(tr.get("data-raca"))
        sexo   = _clean_text(tr.get("data-sexo"))
        status = (tr.get("data-status") or "").lower()
        peso_s = tr.get("data-peso")  # peso médio por animal em kg

        # Só processa lotes vendidos / negociados
        if status and status not in ("vendido", "negociado", "vendidos", "negociados", ""):
            continue

        tds = tr.find_all("td")

        # Preço fechado do badge (col 1)
        closed_price = None
        if len(tds) > 1:
            closed_price = _extract_price_from_badge(tds[1])

        # Número do lote (col 2)
        lot_ref = _clean_text(tds[2].get_text(" ", strip=True)) if len(tds) > 2 else None

        # Quantidade de animais (col 3)
        qtde = None
        if len(tds) > 3:
            qtde = _to_float(tds[3].get_text(" ", strip=True))

        # Peso médio por animal (col 6 ou data-peso)
        peso_kg = _to_float(peso_s)
        if peso_kg is None and len(tds) > 6:
            peso_kg = _to_float(tds[6].get_text(" ", strip=True))

        # Total de arrobas do lote: qtde_animais * (peso_kg / 15)
        arrobas = None
        if peso_kg and qtde:
            arrobas = round(qtde * (peso_kg / 15.0), 2)
        elif peso_kg:
            arrobas = round(peso_kg / 15.0, 2)

        # Preço por arroba: badge mostra preço POR CABEÇA, dividir por arrobas/cabeça
        arroba_price = None
        if closed_price and peso_kg and peso_kg > 0:
            arrobas_por_cabeca = peso_kg / 15.0
            arroba_price = round(closed_price / arrobas_por_cabeca, 2)

        # Preço R$/kg vivo (col 7) — armazenamos em era_raw E price_per_kg_brl
        preco_kg_vivo = None
        price_kg = None
        if len(tds) > 7:
            preco_kg_vivo = _clean_text(tds[7].get_text(" ", strip=True))
            price_kg = _to_float(preco_kg_vivo)
            if price_kg and not (5.0 < price_kg < 100.0):
                price_kg = None  # fora da faixa plausível R$/kg vivo (5-100 R$/kg)

        if not any([raca, closed_price, price_kg]):
            continue

        rows.append({
            "lot_ref":              lot_ref,
            "race_raw":             raca,
            "sex_raw":              sexo,
            "era_raw":              preco_kg_vivo,
            "weight_kg":            peso_kg,
            "arrobas":              arrobas,
            "qtde_animals":         int(qtde) if qtde else None,
            "scrape_mode":          "individual",
            "closed_price_brl":     closed_price,
            "price_per_kg_brl":     price_kg,
            "price_per_arroba_brl": arroba_price,
        })

    return rows


# ── Scraping de uma página de leilão ─────────────────────────────────────────

def scrape_cda_url(url: str) -> list:
    """
    Faz o request e extrai todos os lotes/médias de uma página de leilão.

    Estratégia dual:
    1. Tenta extrair lotes individuais via data-raca (leilão mais recente)
    2. Se não encontrar, tenta a tabela de médias (Classificação|Idade|Peso|Valor)
       presente nos leilões de segunda/terça já encerrados.
    """
    session = _get_session()
    resp = session.get(url, timeout=REQUEST_TIMEOUT)
    # Se redirecionou para login, sessão expirou — tenta renovar uma vez
    if "/login" in resp.url.lower():
        print(f"[CDA] Sessão expirada em {url}, renovando login...", flush=True)
        _reset_session()
        session = _get_session()
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()

    soup       = BeautifulSoup(resp.text, "lxml")
    event_meta = _extract_event_meta(soup, url)

    # Tenta lotes individuais primeiro
    rows = _parse_lot_rows(soup)

    # Fallback: tabela de médias dos leilões encerrados
    if not rows:
        rows = _parse_medias_table(soup)

    # Calcula hash e anexa metadados do evento
    parsed = []
    for row in rows:
        row.update(event_meta)
        stable = {
            "source_url":           url,
            "event_name":           row.get("event_name"),
            "event_date":           row["event_date"].isoformat() if row.get("event_date") else None,
            "lot_ref":              row.get("lot_ref"),
            "race_raw":             row.get("race_raw"),
            "sex_raw":              row.get("sex_raw"),
            "era_raw":              row.get("era_raw"),
            "weight_kg":            row.get("weight_kg"),
            "closed_price_brl":     row.get("closed_price_brl"),
            "price_per_arroba_brl": row.get("price_per_arroba_brl"),
        }
        row["hash_key"] = hashlib.sha256(
            json.dumps(stable, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        row["row_raw"] = (
            f"{row.get('lot_ref') or 'media'} | {row.get('race_raw')} | "
            f"{row.get('sex_raw') or ''} | {row.get('era_raw') or ''} | "
            f"{row.get('weight_kg')}kg | R$ {row.get('closed_price_brl')} | "
            f"R$ {row.get('price_per_arroba_brl')}/@"
        )
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
        existing.updated_at     = now
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
    inserted = updated = 0
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
            lot   = CdaLotResult(
                event_id=event.id if event else None,
                source_url=source_url,
                source_page=RESULTS_URL,
                lot_ref=payload.get("lot_ref"),
                race_raw=payload.get("race_raw"),
                sex_raw=payload.get("sex_raw"),
                era_raw=payload.get("era_raw"),
                weight_kg=payload.get("weight_kg"),
                arrobas=payload.get("arrobas"),
                qtde_animals=payload.get("qtde_animals"),
                scrape_mode=payload.get("scrape_mode", "individual"),
                closed_price_brl=payload.get("closed_price_brl"),
                price_per_kg_brl=payload.get("price_per_kg_brl"),
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
    return {"inserted": inserted, "updated": updated}


# ── Ciclos de execução ────────────────────────────────────────────────────────

def _parse_medias_table(soup) -> list:
    """
    Extrai médias da tabela de resumo presente em leilões já encerrados.

    Estrutura confirmada (leilões de segunda/terça):
      th: Classificação | Idade | Peso | Valor | R$/Kg
      td: ANELHORADO    | 08 A 10 MESES | 199 kg | R$ 2.950,00 | 14,82

    Calcula price_per_arroba_brl = valor / (peso_kg / 15)
    """
    rows = []

    for table in soup.find_all("table"):
        headers_raw = [
            _clean_text(th.get_text(" ", strip=True))
            for th in table.find_all("th")
        ]
        if not headers_raw:
            first_tr = table.find("tr")
            if first_tr:
                headers_raw = [
                    _clean_text(c.get_text(" ", strip=True))
                    for c in first_tr.find_all(["th", "td"])
                ]

        # Normaliza para detectar a tabela de médias
        headers_norm = [h.lower() if h else "" for h in headers_raw]
        has_class   = any("classif" in h for h in headers_norm)
        has_valor   = any("valor" in h for h in headers_norm)
        has_peso    = any("peso" in h for h in headers_norm)

        if not (has_class and has_valor and has_peso):
            continue

        # Mapa de índices por coluna
        def col(keyword):
            for i, h in enumerate(headers_norm):
                if keyword in h:
                    return i
            return None

        idx_race  = col("classif") or col("raca")
        idx_age   = col("idade") or col("era") or col("categ")
        idx_peso  = col("peso")
        idx_valor = col("valor")
        idx_prkg  = col("r$/kg") or col("kg")

        for tr in table.find_all("tr"):
            tds = tr.find_all("td")
            if not tds:
                continue
            cells = [_clean_text(td.get_text(" ", strip=True)) for td in tds]
            if not any(cells):
                continue

            def get(idx):
                return cells[idx] if idx is not None and idx < len(cells) else None

            race    = get(idx_race)
            age     = get(idx_age)
            peso_s  = get(idx_peso)
            valor_s = get(idx_valor)

            peso_f  = _to_float(peso_s)
            valor_f = _to_float(valor_s)

            if not race or not valor_f or not peso_f:
                continue

            arrobas      = round(peso_f / 15.0, 2) if peso_f else None
            arroba_price = round(valor_f / arrobas, 2) if valor_f and arrobas else None

            # Inferir sex_raw a partir da classificação (ex: NOVILHA→F, BOI/TOURO→M)
            sex_inferred = None
            if race:
                race_up = race.upper()
                if any(x in race_up for x in ["NOVILHA", "VACA", "BEZERRA", "TERNEIRA"]):
                    sex_inferred = "F"
                elif any(x in race_up for x in ["BOI", "TOURO", "NOVILHO", "BEZERRO", "TERNEIRO"]):
                    sex_inferred = "M"

            rows.append({
                "lot_ref":              None,
                "race_raw":             race,
                "sex_raw":              sex_inferred,    # inferido da classificação
                "era_raw":              age,             # ex: "08 A 10 MESES"
                "weight_kg":            peso_f,
                "arrobas":              arrobas,
                "qtde_animals":         None,
                "scrape_mode":          "medias",
                "closed_price_brl":     valor_f,
                "price_per_arroba_brl": arroba_price,
            })

    return rows


def run_cda_backfill(max_pages: int = 10, max_urls: int = None) -> dict:
    """Descobre leilões e processa cada um."""
    urls = fetch_cda_auction_urls(max_pages=max_pages)
    if max_urls:
        urls = urls[:max_urls]

    summary = {
        "urls_discovered":  len(urls),
        "urls_processed":   0,
        "rows_scraped":     0,
        "inserted":         0,
        "updated":          0,
        "failed_urls":      [],
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
                f"[CDA] {url.split('/')[-1]} → "
                f"rows={len(parsed)} inserted={result['inserted']} updated={result['updated']}",
                flush=True,
            )
        except Exception as exc:
            summary["failed_urls"].append({"url": url, "error": str(exc)})
            print(f"[CDA] ERROR {url}: {exc}", flush=True)

    print(f"[CDA] Backfill concluído: {summary}", flush=True)
    return summary


def run_cda_daily_cycle() -> dict:
    """
    Ciclo diário:
    - Banco vazio → backfill histórico completo (10 páginas ≈ 200+ leilões)
    - Banco com dados → incremental: só as 2 últimas páginas (~40 leilões recentes)
    """
    session = SessionLocal()
    try:
        lot_count = session.query(CdaLotResult.id).count()
    finally:
        session.close()

    if lot_count == 0:
        print("[CDA] Banco vazio. Iniciando backfill histórico...", flush=True)
        return run_cda_backfill(max_pages=10, max_urls=None)

    print(f"[CDA] {lot_count} lotes no banco. Ciclo incremental...", flush=True)
    return run_cda_backfill(max_pages=2, max_urls=None)


# ── Alias de compatibilidade ──────────────────────────────────────────────────
def fetch_cda_history_urls(max_pages=100):
    return fetch_cda_auction_urls(max_pages=max_pages)
