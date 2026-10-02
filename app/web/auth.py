"""
Login da plataforma web pelo próprio bot (sem senha, sem SMS).

1. O site pede um código (POST /api/v1/auth/start) e mostra dois botões:
   WhatsApp → wa.me/<número do bot>?text=ENTRAR <código>
   Telegram → t.me/<bot>?start=login_<código>
2. O usuário envia a mensagem; o webhook do bot chama confirm_login_code().
   Como é o usuário quem escreve, a janela de 24h do WhatsApp abre e a
   confirmação sai como texto livre (não precisa de template).
3. O navegador consulta GET /api/v1/auth/poll; quando confirmado, recebe o
   cookie de sessão (assinado, HttpOnly) e o código é consumido.

A identidade é a mesma do bot: users.chat_id (telefone no WhatsApp, id no Telegram).
"""
import os
import re
import secrets
from datetime import datetime, timedelta

import requests
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

CODE_TTL = timedelta(minutes=10)
SESSION_MAX_AGE = 30 * 24 * 3600          # 30 dias
SESSION_COOKIE = "ab_session"
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # sem 0/O/1/I
CODE_RE = re.compile(r"^\s*ENTRAR\s+([A-Z0-9]{6})\s*$", re.IGNORECASE)
TELEGRAM_BOT_USERNAME = os.getenv("TELEGRAM_BOT_USERNAME", "AnalyticsBovBot")

_wa_number_cache = {}


def _serializer():
    secret = os.getenv("WEB_SECRET_KEY")
    if not secret:
        raise RuntimeError("WEB_SECRET_KEY não configurada")
    return URLSafeTimedSerializer(secret, salt="web-session")


def whatsapp_display_number() -> str:
    """Número do bot no WhatsApp (só dígitos) — WA_DISPLAY_PHONE ou consulta à Graph API (cache)."""
    if os.getenv("WA_DISPLAY_PHONE"):
        return re.sub(r"\D", "", os.getenv("WA_DISPLAY_PHONE"))
    if "n" not in _wa_number_cache:
        resp = requests.get(
            f"https://graph.facebook.com/v22.0/{os.getenv('META_PHONE_ID')}",
            params={"fields": "display_phone_number"},
            headers={"Authorization": f"Bearer {os.getenv('META_ACCESS_TOKEN')}"}, timeout=10,
        )
        resp.raise_for_status()
        _wa_number_cache["n"] = re.sub(r"\D", "", resp.json().get("display_phone_number", ""))
    return _wa_number_cache["n"]


def create_login_code() -> dict:
    from app.models import SessionLocal, WebLoginCode
    code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))
    now = datetime.utcnow()
    db = SessionLocal()
    try:
        db.query(WebLoginCode).filter(WebLoginCode.expires_at < now - timedelta(days=1)).delete()
        db.add(WebLoginCode(code=code, created_at=now, expires_at=now + CODE_TTL))
        db.commit()
    finally:
        db.close()
    links = {"telegram_url": f"https://t.me/{TELEGRAM_BOT_USERNAME}?start=login_{code}"}
    try:
        links["whatsapp_url"] = f"https://wa.me/{whatsapp_display_number()}?text=ENTRAR%20{code}"
    except Exception as e:
        print(f"[WEB AUTH] Número do WhatsApp indisponível: {e}", flush=True)
        links["whatsapp_url"] = None
    return {"code": code, "expires_in": int(CODE_TTL.total_seconds()), **links}


def confirm_login_code(code: str, chat_id: str, platform: str, display_name: str = None) -> bool:
    """Chamado pelo bot quando o usuário envia o código. Cria o usuário se ainda não existir."""
    from app.models import SessionLocal, User, WebLoginCode
    code = (code or "").strip().upper()
    now = datetime.utcnow()
    db = SessionLocal()
    try:
        row = db.query(WebLoginCode).filter_by(code=code).first()
        if not row or row.expires_at < now or row.confirmed_chat_id or row.consumed_at:
            return False
        if not db.query(User).filter_by(chat_id=str(chat_id)).first():
            db.add(User(chat_id=str(chat_id), username=display_name, platform=platform))
        row.confirmed_chat_id = str(chat_id)
        row.confirmed_platform = platform
        row.confirmed_at = now
        db.commit()
        return True
    finally:
        db.close()


def poll_login_code(code: str):
    """'pending' | 'expired' | chat_id confirmado (consome o código)."""
    from app.models import SessionLocal, WebLoginCode
    now = datetime.utcnow()
    db = SessionLocal()
    try:
        row = db.query(WebLoginCode).filter_by(code=(code or "").strip().upper()).first()
        if not row or row.consumed_at or row.expires_at < now:
            return "expired"
        if not row.confirmed_chat_id:
            return "pending"
        row.consumed_at = now
        db.commit()
        return row.confirmed_chat_id
    finally:
        db.close()


def make_session_token(chat_id: str) -> str:
    return _serializer().dumps({"cid": str(chat_id)})


def read_session_token(token: str):
    try:
        return _serializer().loads(token, max_age=SESSION_MAX_AGE).get("cid")
    except (BadSignature, SignatureExpired):
        return None


def ensure_personal_organization(chat_id: str):
    """Todo usuário tem ao menos a organização dele (modo produtor)."""
    from app.models import SessionLocal, User, Organization, OrganizationMember
    db = SessionLocal()
    try:
        if db.query(OrganizationMember).filter_by(chat_id=str(chat_id)).first():
            return
        user = db.query(User).filter_by(chat_id=str(chat_id)).first()
        org = Organization(name=(user.username if user and user.username else "Minhas fazendas"),
                           kind="produtor", owner_chat_id=str(chat_id))
        db.add(org)
        db.flush()
        db.add(OrganizationMember(organization_id=org.id, chat_id=str(chat_id), role="owner"))
        db.commit()
    finally:
        db.close()


def login_reply_text() -> str:
    return "✅ *Acesso liberado!* Pode voltar ao navegador — você já está conectado na plataforma web."
