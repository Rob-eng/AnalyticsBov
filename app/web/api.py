"""
API JSON da plataforma web — /api/v1.

Sessão por cookie assinado (app/web/auth.py). Os endpoints reaproveitam as
mesmas funções do bot (CAR, NDVI, mercado...), então web e bot dão sempre o
mesmo resultado.
"""
import os

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.web import auth

router = APIRouter(prefix="/api/v1", tags=["Web"])

_rate = {}


def _rate_limit(key: str, limit: int = 20, window: int = 600):
    import time
    now = time.time()
    hits = [t for t in _rate.get(key, []) if now - t < window]
    if len(hits) >= limit:
        raise HTTPException(429, "Muitas tentativas. Aguarde alguns minutos.")
    hits.append(now)
    _rate[key] = hits


def current_user(request: Request):
    from app.models import SessionLocal, User
    chat_id = auth.read_session_token(request.cookies.get(auth.SESSION_COOKIE, ""))
    if not chat_id:
        raise HTTPException(401, "Não autenticado")
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(chat_id=chat_id).first()
        if not user:
            raise HTTPException(401, "Usuário não encontrado")
        db.expunge(user)
        return user
    finally:
        db.close()


# ── Autenticação ──────────────────────────────────────────────────────────────

@router.post("/auth/start")
def auth_start(request: Request):
    _rate_limit(f"start:{request.client.host if request.client else '?'}")
    return auth.create_login_code()


@router.get("/auth/poll")
def auth_poll(code: str, request: Request, response: Response):
    _rate_limit(f"poll:{request.client.host if request.client else '?'}", limit=400)
    result = auth.poll_login_code(code)
    if result in ("pending", "expired"):
        return {"status": result}
    auth.ensure_personal_organization(result)
    response.set_cookie(
        auth.SESSION_COOKIE, auth.make_session_token(result), max_age=auth.SESSION_MAX_AGE,
        httponly=True, secure=os.getenv("WEB_INSECURE_COOKIE") != "1", samesite="lax", path="/",
    )
    return {"status": "ok"}


@router.post("/auth/logout")
def auth_logout(response: Response):
    response.delete_cookie(auth.SESSION_COOKIE, path="/")
    return {"status": "ok"}


# ── Conta ─────────────────────────────────────────────────────────────────────

@router.get("/me")
def me(user=Depends(current_user)):
    from app.models import SessionLocal, Organization, OrganizationMember
    db = SessionLocal()
    try:
        orgs = (db.query(Organization, OrganizationMember.role)
                .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
                .filter(OrganizationMember.chat_id == user.chat_id).all())
        organizations = [{"id": o.id, "name": o.name, "kind": o.kind, "role": role} for o, role in orgs]
    finally:
        db.close()
    return {
        "chat_id": user.chat_id,
        "name": user.username,
        "platform": user.platform or "telegram",
        "plan": user.plan_type or "FREE",
        "trial_expires_at": user.trial_expires_at.isoformat() if user.trial_expires_at else None,
        "organizations": organizations,
        "mode": "consultor" if any(o["kind"] == "consultoria" for o in organizations) else "produtor",
    }


# ── Propriedades (Fase 0: as mesmas cadastradas no bot) ───────────────────────

@router.get("/properties")
def list_properties(user=Depends(current_user)):
    from app.models import SessionLocal, FavoriteLocation
    db = SessionLocal()
    try:
        locs = (db.query(FavoriteLocation).filter_by(user_id=user.chat_id)
                .order_by(FavoriteLocation.created_at).all())
        return [{"id": l.id, "name": l.name, "lat": l.latitude, "lon": l.longitude} for l in locs]
    finally:
        db.close()
