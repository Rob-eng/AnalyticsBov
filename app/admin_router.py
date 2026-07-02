from fastapi import APIRouter, BackgroundTasks, Depends, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from datetime import datetime, timedelta
import os
from app.auth import get_api_key

router = APIRouter(prefix="/admin", tags=["Admin Ingestion"])


# ─────────────────────────────────────────────────────────────────────────────
# Health & Monitoring
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/health/features")
def get_feature_health(
    hours: int = Query(24, description="Janela de tempo em horas para calcular erros"),
    api_key: str = Depends(get_api_key),
):
    """
    Retorna o status operacional de cada funcionalidade do sistema
    baseado nos registros da tabela ActivityLog.
    """
    from app.models import SessionLocal, ActivityLog
    from sqlalchemy import func

    # Mapa: nome_feature → lista de action values no ActivityLog
    FEATURES = {
        "NDVI":      ["NDVI", "NDVI_ALERT_SEND"],
        "Clima":     ["CLIMA", "HISTORICO"],
        "MDT":       ["MDT"],
        "CDA":       ["CDA", "CDA_SEARCH", "LEILAO"],
        "CAR":       ["CAR_SEARCH", "ZIP_UPLOAD"],
        "WhatsApp":  [],   # filtrado por platform
        "Telegram":  [],   # filtrado por platform
    }

    cutoff_24h = datetime.utcnow() - timedelta(hours=hours)
    cutoff_7d  = datetime.utcnow() - timedelta(days=7)

    db = SessionLocal()
    result = {}
    try:
        for feature, actions in FEATURES.items():
            # Queries especiais para plataformas
            if feature == "WhatsApp":
                base_q = db.query(ActivityLog).filter(ActivityLog.platform == "whatsapp")
            elif feature == "Telegram":
                base_q = db.query(ActivityLog).filter(ActivityLog.platform == "telegram")
            else:
                if not actions:
                    continue
                base_q = db.query(ActivityLog).filter(ActivityLog.action.in_(actions))

            # Último sucesso
            last_ok = (
                base_q.filter(ActivityLog.status == "SUCCESS")
                .order_by(ActivityLog.created_at.desc())
                .first()
            )

            # Erros recentes
            errors_24h = base_q.filter(
                ActivityLog.status == "ERROR",
                ActivityLog.created_at >= cutoff_24h,
            ).count()

            errors_7d = base_q.filter(
                ActivityLog.status == "ERROR",
                ActivityLog.created_at >= cutoff_7d,
            ).count()

            # Total de ações nos últimos 7 dias (para taxa de sucesso)
            total_7d = base_q.filter(ActivityLog.created_at >= cutoff_7d).count()

            # Última mensagem de erro
            last_err = (
                base_q.filter(
                    ActivityLog.status == "ERROR",
                    ActivityLog.error_message.isnot(None),
                )
                .order_by(ActivityLog.created_at.desc())
                .first()
            )

            # Status: ok / warn / error / unknown
            if last_ok is None:
                status = "unknown"
            elif errors_24h == 0:
                status = "ok"
            elif errors_24h <= 2:
                status = "warn"
            else:
                status = "error"

            success_rate = None
            if total_7d > 0:
                success_rate = round((total_7d - errors_7d) / total_7d * 100, 1)

            result[feature] = {
                "status": status,
                "last_success": last_ok.created_at.isoformat() if last_ok else None,
                "errors_24h": errors_24h,
                "errors_7d": errors_7d,
                "total_7d": total_7d,
                "success_rate_7d": success_rate,
                "last_error_msg": (last_err.error_message[:200] if last_err and last_err.error_message else None),
                "last_error_at": (last_err.created_at.isoformat() if last_err else None),
            }

    finally:
        db.close()

    # Status geral do sistema
    statuses = [v["status"] for v in result.values()]
    if "error" in statuses:
        overall = "degraded"
    elif "warn" in statuses:
        overall = "warn"
    elif all(s in ("ok", "unknown") for s in statuses):
        overall = "ok"
    else:
        overall = "ok"

    return {
        "overall": overall,
        "checked_at": datetime.utcnow().isoformat(),
        "window_hours": hours,
        "features": result,
    }


