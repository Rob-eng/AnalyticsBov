from fastapi import APIRouter, Request, HTTPException
from telegram import Update
import os
import json
from app.config import Config
from app.bot import create_bot_application

router = APIRouter(prefix="/webhook/telegram", tags=["Telegram Webhook"])

# Global Application instance to avoid re-initializing on each request
# We'll initialize it once when the router starts
_bot_app = None

async def get_bot_app():
    global _bot_app
    if _bot_app is None:
        from app.bot import create_bot_application
        # We don't need post_init here as we manage scheduler separately or in startup
        _bot_app = create_bot_application()
        await _bot_app.initialize()
    return _bot_app

@router.post("/{token}")
async def telegram_webhook(token: str, request: Request):
    """
    Recebe atualizações do Telegram via Webhook.
    O token na URL serve como segurança simples.
    """
    if token != Config.TELEGRAM_TOKEN:
        raise HTTPException(status_code=403, detail="Token inválido")
    
    try:
        data = await request.json()
        app = await get_bot_app()
        
        # Converte o JSON em um objeto Update do Telegram
        update = Update.de_json(data, app.bot)
        
        # Processa a atualização de forma assíncrona
        await app.process_update(update)
        
        return {"status": "ok"}
    except Exception as e:
        print(f"❌ Erro no Webhook do Telegram: {e}")
        return {"status": "error", "message": str(e)}

@router.get("/setup")
async def setup_webhook():
    """
    Configura o URL do Webhook no Telegram.
    Deve ser chamado manualmente ou no startup.
    """
    url = os.getenv("TELEGRAM_WEBHOOK_URL")
    if not url:
        return {"status": "error", "message": "TELEGRAM_WEBHOOK_URL não definida."}
    
    webhook_url = f"{url}/webhook/telegram/{Config.TELEGRAM_TOKEN}"
    app = await get_bot_app()
    
    # Remove Polling anterior e define Webhook
    success = await app.bot.set_webhook(url=webhook_url, drop_pending_updates=True)
    
    if success:
        return {"status": "success", "url": webhook_url}
    else:
        return {"status": "error", "message": "Falha ao definir Webhook."}
