"""
Avisos de fim do período de teste (trial) — job diário do scheduler.

Usuários com trial_expires_at e sem assinatura Stripe recebem:
  estágio 1: aviso 3 dias antes do vencimento
  estágio 2: aviso no dia do vencimento (ou até 1 dia depois, se o job atrasar)
users.trial_notice_stage guarda o último estágio enviado, para não repetir.

WhatsApp: texto livre dentro da janela de 24h; fora dela, o template aprovado
'aviso_fim_teste' (com botão "Assinar agora" → /billing/checkout/<PLANO>_MONTHLY/<chat_id>).
"""
from datetime import datetime

CHECKOUT_BASE = "https://analyticsbov-production.up.railway.app/billing/checkout/"
NOTICE_DAYS_BEFORE = 3
PLAN_DISPLAY = {"STARTER": "Starter", "PRO": "Ouro (PRO)"}


def _stage_due(days_left: int) -> int:
    if -1 <= days_left <= 0:
        return 2
    if 0 < days_left <= NOTICE_DAYS_BEFORE:
        return 1
    return 0


def _notice_text(plan: str, end_str: str, chat_id: str) -> str:
    plan_display = PLAN_DISPLAY.get(plan, plan)
    return (
        f"⏳ *Seu período de teste termina em {end_str}*\n\n"
        f"Você está usando o plano *{plan_display}* do Agro Analytics.\n"
        "Para continuar recebendo os alertas de NDVI por satélite e as cotações do boi, assine:\n\n"
        f"👉 Mensal: {CHECKOUT_BASE}{plan}_MONTHLY/{chat_id}\n"
        f"👉 Anual (desconto): {CHECKOUT_BASE}{plan}_YEARLY/{chat_id}"
    )


def _send_telegram(chat_id: str, text: str) -> bool:
    import requests
    from app.config import Config
    resp = requests.post(
        f"https://api.telegram.org/bot{Config.TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown", "disable_web_page_preview": True},
        timeout=15,
    )
    return resp.ok


def run_trial_notices() -> dict:
    from app.models import SessionLocal, User

    today = datetime.utcnow().date()
    summary = {"checked": 0, "sent": 0, "failed": 0}
    db = SessionLocal()
    try:
        users = db.query(User).filter(
            User.trial_expires_at.isnot(None),
            User.stripe_subscription_id.is_(None),
        ).all()
        for user in users:
            summary["checked"] += 1
            days_left = (user.trial_expires_at.date() - today).days
            stage = _stage_due(days_left)
            if stage == 0 or stage <= (user.trial_notice_stage or 0):
                continue

            chat_id = str(user.chat_id)
            plan = (user.plan_type or "PRO").upper()
            if plan not in PLAN_DISPLAY:
                plan = "PRO"
            end_str = user.trial_expires_at.strftime("%d/%m/%Y")
            text = _notice_text(plan, end_str, chat_id)

            try:
                if (user.platform or "telegram") == "whatsapp":
                    from app.whatsapp.sender import send_whatsapp_text_or_template
                    ok = send_whatsapp_text_or_template(
                        chat_id, text, template_name="aviso_fim_teste",
                        template_params={"plano": PLAN_DISPLAY[plan], "data_fim": end_str},
                        button_url_suffix=f"{plan}_MONTHLY/{chat_id}",
                    )
                else:
                    ok = _send_telegram(chat_id, text)
            except Exception as e:
                print(f"[TRIAL] Falha ao avisar {chat_id}: {e}", flush=True)
                ok = False

            if ok:
                user.trial_notice_stage = stage
                db.commit()
                summary["sent"] += 1
                print(f"[TRIAL] Aviso estágio {stage} enviado para {chat_id} (vence {end_str})", flush=True)
            else:
                summary["failed"] += 1
    finally:
        db.close()

    print(f"[TRIAL] {summary}", flush=True)
    return summary
