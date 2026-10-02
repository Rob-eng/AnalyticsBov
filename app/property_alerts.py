"""
Alertas por propriedade ligados na plataforma web (opt-in em favorite_locations):

- Chuva abaixo da média (semanal): últimos 30 dias < 50% da média dos 10 anos
  anteriores para a mesma janela, só quando a média do período é relevante
  (≥ 40 mm — na seca a média é quase zero e qualquer garoa vira "100%").
  No máximo um aviso a cada 14 dias por propriedade.
- Novo apontamento PRODES (mensal): compara os apontamentos que cruzam o
  perímetro com a lista da última varredura. A primeira varredura só registra
  a base, sem avisar. Se o INPE não responder, pula e tenta no mês seguinte.

Entrega igual aos avisos de plano: Telegram por texto; WhatsApp por texto
dentro da janela de 24h e, fora dela, pelo template aprovado (com botão para
a página da propriedade).
"""
import os
from datetime import datetime, timedelta

from sqlalchemy.orm.attributes import flag_modified

from app.models import SessionLocal, FavoriteLocation, User, log_activity

WEB_BASE_URL = os.getenv("WEB_BASE_URL", "https://analyticsbov-production.up.railway.app").rstrip("/")
RAIN_PCT_THRESHOLD = 50
RAIN_MIN_NORMAL_MM = 40
RAIN_COOLDOWN = timedelta(days=14)
RAIN_TEMPLATE = os.getenv("WHATSAPP_RAIN_TEMPLATE_NAME", "alerta_chuva_abaixo")
PRODES_TEMPLATE = os.getenv("WHATSAPP_PRODES_TEMPLATE_NAME", "alerta_prodes_novo")


def property_url(property_id: int) -> str:
    return f"{WEB_BASE_URL}/app/p/{property_id}"


def _fmt(v: float, nd: int = 0) -> str:
    return f"{v:,.{nd}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _deliver(user, text: str, template: str, params: dict, property_id: int) -> bool:
    chat_id = str(user.chat_id)
    try:
        if (user.platform or "telegram") == "whatsapp":
            from app.whatsapp.sender import send_whatsapp_text_or_template
            return send_whatsapp_text_or_template(chat_id, text, template_name=template,
                                                  template_params=params, button_url_suffix=str(property_id))
        import requests
        from app.config import Config
        resp = requests.post(
            f"https://api.telegram.org/bot{Config.TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown", "disable_web_page_preview": True},
            timeout=15,
        )
        return resp.ok
    except Exception as e:
        print(f"[ALERTAS] Falha ao enviar para {chat_id}: {e}", flush=True)
        return False


def _targets(db, flag):
    """(propriedade, usuário) com o alerta ligado — usuários sem plano ativo também recebem (é opt-in)."""
    out = []
    for loc in db.query(FavoriteLocation).filter(flag == True).all():  # noqa: E712
        user = db.query(User).filter_by(chat_id=str(loc.user_id)).first()
        if user:
            out.append((loc, user))
    return out


# ── Chuva ─────────────────────────────────────────────────────────────────────

def rain_message(name: str, s: dict, property_id: int) -> tuple:
    pct = f"{s['pct_of_normal']}%"
    text = (f"🌧️ *Chuva abaixo da média — {name}*\n\n"
            f"Nos últimos 30 dias choveu *{_fmt(s['last30_mm'])} mm*, {pct} da média dos últimos 10 anos "
            f"para o período ({_fmt(s['normal30_mm'])} mm).\n"
            f"Previsão para os próximos 7 dias: {_fmt(s['next7_mm'])} mm.\n\n"
            f"Ver na plataforma: {property_url(property_id)}")
    params = {"prop_nome": name, "chuva_30d": _fmt(s["last30_mm"]), "pct_normal": pct,
              "normal_30d": _fmt(s["normal30_mm"]), "prev_7d": _fmt(s["next7_mm"])}
    return text, params


