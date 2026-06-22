import os
import requests
import json
from io import BytesIO
from app.saas.plans import META_ACCESS_TOKEN, META_PHONE_ID

# A API da Meta usa versões. A v22.0 é a mais recente.
GRAPH_API_URL = f"https://graph.facebook.com/v22.0/{META_PHONE_ID}/messages"
MEDIA_UPLOAD_URL = f"https://graph.facebook.com/v22.0/{META_PHONE_ID}/media"

HEADERS = {
    "Authorization": f"Bearer {META_ACCESS_TOKEN}",
}


def _check_credentials():
    if not META_ACCESS_TOKEN or not META_PHONE_ID:
        print("❌ ERRO: META_ACCESS_TOKEN ou META_PHONE_ID não configurados.", flush=True)
        return False
    return True


def _sanitize_string(s: str) -> str:
    """Remove tokens, secrets ou chaves longas de strings de log para segurança."""
    import re
    if not s:
        return s
    # Remove strings do tipo token da Meta (EAAC... ou alfanuméricas muito longas)
    return re.sub(r'[A-Za-z0-9+/]{30,}', '[SECRET_TOKEN_REMOVED]', s)


_META_ERROR_MAP = {
    131047: "Janela de 24h expirada (user não interagiu recentemente)",
    131051: "Tipo de mensagem não suportado",
    132001: "Template não encontrado (não existe ou nome incorreto)",
    132005: "Template com parâmetros inválidos (quantidade ou formato errado)",
    132007: "Template indisponível (rejeitado, pausado ou desabilitado)",
    132012: "Template com muitos parâmetros",
    132015: "Template aguardando aprovação",
    133004: "Servidor da Meta indisponível temporariamente",
    130429: "Rate limit atingido (muitas mensagens)",
    131026: "Mensagem não entregue (usuário bloqueou ou número inválido)",
    131053: "Upload de mídia falhou na Meta",
}


def _send_message(payload):
    """Envia uma mensagem via Graph API."""
    headers = {**HEADERS, "Content-Type": "application/json"}
    try:
        response = requests.post(GRAPH_API_URL, headers=headers, json=payload, timeout=15)
        if response.status_code in (200, 201):
            return True
        else:
            # Extrair código de erro da Meta para diagnóstico detalhado
            meta_code = None
            meta_title = ""
            try:
                err_data = response.json().get("error", {})
                meta_code = err_data.get("code")
                meta_title = err_data.get("error_data", {}).get("details", "")
                if not meta_title:
                    meta_title = err_data.get("message", "")
            except Exception:
                pass

            reason = _META_ERROR_MAP.get(meta_code, "Código desconhecido")
            sanitized_txt = _sanitize_string(response.text)
            print(
                f"❌ WA send error ({response.status_code}) | "
                f"Meta code: {meta_code} → {reason} | "
                f"Detail: {sanitized_txt[:300]}",
                flush=True
            )
            return False
    except Exception as e:
        sanitized_err = _sanitize_string(str(e))
        print(f"⚠️ WA connection error: {sanitized_err}", flush=True)
        return False


def send_whatsapp_text(to_phone: str, message_body: str):
    """
    Envia uma mensagem de texto simples usando a API Oficial do WhatsApp Cloud.
    to_phone: O telefone do destinatário com DDI (Ex: 5511999999999)
    """
    if not _check_credentials():
        return False

    # WhatsApp tem limite de 4096 chars por mensagem
    if len(message_body) > 4096:
        message_body = message_body[:4090] + "\n..."

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

    success = _send_message(payload)
    if success:
        print(f"✅ WA texto enviado para {to_phone}", flush=True)
    return success


def _upload_media(file_buffer, mime_type, filename="file"):
    """
    Faz upload de um arquivo de mídia para a Meta e retorna o media_id.
    file_buffer: BytesIO ou bytes
    mime_type: 'image/png', 'image/jpeg', 'video/mp4'
    """
    if not _check_credentials():
        return None

    if isinstance(file_buffer, BytesIO):
        file_buffer.seek(0)
        file_data = file_buffer.read()
    elif isinstance(file_buffer, bytes):
        file_data = file_buffer
    else:
        print(f"❌ WA upload: tipo de buffer não suportado: {type(file_buffer)}", flush=True)
        return None

    # Meta espera multipart/form-data
    print(f"📡 [WA-UPLOAD] Enviando {len(file_data)//1024} KB ({mime_type})...", flush=True)
    files = {
        'file': (filename, file_data, mime_type),
    }
    data = {
        'messaging_product': 'whatsapp',
        'type': mime_type,
    }

    try:
        response = requests.post(
            MEDIA_UPLOAD_URL,
            headers=HEADERS,
            files=files,
            data=data,
            timeout=60
        )

        if response.status_code in (200, 201):
            media_id = response.json().get('id')
            print(f"✅ WA media uploaded: {media_id} ({mime_type})", flush=True)
            return media_id
        else:
            sanitized_txt = _sanitize_string(response.text)
            print(f"❌ WA upload error ({response.status_code}): {sanitized_txt[:300]}", flush=True)
            return None
    except Exception as e:
        sanitized_err = _sanitize_string(str(e))
        print(f"⚠️ WA upload connection error: {sanitized_err}", flush=True)
        return None


