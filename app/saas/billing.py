import stripe
import os
from app.config import Config
from app.models import SessionLocal, User
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import RedirectResponse
import logging

stripe.api_key = Config.STRIPE_API_KEY

router = APIRouter(prefix="/billing", tags=["Billing"])

# Plan Configuration (Stripe Official IDs & Business Rules)
PLANS = {
    "FREE": {
        "name": "Plano Bronze", 
        "max_properties": 1, 
        "monthly_lookups": 3, 
        "monthly_alerts": 1
    },
    
    # Starter
    "STARTER": {
        "name": "Plano Starter",
        "max_properties": 3,
        "monthly_lookups": 10,
        "monthly_alerts": 9999, # Unlimited
        "prices": {
            "MONTHLY": "price_1T55Oq2M9WyBElyRth0qLD5M",
            "YEARLY":  "price_1T55Oq2M9WyBElyRU52SNG7e"
        }
    },
    
    # PRO (Ouro)
    "PRO": {
        "name": "Plano Ouro (Equipes)",
        "max_properties": 10, # Extrapolating to 10 for teams
        "monthly_lookups": 9999, # Unlimited lookups for PRO teams
        "monthly_alerts": 9999,
        "max_team_members": 3,
        "prices": {
            "MONTHLY": "price_1T55Q72M9WyBElyRlawYjcRD",
            "YEARLY":  "price_1T55Q72M9WyBElyReOxOLUEP"
        }
    }
}

@router.get("/checkout/{plan_choice}/{chat_id}")
async def create_checkout_session(plan_choice: str, chat_id: str):
    """Cria uma sessão de checkout do Stripe para o plano escolhido."""
    # Parse choice: STARTER_MONTHLY -> base="STARTER", interval="MONTHLY"
    try:
        if "_" in plan_choice:
            base_plan, interval = plan_choice.split("_", 1)
        else:
            base_plan, interval = plan_choice, "MONTHLY"
            
        if base_plan not in PLANS or base_plan == "FREE":
            raise ValueError("Plano base inválido")
            
        plan_info = PLANS[base_plan]
        price_id = plan_info["prices"].get(interval)
        
        if not price_id:
            raise ValueError("Intervalo inválido para este plano")
            
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price': price_id,
                'quantity': 1,
            }],
            mode='subscription',
            success_url=f"https://analyticsbov-production.up.railway.app/?status=success&chat_id={chat_id}",
            cancel_url=f"https://analyticsbov-production.up.railway.app/?status=cancel&chat_id={chat_id}",
            client_reference_id=chat_id,
            metadata={
                "chat_id": chat_id,
                "plan": base_plan,
                "interval": interval
            }
        )
        return RedirectResponse(session.url)
    except Exception as e:
        logging.error(f"Stripe session error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/webhook")
async def stripe_webhook(request: Request):
    """Recebe notificações de pagamento do Stripe e atualiza o plano no banco."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    webhook_secret = Config.STRIPE_WEBHOOK_SECRET

    try:
        if webhook_secret:
            # Verificação segura com assinatura
            event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
        else:
            # Fallback: sem STRIPE_WEBHOOK_SECRET configurado — aceita o evento sem verificação
            # ⚠️ APENAS para desenvolvimento/primeira configuração. Configurar o secret no Railway!
            import json
            logging.warning(
                "⚠️ STRIPE_WEBHOOK_SECRET não configurado! "
                "Processando webhook SEM verificação de assinatura. "
                "Configure a variável no Railway para segurança em produção."
            )
            event = json.loads(payload)
    except ValueError:
        logging.error("Stripe webhook: payload inválido")
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        logging.error("Stripe webhook: assinatura inválida")
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as e:
        logging.error(f"Stripe webhook: erro inesperado na verificação: {e}")
        raise HTTPException(status_code=400, detail="Webhook verification failed")

    # Handle the checkout.session.completed event
    event_type = event.get('type') if isinstance(event, dict) else event['type']

    if event_type == 'checkout.session.completed':
        session_data = event.get('data', {}).get('object', {}) if isinstance(event, dict) else event['data']['object']
        chat_id = session_data.get('client_reference_id')
        plan = session_data.get('metadata', {}).get('plan', 'PRO')
        sub_id = session_data.get('subscription')

        if chat_id:
            db = SessionLocal()
            try:
                user = db.query(User).filter_by(chat_id=str(chat_id)).first()
                if user:
                    old_plan = user.plan_type
                    user.plan_type = plan
                    user.stripe_subscription_id = sub_id
                    db.commit()
                    logging.info(f"✅ Usuário {chat_id} promovido de {old_plan} para {plan}!")

                    # Notificar o usuário via WhatsApp
                    try:
                        user_platform = getattr(user, 'platform', 'telegram') or 'telegram'
                        plan_names = {"STARTER": "Starter", "PRO": "Ouro (PRO)"}
                        plan_display = plan_names.get(plan, plan)

                        if user_platform == 'whatsapp':
                            from app.whatsapp.sender import send_whatsapp_text
                            send_whatsapp_text(
                                str(chat_id),
                                f"🎉 *Pagamento confirmado!*\n\n"
                                f"Seu plano foi atualizado para *{plan_display}*.\n"
                                f"Todas as funcionalidades premium já estão liberadas!\n\n"
                                f"🌿 Alertas NDVI automáticos\n"
                                f"📊 Relatório semanal de cotação\n"
                                f"🏔️ MDT 3D e mais\n\n"
                                f"Obrigado por assinar o Agro Analytics! 🐂"
                            )
                        logging.info(f"✅ Notificação de upgrade enviada para {chat_id}")
                    except Exception as notify_err:
                        logging.warning(f"Notificação de upgrade falhou para {chat_id}: {notify_err}")
                else:
                    logging.warning(f"⚠️ Stripe webhook: usuário {chat_id} não encontrado no banco")
            except Exception as e:
                logging.error(f"Database error on webhook: {e}")
                db.rollback()
            finally:
                db.close()

    return {"status": "success"}

def check_plan_limit(chat_id: str, action: str) -> bool:
    """
    Verifica se o usuário pode realizar a ação com base no seu plano.
    Ações: 'NDVI_LOOKUP', 'ALERTS_ENABLED', etc.
    """
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(chat_id=str(chat_id)).first()
        if not user or user.plan_type == 'FREE' or user.plan_type is None:
            return False
        return True 
    finally:
        db.close()
