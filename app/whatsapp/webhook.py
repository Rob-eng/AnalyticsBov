from fastapi import APIRouter, Request, HTTPException, Query
from fastapi.responses import PlainTextResponse
import os
import json

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
    Isto é chamado apenas 1 vez quando você configura a URL no Meta Developer Dashboard.
    """
    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("✅ Webhook do WhatsApp verificado com sucesso pela Meta!")
        # A Meta espera receber apenas o `challenge` seco no body
        return PlainTextResponse(content=challenge, status_code=200)
    raise HTTPException(status_code=403, detail="Token de verificação inválido")

@router.post("/")
async def receive_message(request: Request):
    """
    Endpoint que recebe TODAS as mensagens ativas, botões clicados e recibos de leitura do WhatsApp.
    """
    body = await request.json()
    # Descomente para debug intenso caso não saiba o formato exato que a Meta está enviando:
    # print("📩 Nova notificação da Meta recebida:", json.dumps(body, indent=2))
    
    # Validação básica do objeto Meta
    if body.get("object") == "whatsapp_business_account":
        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                
                # A Meta envia notificações de mensagens lidas/entregues aqui também.
                # Só nos importamos se for uma 'message' real de um usuário
                if "messages" in value:
                    for msg in value["messages"]:
                        sender_phone = msg.get("from")
                        msg_id = msg.get("id")
                        msg_type = msg.get("type")
                        
                        # Extrai o texto base
                        texto = ""
                        if msg_type == "text":
                            texto = msg.get("text", {}).get("body", "")
                        elif msg_type == "interactive":
                            # Quando o usuário clica num botão ou lista
                            interactive = msg.get("interactive", {})
                            if interactive.get("type") == "button_reply":
                                texto = interactive.get("button_reply", {}).get("id", "")
                            elif interactive.get("type") == "list_reply":
                                texto = interactive.get("list_reply", {}).get("id", "")
                        
                        print(f"[{sender_phone}] mandou: {texto}")
                        # TODO: Integrar com a state machine do Bot

    # A Meta sempre espera um 200 OK RÁPIDO (< 2 segundos), senão ela fica reenviando a mesma mensagem
    return {"status": "ok"}