def download_whatsapp_media(media_id: str):
    """
    Downloads media from Meta using media_id.
    1. Gets the URL for the media.
    2. Downloads the actual bytes from that URL.
    """
    if not _check_credentials():
        return None
        
    media_info_url = f"https://graph.facebook.com/v22.0/{media_id}"
    
    try:
        # Step 1: Get the download URL
        response = requests.get(media_info_url, headers=HEADERS, timeout=15)
        if response.status_code == 200:
            media_url = response.json().get('url')
            if not media_url:
                print(f"❌ WA media: No URL found in response for {media_id}", flush=True)
                return None
            
            # Step 2: Download the file bytes
            # Note: The download request must ALSO have the Authorization header
            media_response = requests.get(media_url, headers=HEADERS, timeout=60)
            if media_response.status_code == 200:
                print(f"✅ WA media downloaded: {len(media_response.content)//1024} KB", flush=True)
                return media_response.content
            else:
                print(f"❌ WA media download failed ({media_response.status_code})", flush=True)
        else:
            sanitized_txt = _sanitize_string(response.text)
            print(f"❌ WA media info failed ({response.status_code}): {sanitized_txt[:300]}", flush=True)
    except Exception as e:
        sanitized_err = _sanitize_string(str(e))
        print(f"⚠️ WA media download connection error: {sanitized_err}", flush=True)
        
    return None


def send_whatsapp_image_by_id(to_phone: str, media_id: str, caption: str = ""):
    """
    Envia uma imagem que já foi enviada/upload na Meta usando o media_id.
    Isso otimiza o fluxo de fallback sem a necessidade de múltiplos uploads.
    """
    if not _check_credentials():
        return False

    caption = caption.replace('_', '').strip()
    if len(caption) > 1024:
        caption = caption[:1020] + "..."

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_phone,
        "type": "image",
        "image": {
            "id": media_id,
            "caption": caption
        }
    }

    success = _send_message(payload)
    if success:
        print(f"✅ WA imagem enviada via media_id para {to_phone}", flush=True)
    return success


def send_whatsapp_image(to_phone: str, image_buffer, caption: str = ""):
    """
    Envia uma imagem via WhatsApp Cloud API.
    image_buffer: BytesIO buffer contendo PNG ou JPEG (máx 5MB)
    caption: texto opcional (máx 1024 chars)
    """
    if not _check_credentials():
        return False

    # Limpar formatação Markdown (WhatsApp usa *bold* mas não suporta _italic_ igual)
    caption = caption.replace('_', '').strip()
    if len(caption) > 1024:
        caption = caption[:1020] + "..."

    # Upload da imagem primeiro
    media_id = _upload_media(image_buffer, "image/png", "map.png")
    if not media_id:
        # Fallback: envia só o texto
        print("⚠️ WA: Upload falhou, enviando só texto", flush=True)
        return send_whatsapp_text(to_phone, caption or "Não foi possível enviar a imagem.")

    return send_whatsapp_image_by_id(to_phone, media_id, caption)


def send_whatsapp_video(to_phone: str, video_buffer, caption: str = ""):
    """
    Envia um vídeo via WhatsApp Cloud API.
    video_buffer: BytesIO buffer contendo MP4 H.264 (máx 16MB)
    caption: texto opcional (máx 1024 chars)
    """
    if not _check_credentials():
        return False

    caption = caption.replace('_', '').strip()
    if len(caption) > 1024:
        caption = caption[:1020] + "..."

    media_id = _upload_media(video_buffer, "video/mp4", "terrain.mp4")
    if not media_id:
        print("⚠️ WA: Upload de vídeo falhou, enviando só texto", flush=True)
        return send_whatsapp_text(to_phone, caption or "Não foi possível enviar o vídeo.")

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_phone,
        "type": "video",
        "video": {
            "id": media_id,
            "caption": caption
        }
    }

    success = _send_message(payload)
    if success:
        print(f"✅ WA vídeo enviado para {to_phone}", flush=True)
    return success


