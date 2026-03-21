import stripe
import os
from app.config import Config
from app.models import SessionLocal, User
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import RedirectResponse
import logging

stripe.api_key = os.getenv("STRIPE_API_KEY")

router = APIRouter(prefix="/billing", tags=["Billing"])

# Plan Configuration
PLANS = {
    "FREE": {"name": "Plano Bronze", "price": 0, "limit": 3},
    "PRO": {"name": "Plano Ouro", "price": 99.00, "price_id": os.getenv("STRIPE_PRO_PRICE_ID")},
    "ENTERPRISE": {"name": "Plano Diamond", "price": 499.00, "price_id": os.getenv("STRIPE_ENTERPRISE_PRICE_ID")}
}

@router.get("/checkout/{plan}/{chat_id}")
async def create_checkout_session(plan: str, chat_id: str):
    """Cria uma sessão de checkout do Stripe para o plano escolhido."""
    if plan not in PLANS or plan == "FREE":
        raise HTTPException(status_code=400, detail="Plano inválido para cobrança")
    
    plan_info = PLANS[plan]
    
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price': plan_info["price_id"],
                'quantity': 1,
            }],
            mode='subscription',
            success_url=f"https://analyticsbov-production.up.railway.app/?status=success&chat_id={chat_id}",
            cancel_url=f"https://analyticsbov-production.up.railway.app/?status=cancel&chat_id={chat_id}",
            client_reference_id=chat_id,
            metadata={
                "chat_id": chat_id,
                "plan": plan
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
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")

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
            # Check daily usage logic could go here
            return False # For now, limit strictly if we want to force payment
        return True # PRO or above has unlimited access
    finally:
        db.close()
