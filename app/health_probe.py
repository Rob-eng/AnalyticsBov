"""
Active health probes — each function actually calls the service and returns
{"status": "ok"|"warn"|"error", "latency_ms": float, "message": str}

These are lightweight: no full pipeline execution, just connectivity/freshness checks.
"""

import os
import time
import requests as _req

# Test coordinates: Campo Grande, MS
_LAT = -20.44
_LON = -54.64

_TIMEOUT = 8


def _run(fn):
    t0 = time.time()
    try:
        result = fn()
    except Exception as exc:
        result = {"status": "error", "message": str(exc)[:200]}
    result["latency_ms"] = round((time.time() - t0) * 1000)
    return result


# ── Individual probes ─────────────────────────────────────────────────────────

def probe_database():
    def _():
        from app.models import SessionLocal
        from sqlalchemy import text
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
            return {"status": "ok", "message": "Conexão PostgreSQL OK"}
        finally:
            db.close()
    return _run(_)


def probe_exchange_rate():
    def _():
        resp = _req.get(
            "https://economia.awesomeapi.com.br/last/USD-BRL",
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        rate = float(resp.json()["USDBRL"]["bid"])
        return {"status": "ok", "message": f"USD/BRL = R$ {rate:.2f}"}
    return _run(_)


def probe_openmeteo():
    def _():
        resp = _req.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": _LAT,
                "longitude": _LON,
                "daily": "precipitation_sum",
                "forecast_days": 1,
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        precip = resp.json().get("daily", {}).get("precipitation_sum", [None])[0]
        return {"status": "ok", "message": f"Previsão amanhã: {precip} mm"}
    return _run(_)


def probe_scot_web():
    def _():
        resp = _req.get(
            "https://www.scotconsultoria.com.br",
            timeout=_TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if resp.status_code < 400:
            return {"status": "ok", "message": f"HTTP {resp.status_code}"}
        return {"status": "warn", "message": f"HTTP {resp.status_code}"}
    return _run(_)


def probe_cda_freshness():
    def _():
        from app.models import SessionLocal, CdaEvent
        from datetime import datetime, timedelta
        db = SessionLocal()
        try:
            last = (
                db.query(CdaEvent)
                .filter(CdaEvent.event_date.isnot(None))
                .order_by(CdaEvent.event_date.desc())
                .first()
            )
            if not last:
                return {"status": "warn", "message": "Nenhum evento CDA no banco"}
            age = (datetime.utcnow() - last.event_date).days
            msg = f"Último leilão há {age}d — {last.event_date.strftime('%d/%m/%Y')}"
            return {"status": "ok" if age <= 7 else "warn", "message": msg}
        finally:
            db.close()
    return _run(_)


def probe_whatsapp():
    def _():
        token    = os.getenv("WHATSAPP_TOKEN", "")
        phone_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
        if not token or not phone_id:
            return {"status": "warn", "message": "WHATSAPP_TOKEN ou PHONE_NUMBER_ID ausentes"}
        resp = _req.get(
            f"https://graph.facebook.com/v22.0/{phone_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=_TIMEOUT,
        )
        if resp.status_code == 200:
            num = resp.json().get("display_phone_number", phone_id)
            return {"status": "ok", "message": f"Número: {num}"}
        body = resp.json()
        err  = body.get("error", {}).get("message", resp.text[:100])
        return {"status": "error", "message": f"HTTP {resp.status_code}: {err}"}
    return _run(_)


def probe_telegram():
    def _():
        from app.config import Config
        resp = _req.get(
            f"https://api.telegram.org/bot{Config.TELEGRAM_TOKEN}/getMe",
            timeout=_TIMEOUT,
        )
        if resp.status_code == 200:
            bot = resp.json().get("result", {})
            return {"status": "ok", "message": f"@{bot.get('username', '?')}"}
        return {"status": "error", "message": f"HTTP {resp.status_code}: {resp.text[:80]}"}
    return _run(_)


def probe_gee():
    def _():
        key = (
            os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
            or os.getenv("EE_PRIVATE_KEY")
            or os.getenv("GEE_SERVICE_ACCOUNT_KEY")
        )
        if not key:
            return {"status": "warn", "message": "Credenciais GEE não configuradas (env var ausente)"}
        try:
            import ee
            ee.Initialize()
            return {"status": "ok", "message": "GEE inicializado com sucesso"}
        except Exception as exc:
            return {"status": "error", "message": str(exc)[:150]}
    return _run(_)


def probe_openai():
    def _():
        key = os.getenv("OPENAI_API_KEY", "")
        if not key:
            return {"status": "warn", "message": "OPENAI_API_KEY não configurada"}
        # Lightweight: just validate the key format without making a full API call
        if key.startswith("sk-") and len(key) > 20:
            resp = _req.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {key}"},
                timeout=_TIMEOUT,
            )
            if resp.status_code == 200:
                count = len(resp.json().get("data", []))
                return {"status": "ok", "message": f"{count} modelos disponíveis"}
            return {"status": "error", "message": f"HTTP {resp.status_code}"}
        return {"status": "warn", "message": "OPENAI_API_KEY parece inválida"}
    return _run(_)


def probe_stripe():
    def _():
        key = os.getenv("STRIPE_SECRET_KEY", "")
        if not key:
            return {"status": "warn", "message": "STRIPE_SECRET_KEY não configurada"}
        resp = _req.get(
            "https://api.stripe.com/v1/balance",
            headers={"Authorization": f"Bearer {key}"},
            timeout=_TIMEOUT,
        )
        if resp.status_code == 200:
            return {"status": "ok", "message": "Stripe API acessível"}
        err = resp.json().get("error", {}).get("message", resp.text[:80])
        return {"status": "error", "message": f"HTTP {resp.status_code}: {err}"}
    return _run(_)


# ── Probe registry ────────────────────────────────────────────────────────────

ALL_PROBES = {
    "Database":       probe_database,
    "Câmbio USD/BRL": probe_exchange_rate,
    "OpenMeteo":      probe_openmeteo,
    "Scot Website":   probe_scot_web,
    "CDA Leilão":     probe_cda_freshness,
    "WhatsApp API":   probe_whatsapp,
    "Telegram API":   probe_telegram,
    "Google EE":      probe_gee,
    "OpenAI":         probe_openai,
    "Stripe":         probe_stripe,
}

PROBE_ICONS = {
    "Database":       "🗄️",
    "Câmbio USD/BRL": "💱",
    "OpenMeteo":      "🌧️",
    "Scot Website":   "📈",
    "CDA Leilão":     "🐂",
    "WhatsApp API":   "📱",
    "Telegram API":   "✈️",
    "Google EE":      "🛰️",
    "OpenAI":         "🤖",
    "Stripe":         "💳",
}


def run_all_probes(save_to_db: bool = True) -> dict:
    """
    Run all probes sequentially and optionally persist results.
    Returns dict[probe_name -> result_dict].
    """
    results = {}
    for name, fn in ALL_PROBES.items():
        print(f"[HealthProbe] Running: {name}...", flush=True)
        results[name] = fn()
        s = results[name]
        print(f"[HealthProbe] {name}: {s['status']} ({s['latency_ms']}ms) — {s.get('message','')}", flush=True)

    if save_to_db:
        _persist(results)
    return results


def _persist(results: dict):
    from app.models import SessionLocal, HealthCheckResult
    from datetime import datetime
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        for name, r in results.items():
            row = HealthCheckResult(
                probe_name=name,
                status=r["status"],
                latency_ms=r.get("latency_ms"),
                message=r.get("message"),
                checked_at=now,
            )
            db.add(row)
        db.commit()
    except Exception as e:
        print(f"[HealthProbe] Failed to persist results: {e}", flush=True)
        db.rollback()
    finally:
        db.close()
