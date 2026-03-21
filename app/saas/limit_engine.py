from app.models import SessionLocal, User, ActivityLog, FavoriteLocation
from app.saas.billing import PLANS
from datetime import datetime, timedelta
from sqlalchemy import func

def can_perform_action(chat_id: str, action_type: str) -> tuple[bool, str]:
    """
    Verifica se o usuário pode realizar uma ação baseada no plano.
    Actions: 'LOOKUP' (NDVI/Clima/Historico/MDT), 'ADD_PROPERTY', 'ALERT'
    Returns: (can_do, message)
    """
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(chat_id=str(chat_id)).first()
        plan_name = user.plan_type if user and user.plan_type else 'FREE'
        plan = PLANS.get(plan_name, PLANS['FREE'])
        
        # 1. Limite de Propriedades (Cadastro)
        if action_type == 'ADD_PROPERTY':
            prop_count = db.query(FavoriteLocation).filter_by(user_id=str(chat_id)).count()
            if prop_count >= plan['max_properties']:
                return False, f"⚠️ Limite de propriedades atingido ({plan['max_properties']}). Patrão, faça upgrade para cadastrar mais fazendas!"
                
        # 2. Limite de Consultas Mensais (NDVI/Tempo)
        if action_type == 'LOOKUP':
            # Contar logs deste mês
            start_of_month = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            lookup_count = db.query(ActivityLog).filter(
                ActivityLog.user_id == str(chat_id),
                ActivityLog.action.in_(['NDVI', 'CLIMA', 'HISTORICO', 'MDT']),
                ActivityLog.created_at >= start_of_month,
                ActivityLog.status == 'SUCCESS'
            ).count()
            
            if lookup_count >= plan['monthly_lookups']:
                return False, f"⚠️ Eita! O senhor atingiu o limite de {plan['monthly_lookups']} consultas mensais do seu plano. Para continuar, assine o Plano Ouro ou Starter!"

        # 3. Limite de Alertas de Satélite
        if action_type == 'ALERT':
            start_of_month = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            alert_count = db.query(ActivityLog).filter(
                ActivityLog.user_id == str(chat_id),
                ActivityLog.trigger_type == 'AUTO_ALERT',
                ActivityLog.created_at >= start_of_month
            ).count()
            
            if alert_count >= plan.get('monthly_alerts', 999):
                return False, "⚠️ Limite de alertas mensais atingido."

        return True, "OK"
    finally:
        db.close()
