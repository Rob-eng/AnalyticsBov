from fastapi import APIRouter, Request, HTTPException, Query, BackgroundTasks
from fastapi.responses import PlainTextResponse
import os
import json
from app.whatsapp.sender import send_whatsapp_text
from app.agent import process_whatsapp_message

router = APIRouter(prefix="/webhook/whatsapp", tags=["WhatsApp"])

# O VERIFY_TOKEN é criado por nós e deve ser inserido no painel da Meta ao configurar o Webhook
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "meu_token_secreto_agro_123")

@router.get("/")
async def verify_webhook(
    mode: str = Query(None, alias="hub.mode"),
    token: str = Query(None, alias="hub.verify_token"),
    challenge: str = Query(None, alias="hub.challenge")
):
    """
    Endpoint para verificação inicial do Webhook solicitada pela Meta (Facebook).
    """
    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("✅ Webhook do WhatsApp verificado com sucesso pela Meta!")
        return PlainTextResponse(content=challenge, status_code=200)
    raise HTTPException(status_code=403, detail="Token de verificação inválido")

@router.post("/")
async def receive_message(request: Request, background_tasks: BackgroundTasks):
    """
    Endpoint que recebe TODAS as mensagens ativas, botões clicados e recibos de leitura do WhatsApp.
    """
    body = await request.json()
    
    if body.get("object") == "whatsapp_business_account":
        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                
                if "messages" in value:
                    for msg in value["messages"]:
                        sender_phone = msg.get("from")
                        msg_type = msg.get("type")
                        
                        texto = ""
                        if msg_type == "text":
                            texto = msg.get("text", {}).get("body", "")
                        elif msg_type == "interactive":
                            interactive = msg.get("interactive", {})
                            if interactive.get("type") == "button_reply":
                                texto = interactive.get("button_reply", {}).get("id", "")
                            elif interactive.get("type") == "list_reply":
                                texto = interactive.get("list_reply", {}).get("id", "")
                        
                        print(f"[Webhook] {sender_phone} disse: {texto}")
                        
                        # ⚠️ Delega a resposta e o pensamento da IA para uma BackgroundTask do FastAPI
                        # Isso garante que a Meta receba o '200 OK' em 1s, enquanto o ChatGPT tem o tempo dele
                        if texto:
                            background_tasks.add_task(process_whatsapp_message, sender_phone, texto)

    # A Meta sempre espera um 200 OK
    return {"status": "ok"}
