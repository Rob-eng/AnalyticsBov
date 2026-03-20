from fastapi import FastAPI, HTTPException, Query, Depends, Security
from fastapi.security.api_key import APIKeyHeader, APIKey, APIKeyQuery
from sqlalchemy import text
from app.models import SessionLocal, CARProperty, engine
from geoalchemy2.functions import ST_Intersects, ST_GeomFromText, ST_Distance, ST_Centroid
from geoalchemy2.shape import to_shape
from shapely.geometry import mapping
import json
import os
from starlette.status import HTTP_403_FORBIDDEN

from app.whatsapp.webhook import router as whatsapp_router
from app.models import init_db

# Inicializa o Banco de Dados (cria tabelas e migrações pendentes)
init_db()

app = FastAPI(title="CAR Spatial API", description="API to query CAR properties from PostGIS")
app.include_router(whatsapp_router)

# Security: Basic API Key
API_KEY = os.getenv("CAR_API_KEY", "your-default-secure-key")
API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)
api_key_query = APIKeyQuery(name="api_key", auto_error=False)

async def get_api_key(
    api_key_header: str = Security(api_key_header),
    api_key_query: str = Security(api_key_query),
):
    if api_key_header == API_KEY:
        return api_key_header
    if api_key_query == API_KEY:
        return api_key_query
    
    raise HTTPException(
        status_code=HTTP_403_FORBIDDEN, detail="Could not validate credentials"
    )

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

@app.get("/property/at")
def get_property_at(lat: float = Query(..., description="Latitude"), 
                    lon: float = Query(..., description="Longitude"),
                    api_key: APIKey = Depends(get_api_key)):
    """
    Finds the CAR property containing the given coordinates.
    """
    from app.models import CarSessionLocal
    session = CarSessionLocal()
    
    # DEBUG: Inspect DB Connection
    try:
        from sqlalchemy import inspect
        bind = session.get_bind()
        print(f"DEBUG API: DB URL: {bind.url}", flush=True)
        inspector = inspect(bind)
        print(f"DEBUG API: Tables in DB: {inspector.get_table_names()}", flush=True)
    except Exception as e:
        print(f"DEBUG API: Inspection Failed: {e}", flush=True)

    try:
        point_wkt = f'POINT({lon} {lat})'
        
        prop = session.query(CARProperty).filter(
            CARProperty.geometry.ST_Intersects(ST_GeomFromText(point_wkt, 4674))
        ).first()

        if prop:
            geom_shape = to_shape(prop.geometry)
            return {
                "found": True,
                "status": "OFFICIAL",
                "cod_imovel": prop.cod_imovel,
                "uf": prop.uf,
                "municipio": prop.municipio,
                "geometry": mapping(geom_shape)
            }
        
        # Fallback: Nearest within 11km
        nearest = session.query(CARProperty).order_by(
            CARProperty.geometry.ST_Distance(ST_GeomFromText(point_wkt, 4674))
        ).limit(1).first()

        if nearest:
            dist_query = session.execute(
                text(f"SELECT ST_Distance(geometry, ST_GeomFromText('{point_wkt}', 4674)) FROM car_properties WHERE id = :pid"),
                {"pid": nearest.id}
            ).scalar()
            
            if dist_query < 0.1: 
                geom_shape = to_shape(nearest.geometry)
                return {
                    "found": True,
                    "status": "NEARBY",
                    "cod_imovel": nearest.cod_imovel,
                    "uf": nearest.uf,
                    "municipio": nearest.municipio,
                    "geometry": mapping(geom_shape),
                    "distance_degrees": dist_query
                }

        return {"found": False, "message": "No property found at this location."}
    finally:
        session.close()

@app.get("/property/details/{cod_imovel}")
def get_property_details(cod_imovel: str, api_key: APIKey = Depends(get_api_key)):
    """
    Retrieve full details and perimeter for a specific property code.
    """
    from app.models import CarSessionLocal
    session = CarSessionLocal()
    try:
        prop = session.query(CARProperty).filter(CARProperty.cod_imovel == cod_imovel).first()
        if not prop:
            raise HTTPException(status_code=404, detail="Property not found")
            
        geom_shape = to_shape(prop.geometry)
        return {
            "found": True,
            "cod_imovel": prop.cod_imovel,
            "uf": prop.uf,
            "municipio": prop.municipio,
            "geometry": mapping(geom_shape)
        }
    finally:
        session.close()

@app.get("/property/search")
def search_properties(query: str = Query(..., min_length=3), 
                      limit: int = 20,
                      api_key: APIKey = Depends(get_api_key)):
    """
    Search properties by code or municipality.
    """
    from app.models import CarSessionLocal
    session = CarSessionLocal()
    try:
        props = session.query(CARProperty).filter(
            (CARProperty.cod_imovel.ilike(f"%{query}%")) | 
            (CARProperty.municipio.ilike(f"%{query}%"))
        ).limit(limit).all()
        
        results = []
        for p in props:
            results.append({
                "cod_imovel": p.cod_imovel,
                "uf": p.uf,
                "municipio": p.municipio
            })
        return {"count": len(results), "results": results}
    finally:
        session.close()

import threading
import migrate_ms

@app.api_route("/admin/migrate_ms", methods=["GET", "POST"])
def trigger_migration(background_tasks: bool = True, api_key: APIKey = Depends(get_api_key)):
    """
    Triggers the MS data migration (Cleanup -> Download -> Ingest) in the background.
    """
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
