from fastapi import APIRouter, BackgroundTasks, Depends, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from datetime import datetime, timedelta
import os
from app.auth import get_api_key

router = APIRouter(prefix="/admin", tags=["Admin Ingestion"])

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
    from app.models import CarSessionLocal, CARProperty, SessionLocal, User, ActivityLog
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
    except Exception as e:
        res["user_error"] = str(e)
    finally:
        db.close()

    return res

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
