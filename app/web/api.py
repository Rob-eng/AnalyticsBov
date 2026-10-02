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


# ── Propriedades (mesma lista do bot) ─────────────────────────────────────────

from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response as RawResponse
from typing import Optional

from pydantic import BaseModel, Field

from app.web import properties as P


class NewProperty(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    car_code: Optional[str] = None
    lat: Optional[float] = Field(default=None, ge=-90, le=90)
    lon: Optional[float] = Field(default=None, ge=-180, le=180)


class RenameProperty(BaseModel):
    name: str = Field(min_length=1, max_length=80)


def _own(property_id: int, user) -> None:
    if P.owner_of(property_id) != user.chat_id:
        raise HTTPException(404, "Propriedade não encontrada")


async def _call(fn, *args):
    try:
        return await run_in_threadpool(fn, *args)
    except P.PropertyError as e:
        raise HTTPException(422, str(e))


@router.get("/properties")
def list_properties(user=Depends(current_user)):
    return P.list_properties(user.chat_id)


@router.post("/properties", status_code=201)
async def create_property(body: NewProperty, user=Depends(current_user)):
    return await _call(P.create_property, user.chat_id, body.name, body.car_code, body.lat, body.lon)


@router.get("/car/lookup")
async def car_lookup(lat: float, lon: float, request: Request, user=Depends(current_user)):
    _rate_limit(f"lookup:{user.chat_id}", limit=60)
    return {"candidates": await _call(P.lookup_car_at, lat, lon)}


@router.get("/properties/{property_id}")
async def get_property(property_id: int, user=Depends(current_user)):
    _own(property_id, user)
    return await _call(P.get_property, property_id)


@router.patch("/properties/{property_id}")
def rename_property(property_id: int, body: RenameProperty, user=Depends(current_user)):
    _own(property_id, user)
    from app.models import SessionLocal, FavoriteLocation
    db = SessionLocal()
    try:
        db.query(FavoriteLocation).filter_by(id=property_id).update({"name": body.name.strip()})
        db.commit()
    finally:
        db.close()
    return P.get_property(property_id)


@router.delete("/properties/{property_id}", status_code=204)
def delete_property(property_id: int, user=Depends(current_user)):
    _own(property_id, user)
    P.delete_property(property_id)
    return RawResponse(status_code=204)


@router.post("/properties/{property_id}/sync-car")
async def sync_car(property_id: int, body: Optional[dict] = None, user=Depends(current_user)):
    """Vincula (ou atualiza) o CAR: usa o código enviado, o já salvo ou o encontrado na coordenada."""
    _own(property_id, user)
    prop = P.get_property(property_id)
    code = (body or {}).get("car_code") or prop["car_code"]
    if not code and prop["lat"] is not None:
        found = await _call(P.lookup_car_at, prop["lat"], prop["lon"])
        code = found[0]["car_code"] if found else None
    if not code:
        raise HTTPException(422, "Não encontrei um imóvel do CAR nesta localização. Informe o código.")
    return await _call(P.sync_car, property_id, code)


@router.get("/properties/{property_id}/layers")
async def property_layers(property_id: int, user=Depends(current_user)):
    _own(property_id, user)
    return await _call(P.get_layers, property_id)


@router.get("/properties/{property_id}/ndvi")
async def property_ndvi(property_id: int, user=Depends(current_user)):
    _own(property_id, user)
    _rate_limit(f"ndvi:{user.chat_id}", limit=30)
    return await _call(P.latest_ndvi, user.chat_id, property_id)


def _download(content: bytes, filename: str, media_type: str):
    from urllib.parse import quote
    return RawResponse(content, media_type=media_type,
                       headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"})


@router.get("/properties/{property_id}/car.zip")
async def property_zip(property_id: int, user=Depends(current_user)):
    _own(property_id, user)
    data, name = await _call(P.build_zip, property_id)
    return _download(data, name, "application/zip")


@router.get("/properties/{property_id}/map.png")
async def property_map(property_id: int, user=Depends(current_user)):
    _own(property_id, user)
    _rate_limit(f"map:{user.chat_id}", limit=20)
    data, name = await _call(P.build_map_png, property_id)
    return _download(data, name, "image/png")
