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
@router.get("")
async def verify_webhook(
    mode: str = Query(None, alias="hub.mode"),
    token: str = Query(None, alias="hub.verify_token"),
    challenge: str = Query(None, alias="hub.challenge")
):
    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("✅ Webhook do WhatsApp verificado com sucesso pela Meta!")
        return PlainTextResponse(content=challenge, status_code=200)
    raise HTTPException(status_code=403, detail="Token de verificação inválido")

@router.post("/")
@router.post("")
async def receive_message(request: Request, background_tasks: BackgroundTasks):
    body = await request.json()
    
    if body.get("object") == "whatsapp_business_account":
        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                
                if "messages" in value:
                    # Mapeamento de Nomes de Perfil vindo da Meta
                    contacts_map = {}
                    for contact in value.get("contacts", []):
                        contacts_map[contact.get("wa_id")] = contact.get("profile", {}).get("name")

                    for msg in value["messages"]:
                        sender_phone = msg.get("from")
                        user_name = contacts_map.get(sender_phone)
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
                        
                        elif msg_type == "document":
                            doc = msg.get("document", {})
                            if doc.get("filename", "").lower().endswith(".zip"):
                                media_id = doc.get("id")
                                from app.models import log_activity
                                log_activity(sender_phone, "ZIP_UPLOAD", platform='whatsapp', details=doc.get("filename"), username=user_name)
                                from app.whatsapp.trigger_handler import process_whatsapp_zip_upload
                                background_tasks.add_task(process_whatsapp_zip_upload, sender_phone, media_id)
                        
                        print(f"[Webhook] {sender_phone} ({user_name}) disse: {texto if texto else msg_type}")
                        
                        # Detecção de Código CAR
                        import re
                        car_pattern = r"^[A-Z]{2}-\d{7}-[A-F0-9]{32}$"
                        if texto and re.match(car_pattern, texto.strip().upper()):
                            car_code = texto.strip().upper()
                            from app.models import log_activity
                            log_activity(sender_phone, "CAR_SEARCH", platform='whatsapp', details=car_code, username=user_name)
                            from app.whatsapp.trigger_handler import process_whatsapp_car_request
                            background_tasks.add_task(process_whatsapp_car_request, sender_phone, car_code)
                        
                        # Lógica de Chat IA
                        elif texto:
                            from app.models import log_activity
                            log_activity(sender_phone, "CHAT", platform='whatsapp', details=texto[:50], username=user_name)
                            background_tasks.add_task(process_whatsapp_message, sender_phone, texto)

    return {"status": "ok"}
