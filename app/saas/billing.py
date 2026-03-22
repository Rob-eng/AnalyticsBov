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
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except ValueError:
        return {"error": "Invalid payload"}, 400
    except stripe.error.SignatureVerificationError:
        return {"error": "Invalid signature"}, 400

    # Handle the checkout.session.completed event
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        chat_id = session.get('client_reference_id')
        plan = session.get('metadata', {}).get('plan', 'PRO')
        sub_id = session.get('subscription')

        if chat_id:
            db = SessionLocal()
            try:
                user = db.query(User).filter_by(chat_id=str(chat_id)).first()
                if user:
                    user.plan_type = plan
                    user.stripe_subscription_id = sub_id
                    db.commit()
                    logging.info(f"✅ Usuário {chat_id} promovido para {plan}!")
            except Exception as e:
                logging.error(f"Database error on webhook: {e}")
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