@router.get("/health/probes")
def get_probe_results(api_key: str = Depends(get_api_key)):
    """
    Retorna o último resultado de cada probe ativo.
    Busca o registro mais recente por probe_name na tabela health_check_results.
    """
    from app.models import SessionLocal, HealthCheckResult
    from sqlalchemy import func

    db = SessionLocal()
    try:
        # Subquery: max checked_at por probe_name
        sub = (
            db.query(
                HealthCheckResult.probe_name,
                func.max(HealthCheckResult.checked_at).label("latest"),
            )
            .group_by(HealthCheckResult.probe_name)
            .subquery()
        )
        rows = (
            db.query(HealthCheckResult)
            .join(
                sub,
                (HealthCheckResult.probe_name == sub.c.probe_name)
                & (HealthCheckResult.checked_at == sub.c.latest),
            )
            .all()
        )
        results = {
            r.probe_name: {
                "status":     r.status,
                "latency_ms": r.latency_ms,
                "message":    r.message,
                "checked_at": r.checked_at.isoformat() if r.checked_at else None,
            }
            for r in rows
        }
        statuses = [v["status"] for v in results.values()]
        overall = "error" if "error" in statuses else ("warn" if "warn" in statuses else "ok")
        return {
            "overall": overall,
            "checked_at": rows[0].checked_at.isoformat() if rows else None,
            "probes": results,
        }
    finally:
        db.close()


@router.post("/health/run")
async def run_health_probes(
    background_tasks: BackgroundTasks,
    api_key: str = Depends(get_api_key),
):
    """Aciona todos os health probes imediatamente (roda em background)."""
    from app.health_probe import run_all_probes

    background_tasks.add_task(run_all_probes)
    return {"status": "started", "message": "Health probes iniciados. Resultados em /admin/health/probes em ~30s."}


@router.get("/build-cda-comparisons")
@router.post("/build-cda-comparisons")
async def trigger_cda_comparisons(
    background_tasks: BackgroundTasks,
    api_key: str = Depends(get_api_key),
):
    """Reconstrói as comparações CDA vs Scot em background."""
    from app.cda_analytics import build_cda_scot_comparisons

    background_tasks.add_task(build_cda_scot_comparisons)
    return {"status": "started", "message": "Rebuild de comparações CDA vs Scot iniciado em background."}


@router.get("/cda/status")
def get_cda_status(api_key: str = Depends(get_api_key)):
    """Retorna o estado atual da captura de dados do Leilão CDA."""
    from app.models import SessionLocal, CdaEvent, CdaLotResult, CdaMarketComparison
    from sqlalchemy import func

    db = SessionLocal()
    try:
        total_events = db.query(CdaEvent).count()
        total_lots   = db.query(CdaLotResult).count()
        total_comps  = db.query(CdaMarketComparison).count()

        # Último evento scraped
        last_event = (
            db.query(CdaEvent)
            .filter(CdaEvent.event_date.isnot(None))
            .order_by(CdaEvent.event_date.desc())
            .first()
        )

        # Lots com qtde_animals preenchido (campo novo)
        lots_with_qty = db.query(CdaLotResult).filter(
            CdaLotResult.qtde_animals.isnot(None)
        ).count()

        # Lots por scrape_mode
        mode_counts = (
            db.query(CdaLotResult.scrape_mode, func.count(CdaLotResult.id))
            .group_by(CdaLotResult.scrape_mode)
            .all()
        )

        # Lots das últimas 24h
        recent_cutoff = datetime.utcnow() - timedelta(hours=24)
        recent_lots = db.query(CdaLotResult).filter(
            CdaLotResult.collected_at >= recent_cutoff
        ).count()

        has_recent_data = last_event is not None and (
            last_event.event_date >= datetime.utcnow() - timedelta(days=3)
        ) if last_event else False

        return {
            "status": "ok" if has_recent_data else "stale",
            "has_recent_data": has_recent_data,
            "total_events": total_events,
            "total_lots": total_lots,
            "total_market_comparisons": total_comps,
            "lots_with_qty_animals": lots_with_qty,
            "lots_by_scrape_mode": {m: c for m, c in mode_counts},
            "recent_lots_24h": recent_lots,
            "latest_event": {
                "name": last_event.event_name if last_event else None,
                "date": last_event.event_date.strftime("%d/%m/%Y") if last_event and last_event.event_date else None,
                "location": last_event.event_location if last_event else None,
                "url": last_event.source_url if last_event else None,
            } if last_event else None,
            "checked_at": datetime.utcnow().isoformat(),
        }
    finally:
        db.close()


@router.post("/ingest/mt")
async def trigger_mt_ingestion(background_tasks: BackgroundTasks, api_key: str = Depends(get_api_key)):
    """
    Aciona a carga em massa do Mato Grosso (MT) no servidor.
    A operação roda em segundo plano para não dar timeout.
    """
    from ingest_mt_wfs import download_and_ingest_mt_wfs
    
    # Adiciona a tarefa pesada à fila de background do FastAPI
    background_tasks.add_task(download_and_ingest_mt_wfs)
    
    return {
        "status": "Carga de MT iniciada com sucesso em segundo plano!",
        "mensagem": "Isso levará ~40 minutos. O servidor vai baixar ~20 partes de 10k registros cada e hidratar o banco PostGIS espacial."
    }

