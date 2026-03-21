import ijson
import os
import time
import requests
from app.models import CarSessionLocal, CARProperty
from geoalchemy2.shape import from_shape
from shapely.geometry import shape, MultiPolygon, Polygon
from sqlalchemy.exc import IntegrityError

def ingest_geojson_stream(filepath, uf_code):
    """
    Ingere um arquivo GeoJSON no banco de dados CARProperty.
    Suporta arquivos gigantes usando streaming (ijson).
    """
    if not os.path.exists(filepath):
        print(f"❌ Arquivo {filepath} não encontrado.")
        return 0

    print(f"🔄 Ingerindo {filepath} (Estado: {uf_code})...")
    
    session = CarSessionLocal()
    batch_size = 200
    objects = []
    count = 0
    errors = 0
    
    # 🔍 Cache de IDs existentes para evitar duplicatas (e acelerar o resume)
    try:
        existing = session.query(CARProperty.cod_imovel).filter(CARProperty.uf == uf_code).all()
        seen_ids = {r[0] for r in existing}
        print(f"✅ {len(seen_ids)} registros já existem no banco para {uf_code}.")
    except Exception as e:
        print(f"⚠️ Erro ao buscar IDs existentes: {e}")
        seen_ids = set()

    try:
        with open(filepath, 'rb') as f:
            for i, feat in enumerate(ijson.items(f, 'features.item')):
                if i % 1000 == 0:
                    time.sleep(0.01)
                    
                props = feat.get('properties', {})
                cod = props.get('cod_imovel')
                
                if not cod or cod in seen_ids:
                    continue
                seen_ids.add(cod)

                geom_data = feat.get('geometry')
                if not geom_data:
                    continue

                try:
                    geom = shape(geom_data)
                    if isinstance(geom, Polygon):
                        geom = MultiPolygon([geom])
                    
                    if not geom.is_valid:
                        geom = geom.buffer(0)
                        if isinstance(geom, Polygon):
                            geom = MultiPolygon([geom])
                        if not geom.is_valid:
                            errors += 1
                            continue

                    obj = CARProperty(
                        cod_imovel=cod,
                        uf=uf_code,
                        municipio=props.get('municipio'),
                        geometry=from_shape(geom, srid=4674)
                    )
                    objects.append(obj)
                    
                    if len(objects) >= batch_size:
                        session.bulk_save_objects(objects)
                        session.commit()
                        count += len(objects)
                        print(f"  📦 Cometados +{len(objects)} (Total {uf_code}: {count})", end='\r')
                        objects = []
                        
                except Exception:
                    errors += 1
                    continue

    except Exception as e:
        print(f"❌ Erro fatal no streaming: {e}")
    finally:
        if objects:
            session.bulk_save_objects(objects)
            session.commit()
            count += len(objects)
        session.close()

    print(f"\n✅ Finalizado {uf_code}. Ingeridos: {count}. Erros: {errors}")
    return count

def download_and_ingest_mt_wfs():
    """
    Mato Grosso é muito grande (~200k regs). 
    Baixamos em pedaços de 10.000 via WFS 2.0.0 (Paginação).
    """
    base_url = "https://geoserver.car.gov.br/geoserver/sicar/ows"
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeName": "sicar:sicar_imoveis_mt",
        "outputFormat": "application/json",
        "count": 10000,
        "startIndex": 0
    }
    
    total_features = 198345 # Conforme verificado no hits
    chunk_size = 10000
    
    print(f"🚀 INICIANDO CARGA EM MASSA: MATO GROSSO (MT)")
    print(f"Estimativa: {total_features} propriedades em {total_features//chunk_size + 1} blocos.")

    for start in range(0, total_features, chunk_size):
        params["startIndex"] = start
        filename = f"car_mt_chunk_{start}.geojson"
        
        if os.path.exists(filename):
            print(f"⏭️ Chunk {start} já baixado. Pulando download.")
        else:
            print(f"📥 Baixando chunk {start} a {start+chunk_size}...")
            try:
                r = requests.get(base_url, params=params, timeout=120)
                if r.status_code == 200:
                    with open(filename, 'wb') as f:
                        f.write(r.content)
                else:
                    print(f"❌ Erro no download do chunk {start}: {r.status_code}")
                    continue
            except Exception as e:
                print(f"❌ Falha de conexão no chunk {start}: {e}")
                continue

        # Ingerir chunk e deletar
        ingest_geojson_stream(filename, "MT")
        os.remove(filename)
        print(f"🧹 Chunk {start} processado e limpo.")

if __name__ == "__main__":
    download_and_ingest_mt_wfs()
