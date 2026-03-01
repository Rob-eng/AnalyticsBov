import os
import requests
import json
from app.saas.plans import META_ACCESS_TOKEN, META_PHONE_ID

# A API da Meta usa versões. A v18.0 ou v19.0 são as mais recentes e estáveis.
GRAPH_API_URL = f"https://graph.facebook.com/v19.0/{META_PHONE_ID}/messages"

def send_whatsapp_text(to_phone: str, message_body: str):
    """
    Envia uma mensagem de texto simples usando a API Oficial do WhatsApp Cloud.
    to_phone: O telefone do destinatário com DDI (Ex: 5511999999999)
    """
    
    if not META_ACCESS_TOKEN or not META_PHONE_ID:
        print("❌ ERRO: META_ACCESS_TOKEN ou META_PHONE_ID não configurados.")
        return False

    headers = {
        "Authorization": f"Bearer {META_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_phone,
        "type": "text",
        "text": {
            "preview_url": False,
            "body": message_body
        }
    }
    
    try:
        response = requests.post(GRAPH_API_URL, headers=headers, json=payload, timeout=10)
        
        if response.status_code in (200, 201):
            print(f"✅ Mensagem WA enviada para {to_phone}")
            return True
        else:
            print(f"❌ Erro ao enviar WA ({response.status_code}): {response.text}")
            return False
            
    except Exception as e:
        print(f"⚠️ Erro de conexão com a Graph API: {e}")
        return False