@router.get("/status/db")
def check_db_counts(api_key: str = Depends(get_api_key)):
    """
    Checks the number of rows in CARProperty and Users.
    """
    from app.models import CarSessionLocal, CARProperty, SessionLocal, User, ActivityLog, CdaEvent, CdaLotResult
    from sqlalchemy import func
    
    res = {}
    
    # Check CAR Properties (Pode ser lento se for milhoes, ok para MT/MS)
    car_session = CarSessionLocal()
    try:
        counts = car_session.query(CARProperty.uf, func.count(CARProperty.id)).group_by(CARProperty.uf).all()
        res["car_by_state"] = {uf: count for uf, count in counts}
        res["total_car"] = sum(count for uf, count in counts)
    except Exception as e:
        res["car_error"] = str(e)
    finally:
        car_session.close()

    # Check Bot Users
    db = SessionLocal()
    try:
        res["total_users"] = db.query(User).count()
        res["users_by_platform"] = {
            "whatsapp": db.query(User).filter(User.platform == 'whatsapp').count(),
            "telegram": db.query(User).filter(User.platform == 'telegram').count()
        }
        res["recent_logs"] = db.query(ActivityLog).order_by(ActivityLog.created_at.desc()).limit(10).all()
        # CDA stats
        res["cda_events"]     = db.query(CdaEvent).count()
        res["cda_lot_results"] = db.query(CdaLotResult).count()
    except Exception as e:
        res["user_error"] = str(e)
    finally:
        db.close()

    return res


@router.post("/ingest/cda")
async def trigger_cda_backfill(
    background_tasks: BackgroundTasks,
    max_pages: int = Query(10, description="Número máximo de páginas de resultados a varrer"),
    api_key: str = Depends(get_api_key)
):
    """
    Dispara imediatamente o backfill do Correa da Costa em background.
    Útil para forçar a primeira carga sem esperar o scheduler das 05:30.
    """
    from app.scraper_cda import run_cda_backfill
    from app.cda_analytics import build_cda_scot_comparisons

    def _run():
        try:
            print(f"[Admin] CDA backfill iniciado (max_pages={max_pages})...", flush=True)
            summary = run_cda_backfill(max_pages=max_pages, max_urls=None)
            print(f"[Admin] CDA backfill concluído: {summary}", flush=True)
            cmp_summary = build_cda_scot_comparisons()
            print(f"[Admin] CDA comparisons: {cmp_summary}", flush=True)
        except Exception as e:
            import traceback
            print(f"[Admin] ERRO no CDA backfill: {traceback.format_exc()}", flush=True)

    background_tasks.add_task(_run)
    return {
        "status": "started",
        "message": f"CDA backfill iniciado em background com max_pages={max_pages}. Acompanhe os logs do Railway.",
    }


