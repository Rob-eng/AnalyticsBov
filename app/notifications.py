import requests
from app.config import Config

def notify_admin(message: str):
    """
    Envia uma notificação para o Admin via Telegram.
    Útil para erros críticos ou feedback de usuários.
    """
    if not Config.TELEGRAM_TOKEN or not Config.ADMIN_CHAT_ID:
        print(f"⚠️ [NOTIFY] Admin não configurado. Mensagem: {message}")
        return

    url = f"https://api.telegram.org/bot{Config.TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": Config.ADMIN_CHAT_ID,
        "text": f"🚨 *NOTIFICAÇÃO AGRO BOT*\n\n{message}",
        "parse_mode": "Markdown"
    }
    
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code != 200:
            print(f"❌ [NOTIFY] Erro ao enviar para Telegram: {resp.text}")
    except Exception as e:
        print(f"❌ [NOTIFY] Falha na rede Telegram: {e}")

def notify_user_error(phone: str, error: str, context: str = "Ação desconhecida"):
    """Notifica o admin sobre um erro ocorrido com um usuário específico."""
    msg = (
        f"👤 *Usuário:* `{phone}`\n"
        f"🎯 *Contexto:* {context}\n"
        f"❌ *Erro:* {error}"
    )
    notify_admin(msg)

def notify_feedback(phone: str, feedback: str):
    """Notifica o admin sobre um feedback/sugestão recebida."""
    msg = (
        f"💬 *Feedback Recebido!*\n\n"
        f"👤 *Usuário:* `{phone}`\n"
        f"📝 *Mensagem:* {feedback}"
    )
    notify_admin(msg)
