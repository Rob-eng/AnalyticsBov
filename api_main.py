from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.security.api_key import APIKey
import os

from app.whatsapp.webhook import router as whatsapp_router
from app.telegram_webhook import router as telegram_router
from app.admin_router import router as admin_router
from app.saas.billing import router as billing_router
from app.auth import get_api_key
from app.models import init_db

# Inicializa o Banco de Dados (cria tabelas e migrações pendentes)
init_db()

app = FastAPI(title="CAR Spatial API")
app.include_router(whatsapp_router)
app.include_router(telegram_router)
app.include_router(admin_router)
app.include_router(billing_router)

@app.on_event("startup")
async def on_startup():
    """Configura o sistema ao iniciar a API."""
    try:
        from app.telegram_webhook import get_bot_app
        import os
        
        # 1. Obtém a aplicação do Bot (que contém os handlers)
        application = await get_bot_app()
        
        # 2. Configura e Inicia o Scheduler (NDVI / Weekly Reports)
        from app.scheduler import setup_scheduler
        scheduler = setup_scheduler(application)
        scheduler.start()
        print("✅ API Startup: Scheduler iniciado com sucesso!")

        # 3. Configura Webhook se estiver no Railway (URL disponível)
        webhook_base = os.getenv("TELEGRAM_WEBHOOK_URL")
        if webhook_base:
            from app.config import Config
            webhook_url = f"{webhook_base}/webhook/telegram/{Config.TELEGRAM_TOKEN}"
            await application.bot.set_webhook(url=webhook_url, drop_pending_updates=True)
            print(f"✅ API Startup: Telegram Webhook configurado em {webhook_url}")
        else:
            print("⚠️ API Startup: TELEGRAM_WEBHOOK_URL não definida. Bot aguardando ou em Polling.")
            
    except Exception as e:
        print(f"❌ API Startup Error: {e}")

from fastapi.responses import HTMLResponse

@app.get("/", response_class=HTMLResponse)
def read_root():
    """Retorna a Landing Page Institucional exigida pela Meta Business Verification"""
    import os
    html_path = os.path.join(os.path.dirname(__file__), "app", "templates", "landing.html")
    try:
        with open(html_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return f"<h1>AnalyticsBov</h1><p>Plataforma de inteligência Agro rodando online.</p>"

@app.get("/health")
def health_check():
    """
    Endpoint público de health check — sem autenticação.
    Usado pelo Railway, load balancers e monitoramento externo.
    """
    from datetime import datetime, timezone
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "service": "AnalyticsBov API",
    }

@app.get("/property/at")
def get_property_at(lat: float = Query(..., description="Latitude"), 
                    lon: float = Query(..., description="Longitude"),
                    api_key: str = Depends(get_api_key)):
    """
    Encontra a propriedade CAR na coordenada fornecida via GEE (Nuvem)
    com Fallback para PostGIS (Local).
    """
    # 1. 🛰️ Tenta na Nuvem (GEE - Ilimitado e Global)
    from app.gee_connector import find_car_at_coordinate_gee
    prop_gee = find_car_at_coordinate_gee(lat, lon)
    
    if prop_gee:
        return {
            "found": True,
            "source": "GEE_CLOUD",
            "cod_imovel": prop_gee["cod_imovel"],
            "uf": prop_gee["uf"],
            "municipio": prop_gee["municipio"],
            "geometry": prop_gee["geometry"]
        }

    return {"found": False, "message": "Nenhuma propriedade localizada nesta coordenada."}
            
@app.get("/property/details/{cod_imovel}")
def get_property_details(cod_imovel: str, api_key: APIKey = Depends(get_api_key)):
    raise HTTPException(status_code=501, detail="Lookup by cod_imovel via GEE não implementado.")

@app.get("/property/search")
def search_properties(query: str = Query(..., min_length=3),
                      limit: int = 20,
                      api_key: APIKey = Depends(get_api_key)):
    raise HTTPException(status_code=501, detail="Busca textual de propriedades não disponível via GEE.")

@app.api_route("/admin/migrate_ms", methods=["GET", "POST"])
def trigger_migration(background_tasks: bool = True, api_key: APIKey = Depends(get_api_key)):
    """
    Triggers the MS data migration (Cleanup -> Download -> Ingest) in the background.
    """
    import threading
    import migrate_ms

    def run_job():
        try:
            print("🚀 Admin: Starting migration job...", flush=True)
            migrate_ms.run_migration()
        except Exception as e:
            print(f"❌ Admin: Migration job failed: {e}", flush=True)

    if background_tasks:
        thread = threading.Thread(target=run_job)
        thread.start()
        return {"status": "started", "message": "Migration started in background. Check logs."}
    else:
        run_job()
        return {"status": "completed", "message": "Migration finished synchronous."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