def send_whatsapp_buttons(to_phone: str, body_text: str, buttons: list):
    """
    Envia uma mensagem com botões interativos (Reply Buttons — máx 3).
    buttons: lista de dicts com 'id' e 'title' (máx 20 chars cada)
    Exemplo: [{"id": "btn_ndvi", "title": "🌿 NDVI"}, ...]
    """
    if not _check_credentials():
        return False

    # Limitar a 3 botões (limite da Meta API)
    buttons = buttons[:3]

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_phone,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body_text[:1024]},
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {
                            "id": btn["id"][:256],
                            "title": btn["title"][:20]
                        }
                    }
                    for btn in buttons
                ]
            }
        }
    }

    success = _send_message(payload)
    if success:
        print(f"✅ WA buttons enviados para {to_phone}", flush=True)
    return success

def send_whatsapp_menu(to_phone: str):
    """
    Envia uma mensagem interativa do tipo "List" para funcionar como um Menu Principal.
    """
    if not _check_credentials():
        return False

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_phone,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "header": {
                "type": "text",
                "text": "Agro Analytics 🐂"
            },
            "body": {
                "text": "Escolha uma das opções abaixo para continuar:"
            },
            "footer": {
                "text": "Menu Principal"
            },
            "action": {
                "button": "Ver Opções",
                "sections": [
                    {
                        "title": "Cotações e Mercado",
                        "rows": [
                            {
                                "id": "TRIGGER_COTACAO",
                                "title": "📊 Cotação Atual"
                            },
                            {
                                "id": "TRIGGER_MERCADO_FUTURO",
                                "title": "🔮 Mercado Futuro"
                            }
                        ]
                    },
                    {
                        "title": "Análise Ambiental",
                        "rows": [
                            {
                                "id": "TRIGGER_PREVISAO_CHUVA",
                                "title": "🌧️ Previsão de Chuva"
                            },
                            {
                                "id": "TRIGGER_NDVI",
                                "title": "🌿 Análise NDVI"
                            },
                            {
                                "id": "TRIGGER_MDT",
                                "title": "🏔️ Terreno (MDT)"
                            }
                        ]
                    },
                    {
                        "title": "Minhas Propriedades",
                        "rows": [
                            {
                                "id": "TRIGGER_LISTAR",
                                "title": "📌 Listar Propriedades"
                            }
                        ]
                    }
                ]
            }
        }
    }

    success = _send_message(payload)
    if success:
        print(f"✅ WA Menu enviado para {to_phone}", flush=True)
    return success

def send_whatsapp_template_alert(to_phone: str, media_id: str, prop_nome: str, data_str: str, ndvi_val: str):
    """
    Envia um Message Template contendo mídia e variáveis, usado para alertas fora da janela de 24h.
    O template 'alerta_ndvi_satelite' precisa estar criado e aprovado na Meta Business Suite.
    """
    if not _check_credentials():
        return False

    template_name = os.getenv("WHATSAPP_NDVI_TEMPLATE_NAME", "alerta_ndvi_satelite")

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_phone,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {
                "code": "pt_BR"
            },
            "components": [
                {
                    "type": "header",
                    "parameters": [
                        {
                            "type": "image",
                            "image": {
                                "id": media_id
                            }
                        }
                    ]
                },
                {
                    "type": "body",
                    "parameters": [
                        {
                            "type": "text",
                            "text": str(prop_nome)[:128]
                        },
                        {
                            "type": "text",
                            "text": str(data_str)[:128]
                        },
                        {
                            "type": "text",
                            "text": str(ndvi_val)[:128]
                        }
                    ]
                }
            ]
        }
    }

    success = _send_message(payload)
    if success:
        print(f"✅ WA template enviado para {to_phone}", flush=True)
    return success

def send_whatsapp_market_template(to_phone: str, media_id: str, variables: list = None):
    """
    Envia um Message Template para o relatório de mercado semanal.
    O template 'alerta_cotacao_semanal' deve ter um Header de Mídia (Imagem) e variáveis de texto no Corpo.
    """
    if not _check_credentials():
        return False

    template_name = os.getenv("WHATSAPP_MARKET_TEMPLATE_NAME", "alerta_cotacao_semanal")

    parameters = []
    if variables:
        for var in variables:
            parameters.append({"type": "text", "text": str(var)[:32768]})

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_phone,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {
                "code": "pt_BR"
            },
            "components": [
                {
                    "type": "header",
                    "parameters": [
                        {
                            "type": "image",
                            "image": {
                                "id": media_id
                            }
                        }
                    ]
                }
            ]
        }
    }
    
    if parameters:
        payload["template"]["components"].append({
            "type": "body",
            "parameters": parameters
        })

    success = _send_message(payload)
    if success:
        print(f"✅ WA Market template enviado para {to_phone}", flush=True)
    return success
