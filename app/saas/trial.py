"""
Fim de plano (teste grátis ou assinatura cancelada) — job diário do scheduler.

Regra: aviso 3 dias antes do fim, aviso no último dia e, no dia seguinte,
volta para o plano FREE (com mensagem e link para assinar).

- Teste grátis: fim = users.trial_expires_at (usuários sem assinatura Stripe).
- Assinatura Stripe: renovação automática não gera aviso. Só quando o cliente
  cancela (cancel_at_period_end) o fim do período pago vira a data de fim.
  Assinatura encerrada/sem pagamento (canceled, unpaid, incomplete_expired)
  volta para FREE na hora — o webhook customer.subscription.deleted também
  faz isso em tempo real (app/saas/billing.py → downgrade_to_free).

users.trial_notice_stage guarda o último aviso enviado (1 = D-3, 2 = último
dia) para não repetir; zera quando o plano muda.

WhatsApp: texto livre dentro da janela de 24h; fora dela, o template aprovado
(aviso_fim_teste / aviso_fim_assinatura / plano_encerrado, todos com botão
"Assinar agora" → /billing/checkout/<PLANO>_MONTHLY/<chat_id>).
"""
from datetime import datetime

CHECKOUT_BASE = "https://analyticsbov-production.up.railway.app/billing/checkout/"
NOTICE_DAYS_BEFORE = 3
PLAN_DISPLAY = {"STARTER": "Starter", "PRO": "Ouro (PRO)"}
STRIPE_ENDED_STATUSES = {"canceled", "unpaid", "incomplete_expired"}


def _stage_due(days_left: int) -> int:
    """0 = nada a fazer, 1 = aviso D-3, 2 = aviso no último dia, 3 = já terminou."""
    if days_left < 0:
        return 3
    if days_left == 0:
        return 2
    if days_left <= NOTICE_DAYS_BEFORE:
        return 1
    return 0


def _paid_plan(user) -> str:
    plan = (user.plan_type or "PRO").upper()
    return plan if plan in PLAN_DISPLAY else "PRO"


def _links(plan: str, chat_id: str) -> str:
    return (f"👉 Mensal: {CHECKOUT_BASE}{plan}_MONTHLY/{chat_id}\n"
            f"👉 Anual (desconto): {CHECKOUT_BASE}{plan}_YEARLY/{chat_id}")


def _send(user, text: str, template_name: str, plan: str, end_str: str) -> bool:
    chat_id = str(user.chat_id)
    try:
        if (user.platform or "telegram") == "whatsapp":
            from app.whatsapp.sender import send_whatsapp_text_or_template
            return send_whatsapp_text_or_template(
                chat_id, text, template_name=template_name,
                template_params={"plano": PLAN_DISPLAY[plan], "data_fim": end_str},
                button_url_suffix=f"{plan}_MONTHLY/{chat_id}",
            )
        import requests
        from app.config import Config
        resp = requests.post(
            f"https://api.telegram.org/bot{Config.TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown", "disable_web_page_preview": True},
            timeout=15,
        )
        return resp.ok
    except Exception as e:
        print(f"[PLANO] Falha ao enviar para {chat_id}: {e}", flush=True)
        return False


def _notice(user, plan: str, end_str: str, is_trial: bool) -> bool:
    what = "período de teste" if is_trial else "assinatura (cancelada)"
    text = (
        f"⏳ *Seu plano {PLAN_DISPLAY[plan]} termina em {end_str}*\n\n"
        f"Sua {what} do Agro Analytics vai até essa data; depois a conta volta para o plano gratuito.\n"
        "Para continuar recebendo os alertas de NDVI por satélite e as cotações do boi, assine:\n\n"
        + _links(plan, str(user.chat_id))
    )
    return _send(user, text, "aviso_fim_teste" if is_trial else "aviso_fim_assinatura", plan, end_str)


def downgrade_to_free(user, end_str: str, notify: bool = True) -> None:
    """Volta o usuário para FREE (sessão do chamador faz o commit)."""
    plan = _paid_plan(user)
    if notify:
        text = (
            f"📅 *Seu plano {PLAN_DISPLAY[plan]} terminou em {end_str}*\n\n"
            "Sua conta do Agro Analytics voltou para o plano gratuito.\n"
            "Para reativar os alertas de NDVI por satélite e as cotações do boi, assine:\n\n"
            + _links(plan, str(user.chat_id))
        )
        _send(user, text, "plano_encerrado", plan, end_str)
    print(f"[PLANO] {user.chat_id}: {user.plan_type} → FREE (fim {end_str})", flush=True)
    user.plan_type = "FREE"
    user.trial_expires_at = None
    user.stripe_subscription_id = None
    user.trial_notice_stage = 0


def _subscription_end(sub_id: str):
    """(encerrada_agora, data_fim_se_cancelada) a partir do Stripe; (False, None) se renova."""
    import stripe
    sub = stripe.Subscription.retrieve(sub_id)
    if sub.get("status") in STRIPE_ENDED_STATUSES:
        return True, datetime.utcnow()
    if sub.get("cancel_at_period_end") or sub.get("cancel_at"):
        # Na API nova do Stripe o fim do período fica nos itens da assinatura
        ts = sub.get("cancel_at") or sub.get("current_period_end")
        if not ts:
            items = (sub.get("items") or {}).get("data") or []
            ts = items[0].get("current_period_end") if items else None
        if ts:
            return False, datetime.utcfromtimestamp(ts)
    return False, None


def run_trial_notices() -> dict:
    from app.models import SessionLocal, User

    today = datetime.utcnow().date()
    summary = {"checked": 0, "notices": 0, "downgraded": 0, "failed": 0}
    db = SessionLocal()
    try:
        users = db.query(User).filter(
            (User.trial_expires_at.isnot(None)) | (User.stripe_subscription_id.isnot(None))
        ).all()
        for user in users:
            summary["checked"] += 1
            plan = _paid_plan(user)
            is_trial = user.stripe_subscription_id is None

            if is_trial:
                end = user.trial_expires_at
            else:
                try:
                    ended_now, end = _subscription_end(user.stripe_subscription_id)
                except Exception as e:
                    print(f"[PLANO] Stripe indisponível para {user.chat_id}: {e}", flush=True)
                    summary["failed"] += 1
                    continue
                if ended_now:
                    downgrade_to_free(user, today.strftime("%d/%m/%Y"))
                    db.commit()
                    summary["downgraded"] += 1
                    continue
                if end is None:  # assinatura ativa que renova
                    continue

            end_str = end.strftime("%d/%m/%Y")
            stage = _stage_due((end.date() - today).days)
            if stage == 3:
                downgrade_to_free(user, end_str)
                db.commit()
                summary["downgraded"] += 1
            elif stage and stage > (user.trial_notice_stage or 0):
                if _notice(user, plan, end_str, is_trial):
                    user.trial_notice_stage = stage
                    db.commit()
                    summary["notices"] += 1
                    print(f"[PLANO] Aviso {stage} enviado para {user.chat_id} (fim {end_str})", flush=True)
                else:
                    summary["failed"] += 1
    finally:
        db.close()

    print(f"[PLANO] {summary}", flush=True)
    return summary