@router.get("/dashboard", response_class=HTMLResponse)
async def admin_dashboard(request: Request, api_key: str = Query(None)):
    """
    Visualização das métricas de performance e uso do robô.
    """
    # 1. Segurança Simples via API Key na URL (Admin Only)
    if api_key != os.getenv("CAR_API_KEY", "your-default-secure-key"):
        return HTMLResponse("<h1>Acesso Negado 🚫</h1>", status_code=403)
        
    from app.models import SessionLocal, User, ActivityLog, Feedback, FavoriteLocation
    from sqlalchemy import func
    
    db = SessionLocal()
    try:
        # --- Lógica de Métricas ---
        total_users = db.query(User).count()
        wa_users = db.query(User).filter(User.platform == 'whatsapp').count()
        tg_users = db.query(User).filter(User.platform == 'telegram').count()
        
        pro_users = db.query(User).filter(User.plan_type != 'FREE').count()
        free_users = total_users - pro_users
        
        total_actions = db.query(ActivityLog).count()
        recent_feedbacks = db.query(Feedback).order_by(Feedback.created_at.desc()).limit(10).all()
        
        # Logs com Nomes de Usuários (Aumentado para 200 para não perder novos usuários)
        logs_query = db.query(ActivityLog, User.username).outerjoin(User, ActivityLog.user_id == User.chat_id).order_by(ActivityLog.created_at.desc()).limit(200).all()
        
        # Erros Recentes (Status = ERROR)
        recent_errors = db.query(ActivityLog, User.username).outerjoin(User, ActivityLog.user_id == User.chat_id).filter(ActivityLog.status == 'ERROR').order_by(ActivityLog.created_at.desc()).limit(10).all()

        # Atividade por Tipo (Pie Chart)
        action_stats = db.query(ActivityLog.action, func.count(ActivityLog.id)).group_by(ActivityLog.action).all()
        action_data = {a: c for a, c in action_stats}
        
        # Atividade por Gatilho (Auto vs User)
        trigger_stats = db.query(ActivityLog.trigger_type, func.count(ActivityLog.id)).group_by(ActivityLog.trigger_type).all()
        trigger_data = {t: c for t, c in trigger_stats}

        # Crescimento de usuários 7 dias
        last_week = datetime.utcnow() - timedelta(days=7)
        daily_users = db.query(func.date(User.created_at), func.count(User.chat_id)).filter(User.created_at >= last_week).group_by(func.date(User.created_at)).all()
        
        # Lista de usuários (Preview)
        users = db.query(User).order_by(User.created_at.desc()).limit(100).all()

        templates = Jinja2Templates(directory="app/templates")
        
        return templates.TemplateResponse("dashboard.html", {
            "request": request,
            "api_key": api_key,
            "total_users": total_users,
            "wa_users": wa_users,
            "tg_users": tg_users,
            "pro_users": pro_users,
            "total_actions": total_actions,
            "action_data": action_data,
            "trigger_data": trigger_data,
            "recent_feedbacks": recent_feedbacks,
            "recent_logs": logs_query, # Lista de tuples (Log, Username)
            "users": users,
            "daily_growth": {str(d): c for d, c in daily_users}
        })
    finally:
        db.close()

@router.get("/user/{chat_id}", response_class=HTMLResponse)
async def user_details(request: Request, chat_id: str, api_key: str = Query(None)):
    """
    Exibe o histórico detalhado de um usuário específico.
    """
    if api_key != os.getenv("CAR_API_KEY", "your-default-secure-key"):
        return HTMLResponse("<h1>Acesso Negado 🚫</h1>", status_code=403)

    from app.models import SessionLocal, User, ActivityLog, FavoriteLocation
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.chat_id == chat_id).first()
        if not user:
            return HTMLResponse(f"<h1>Usuário {chat_id} não encontrado.</h1>")
        
        logs = db.query(ActivityLog).filter(ActivityLog.user_id == chat_id).order_by(ActivityLog.created_at.desc()).all()
        locations = db.query(FavoriteLocation).filter(FavoriteLocation.user_id == chat_id).all()
        
        templates = Jinja2Templates(directory="app/templates")
        return templates.TemplateResponse("user_detail.html", {
            "request": request,
            "api_key": api_key,
            "user": user,
            "logs": logs,
            "locations": locations
        })
    finally:
        db.close()