def run_rain_alert_scan() -> dict:
    from app.web.analytics import rain_summary
    sent = checked = 0
    db = SessionLocal()
    try:
        for loc, user in _targets(db, FavoriteLocation.rain_alerts_enabled):
            if loc.latitude is None:
                continue
            state = dict(loc.alert_state or {})
            last = state.get("rain_sent_at")
            if last and datetime.utcnow() - datetime.fromisoformat(last) < RAIN_COOLDOWN:
                continue
            try:
                s = rain_summary(loc.latitude, loc.longitude)
            except Exception as e:
                print(f"[ALERTAS] Chuva indisponível para '{loc.name}': {e}", flush=True)
                continue
            checked += 1
            normal, pct = s.get("normal30_mm"), s.get("pct_of_normal")
            if not normal or normal < RAIN_MIN_NORMAL_MM or pct is None or pct >= RAIN_PCT_THRESHOLD:
                continue
            text, params = rain_message(loc.name, s, loc.id)
            if _deliver(user, text, RAIN_TEMPLATE, params, loc.id):
                sent += 1
                state["rain_sent_at"] = datetime.utcnow().isoformat()
                loc.alert_state = state
                flag_modified(loc, "alert_state")
                db.commit()
                log_activity(str(user.chat_id), "ALERTA_CHUVA", platform=user.platform or "telegram",
                             details=f"{loc.name}: {pct}% da média")
    finally:
        db.close()
    print(f"[ALERTAS] Chuva: {checked} propriedades verificadas, {sent} avisos.", flush=True)
    return {"checked": checked, "sent": sent}


# ── PRODES ────────────────────────────────────────────────────────────────────

def prodes_message(name: str, new: list, property_id: int) -> tuple:
    area = sum(a.get("area_intersect_ha") or 0 for a in new)
    years = sorted({a["year"] for a in new if a.get("year")})
    qtd = f"{len(new)} novo apontamento" if len(new) == 1 else f"{len(new)} novos apontamentos"
    text = (f"🛰️ *Novo desmatamento PRODES — {name}*\n\n"
            f"O INPE publicou {qtd} de desmatamento que cruza{'m' if len(new) > 1 else ''} o perímetro, "
            f"somando *{_fmt(area, 2)} ha* dentro do imóvel"
            f"{' (ano ' + ', '.join(map(str, years)) + ')' if years else ''}.\n\n"
            f"Veja no mapa e gere o laudo: {property_url(property_id)}")
    params = {"prop_nome": name, "qtd": str(len(new)), "area_ha": _fmt(area, 2)}
    return text, params


def run_prodes_alert_scan() -> dict:
    from geoalchemy2.shape import to_shape
    from shapely.geometry import mapping
    from app.prodes_analysis import find_intersecting_apontamentos
    sent = checked = 0
    db = SessionLocal()
    try:
        for loc, user in _targets(db, FavoriteLocation.prodes_alerts_enabled):
            if loc.perimeter is None:
                continue
            try:
                aps = find_intersecting_apontamentos(mapping(to_shape(loc.perimeter)))
            except Exception as e:
                print(f"[ALERTAS] PRODES indisponível ('{loc.name}'): {str(e)[:200]}", flush=True)
                continue
            checked += 1
            state = dict(loc.alert_state or {})
            known = state.get("prodes_uuids")
            current = [a["uuid"] for a in aps if a.get("uuid")]
            new = [a for a in aps if known is not None and a.get("uuid") and a["uuid"] not in set(known)]
            if new:
                text, params = prodes_message(loc.name, new, loc.id)
                if not _deliver(user, text, PRODES_TEMPLATE, params, loc.id):
                    continue   # não atualiza a base: tenta avisar de novo na próxima varredura
                sent += 1
                log_activity(str(user.chat_id), "ALERTA_PRODES", platform=user.platform or "telegram",
                             details=f"{loc.name}: {len(new)} novo(s)")
            state["prodes_uuids"] = current
            state["prodes_checked_at"] = datetime.utcnow().isoformat()
            loc.alert_state = state
            flag_modified(loc, "alert_state")
            db.commit()
    finally:
        db.close()
    print(f"[ALERTAS] PRODES: {checked} propriedades verificadas, {sent} avisos.", flush=True)
    return {"checked": checked, "sent": sent}
