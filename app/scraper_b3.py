"""
Ajustes diários do Boi Gordo futuro (BGI) na B3.

Fonte: Boletim Diário do Mercado — tabela "Negócios consolidados do pregão"
  POST https://arquivos.b3.com.br/bdi/table/ConsolidatedTradesDerivatives/<data>/<data>/<pág>/<qtd>
  corpo: {}   (a API recusa GET; página máx. ~1000 linhas; histórico de ~21 dias)

A tabela traz todos os derivativos do dia (~9 páginas); filtramos os futuros BGI.
Colunas usadas: TckrSymb (BGIV26), AdjstdQt (ajuste), PrvsAdjstdQt, TradQty.
"""

from datetime import date, datetime, timedelta

import requests

from app.models import SessionLocal, FuturesSettlement

TABLE_URL       = "https://arquivos.b3.com.br/bdi/table/ConsolidatedTradesDerivatives"
PAGE_SIZE       = 1000
REQUEST_TIMEOUT = 60
MAX_PAGES       = 30
HISTORY_DAYS    = 21   # limite do BDI ("D-21")

# Letra de vencimento B3 → mês
_MONTH_CODES = {"F": 1, "G": 2, "H": 3, "J": 4, "K": 5, "M": 6,
                "N": 7, "Q": 8, "U": 9, "V": 10, "X": 11, "Z": 12}


def contract_month(ticker):
    """'BGIV26' → date(2026, 10, 1)."""
    try:
        return date(2000 + int(ticker[4:6]), _MONTH_CODES[ticker[3]], 1)
    except (KeyError, ValueError, IndexError):
        return None


def fetch_bgi_settlements(ref_date: date, prefix="BGI") -> list:
    """Ajustes dos futuros `prefix` num pregão. Lista vazia = sem pregão (fim de semana/feriado)."""
    day = ref_date.isoformat()
    records, columns, page = [], None, 1
    while page <= MAX_PAGES:
        resp = requests.post(
            f"{TABLE_URL}/{day}/{day}/{page}/{PAGE_SIZE}",
            json={},
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://arquivos.b3.com.br/bdi/tabelas"},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        table = resp.json().get("table") or {}
        columns = columns or [c["name"] for c in table.get("columns") or []]

        for values in table.get("values") or []:
            row = dict(zip(columns, values))
            ticker = row.get("TckrSymb") or ""
            if not (ticker.startswith(prefix) and len(ticker) == 6 and row.get("Mkt") == "FUTURE"):
                continue
            month = contract_month(ticker)
            if month is None or row.get("AdjstdQt") is None:
                continue
            records.append({
                "ticker":         ticker,
                "contract_month": month,
                "ref_date":       ref_date,
                "settle":         float(row["AdjstdQt"]),
                "prev_settle":    row.get("PrvsAdjstdQt"),
                "trades":         row.get("TradQty"),
            })

        if page >= (table.get("pageCount") or 0):
            break
        page += 1
    return records


def save_settlements(records: list) -> dict:
    inserted = updated = 0
    session = SessionLocal()
    try:
        existing = {
            (s.ticker, s.ref_date): s
            for s in session.query(FuturesSettlement).filter(
                FuturesSettlement.ticker.in_({r["ticker"] for r in records}),
                FuturesSettlement.ref_date.in_({r["ref_date"] for r in records}),
            )
        } if records else {}

        now = datetime.utcnow()
        for rec in records:
            row = existing.get((rec["ticker"], rec["ref_date"]))
            if row is None:
                session.add(FuturesSettlement(**rec, collected_at=now))
                inserted += 1
            elif row.settle != rec["settle"]:
                row.settle, row.prev_settle, row.trades = rec["settle"], rec["prev_settle"], rec["trades"]
                updated += 1
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    return {"inserted": inserted, "updated": updated}


def run_b3_futures_cycle(days_back: int = 3) -> dict:
    """Coleta os últimos `days_back` dias corridos (cobre fim de semana e atrasos da B3)."""
    today = date.today()
    summary = {"sessions": [], "inserted": 0, "updated": 0}
    for offset in range(days_back, -1, -1):
        day = today - timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        try:
            records = fetch_bgi_settlements(day)
        except requests.RequestException as e:
            print(f"[B3] {day}: sem dados ({e})", flush=True)
            continue
        if not records:
            continue
        res = save_settlements(records)
        summary["sessions"].append(day.isoformat())
        summary["inserted"] += res["inserted"]
        summary["updated"] += res["updated"]
    print(f"[B3] BGI ajustes: {summary}", flush=True)
    return summary


def run_b3_futures_backfill() -> dict:
    return run_b3_futures_cycle(days_back=HISTORY_DAYS + 10)


_MES_PT = ["", "Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]


def load_b3_futures_table(max_rows: int = 9):
    """
    Tabela do Mercado Futuro no formato de generate_future_table, a partir dos
    ajustes B3 gravados (último pregão). Usada quando a Scot está indisponível.
    """
    from app.models import SessionLocal, FuturesSettlement

    def br(v, d=2):
        return f"{v:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".") if v is not None else "—"

    db = SessionLocal()
    try:
        last = db.query(FuturesSettlement.ref_date).order_by(FuturesSettlement.ref_date.desc()).first()
        if not last:
            return None
        rows = (db.query(FuturesSettlement).filter(FuturesSettlement.ref_date == last[0])
                .order_by(FuturesSettlement.contract_month).limit(max_rows).all())
    finally:
        db.close()

    table = []
    for r in rows:
        var = r.settle - r.prev_settle if r.prev_settle is not None else None
        table.append([
            f"{_MES_PT[r.contract_month.month]}/{r.contract_month.year % 100}",
            br(r.settle), br(r.prev_settle),
            (f"{'+' if var > 0 else ''}{br(var)}" if var is not None else "—"),
            str(r.trades or 0),
        ])
    return {
        'date_raw': f"Ajustes B3 — pregão de {last[0].strftime('%d/%m/%Y')}",
        'headers': ["Vencimento", "Ajuste (R$/@)", "Ajuste anterior", "Variação (R$/@)", "Negócios"],
        'rows': table,
        'source': "B3 (ajustes do Boi Gordo BGI)",
    }