@router.post("/user/{chat_id}/plan")
async def update_user_plan(
    chat_id: str,
    plan: str = Query(..., description="Novo plano: FREE, STARTER, PRO"),
    api_key: str = Depends(get_api_key),
):
    """
    Atualiza manualmente o plano de um usuário.
    Útil quando o webhook do Stripe falha mas o pagamento foi processado.
    Exemplo: POST /admin/user/556784013193/plan?plan=PRO
    """
    valid_plans = ("FREE", "STARTER", "PRO", "ENTERPRISE")
    plan = plan.upper()
    if plan not in valid_plans:
        return {"error": f"Plano inválido. Use: {valid_plans}"}

    from app.models import SessionLocal, User
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.chat_id == str(chat_id)).first()
        if not user:
            return {"error": f"Usuário {chat_id} não encontrado"}

        old_plan = user.plan_type
        user.plan_type = plan
        db.commit()
        return {
            "status": "success",
            "chat_id": chat_id,
            "old_plan": old_plan,
            "new_plan": plan,
            "message": f"Plano atualizado de {old_plan} para {plan}",
        }
    except Exception as e:
        db.rollback()
        return {"error": str(e)}
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# Trial / Promo Grátis
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/user/{chat_id}/trial")
async def give_user_trial(
    chat_id: str,
    months: int = Query(1, ge=1, le=24, description="Quantidade de meses grátis (1-24)"),
    plan: str = Query("PRO", description="Plano do trial: STARTER, PRO"),
    api_key: str = Depends(get_api_key),
):
    """Dá X meses de trial/promo grátis para um usuário."""
    from app.models import SessionLocal, User
    from datetime import datetime, timedelta

    valid_plans = ("STARTER", "PRO", "ENTERPRISE")
    plan = plan.upper()
    if plan not in valid_plans:
        return {"error": f"Plano inválido para trial. Use: {valid_plans}"}

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.chat_id == str(chat_id)).first()
        if not user:
            return {"error": f"Usuário {chat_id} não encontrado"}

        old_plan = user.plan_type
        expires_at = datetime.utcnow() + timedelta(days=30 * months)
        user.plan_type = plan
        user.trial_expires_at = expires_at
        db.commit()
        return {
            "status": "success",
            "chat_id": chat_id,
            "old_plan": old_plan,
            "trial_plan": plan,
            "trial_months": months,
            "trial_expires_at": expires_at.strftime("%d/%m/%Y"),
            "message": f"{months} mês(es) de {plan} grátis até {expires_at.strftime('%d/%m/%Y')}",
        }
    except Exception as e:
        db.rollback()
        return {"error": str(e)}
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# Gestão de Propriedades
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/user/{chat_id}/property")
async def add_user_property(
    chat_id: str,
    name: str = Query(..., description="Nome da fazenda"),
    lat: float = Query(..., description="Latitude"),
    lon: float = Query(..., description="Longitude"),
    ndvi_alerts: bool = Query(True, description="Ativar alertas NDVI?"),
    api_key: str = Depends(get_api_key),
):
    """Cadastra uma propriedade para um usuário diretamente pelo painel admin."""
    from app.models import SessionLocal, User, FavoriteLocation
    from datetime import datetime

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.chat_id == str(chat_id)).first()
        if not user:
            return {"error": f"Usuário {chat_id} não encontrado"}

        prop = FavoriteLocation(
            user_id=str(chat_id),
            name=name,
            latitude=lat,
            longitude=lon,
            ndvi_alerts_enabled=ndvi_alerts,
            created_at=datetime.utcnow(),
        )
        db.add(prop)
        db.commit()
        db.refresh(prop)
        return {
            "status": "success",
            "property_id": prop.id,
            "name": prop.name,
            "lat": prop.latitude,
            "lon": prop.longitude,
            "ndvi_alerts": prop.ndvi_alerts_enabled,
            "message": f"Propriedade '{name}' cadastrada com sucesso!",
        }
    except Exception as e:
        db.rollback()
        return {"error": str(e)}
    finally:
        db.close()


@router.delete("/user/{chat_id}/property/{prop_id}")
async def delete_user_property(
    chat_id: str,
    prop_id: int,
    api_key: str = Depends(get_api_key),
):
    """Remove uma propriedade de um usuário."""
    from app.models import SessionLocal, FavoriteLocation

    db = SessionLocal()
    try:
        prop = db.query(FavoriteLocation).filter(
            FavoriteLocation.id == prop_id,
            FavoriteLocation.user_id == str(chat_id),
        ).first()
        if not prop:
            return {"error": f"Propriedade {prop_id} não encontrada para o usuário {chat_id}"}

        prop_name = prop.name
        db.delete(prop)
        db.commit()
        return {"status": "success", "message": f"Propriedade '{prop_name}' removida."}
    except Exception as e:
        db.rollback()
        return {"error": str(e)}
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# Mensagem Direta ao Usuário
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/user/{chat_id}/message")
async def send_message_to_user(
    chat_id: str,
    message: str = Query(..., description="Texto da mensagem a enviar"),
    api_key: str = Depends(get_api_key),
):
    """
    Envia uma mensagem direta para o usuário via WhatsApp ou Telegram,
    dependendo da plataforma cadastrada.
    """
    from app.models import SessionLocal, User

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.chat_id == str(chat_id)).first()
        if not user:
            return {"error": f"Usuário {chat_id} não encontrado"}
        platform = (user.platform or "telegram")
    finally:
        db.close()

    try:
        if platform == "whatsapp":
            from app.whatsapp.sender import send_whatsapp_text
            success = send_whatsapp_text(str(chat_id), message)
            if success:
                return {"status": "success", "platform": "whatsapp", "message": "Mensagem enviada!"}
            else:
                return {"error": "Falha no envio WhatsApp (verifique logs do Railway)"}
        else:
            import requests as _req
            from app.config import Config
            url = f"https://api.telegram.org/bot{Config.TELEGRAM_TOKEN}/sendMessage"
            resp = _req.post(url, json={
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "Markdown",
            }, timeout=10)
            if resp.status_code == 200:
                return {"status": "success", "platform": "telegram", "message": "Mensagem enviada!"}
            else:
                return {"error": f"Telegram error {resp.status_code}: {resp.text[:200]}"}
    except Exception as e:
        return {"error": str(e)}
