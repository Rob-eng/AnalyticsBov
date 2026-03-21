from fastapi import APIRouter, BackgroundTasks, Depends
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
async def check_db_counts(api_key: str = Depends(get_api_key)):
    """Retorna o total de propriedades por estado no banco."""
    from app.models import CarSessionLocal, CARProperty
    from sqlalchemy import func
    
    session = CarSessionLocal()
    try:
        res = session.query(CARProperty.uf, func.count(CARProperty.id)).group_by(CARProperty.uf).all()
        return {"counts": {uf: count for uf, count in res}}
    finally:
        session.close()
