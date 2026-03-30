"""
🛰️ AUTOMAÇÃO COMPLETA: SICAR → Shapefile → Google Earth Engine
================================================================
Este script automatiza o processo de:
1. Baixar dados CAR do geoserver.car.gov.br (WFS)
2. Salvar como Shapefile
3. Fazer upload para o Google Earth Engine

Uso:
  python3 sync_car_gee.py              # Sincroniza todos os estados
  python3 sync_car_gee.py MS MT GO     # Sincroniza apenas estados específicos
  python3 sync_car_gee.py --list       # Lista estados disponíveis
"""

import os
import sys
import json
import time
import glob
import shutil
import subprocess
import requests
import geopandas as gpd
from datetime import datetime
from shapely.geometry import shape

# ============================================================
# CONFIGURAÇÃO
# ============================================================
SICAR_WFS_URL = "https://geoserver.car.gov.br/geoserver/sicar/wfs"
GEE_PROJECT = "projects/ee-ranjos/assets"
WORK_DIR = "/tmp/car_sync"
PAGE_SIZE = 5000  # Features por página do WFS

# Todos os estados do Brasil
ALL_UFS = [
    'ac', 'al', 'am', 'ap', 'ba', 'ce', 'df', 'es', 'go',
    'ma', 'mg', 'ms', 'mt', 'pa', 'pb', 'pe', 'pi', 'pr',
    'rj', 'rn', 'ro', 'rr', 'rs', 'sc', 'se', 'sp', 'to'
]

# ============================================================
# FUNÇÕES
# ============================================================

def ensure_work_dir():
    os.makedirs(WORK_DIR, exist_ok=True)

def get_feature_count(uf):
    """Consulta o número total de features de um estado via WFS."""
    params = {
        'service': 'WFS',
        'version': '2.0.0',
        'request': 'GetFeature',
        'typeName': f'sicar:sicar_imoveis_{uf}',
        'resultType': 'hits'
    }
    try:
        r = requests.get(SICAR_WFS_URL, params=params, timeout=60, verify=False)
        if r.status_code == 200:
            import re
            m = re.search(r'numberMatched="(\d+)"', r.text)
            if m:
                return int(m.group(1))
    except:
        pass
    return 0

def download_uf_wfs(uf):
    """
    Baixa todos os dados de um estado via WFS com paginação.
    Retorna o caminho do GeoJSON consolidado.
    """
    print(f"\n{'='*60}")
    print(f"📥 BAIXANDO: {uf.upper()}")
    print(f"{'='*60}")
    
    total = get_feature_count(uf)
    print(f"   Total de propriedades no SICAR: {total:,}")
    
    if total == 0:
        print(f"   ⚠️ Estado {uf.upper()} sem dados ou indisponível.")
        return None
    
    all_features = []
    start_index = 0
    
    while start_index < total:
        params = {
            'service': 'WFS',
            'version': '2.0.0',
            'request': 'GetFeature',
            'typeName': f'sicar:sicar_imoveis_{uf}',
            'outputFormat': 'application/json',
            'count': PAGE_SIZE,
            'startIndex': start_index
        }
        
        retries = 3
        for attempt in range(retries):
            try:
                print(f"   📦 Baixando {start_index:,} a {min(start_index+PAGE_SIZE, total):,} de {total:,}...", end='\r')
                r = requests.get(SICAR_WFS_URL, params=params, timeout=300, verify=False)
                
                if r.status_code == 200:
                    data = r.json()
                    features = data.get('features', [])
                    
                    if not features:
                        break
                    
                    all_features.extend(features)
                    
                    if len(features) < PAGE_SIZE:
                        break  # Última página
                    
                    start_index += PAGE_SIZE
                    time.sleep(0.5)  # Respeitar o servidor
                    break
                else:
                    print(f"\n   ⚠️ Erro HTTP {r.status_code} (tentativa {attempt+1}/{retries})")
                    time.sleep(2)
            except Exception as e:
                print(f"\n   ⚠️ Erro de conexão (tentativa {attempt+1}/{retries}): {e}")
                time.sleep(5)
        else:
            print(f"\n   ❌ Falha após {retries} tentativas no índice {start_index}.")
            break
        
        if not features:
            break
    
    print(f"\n   ✅ Baixadas {len(all_features):,} propriedades de {uf.upper()}")
    
    if not all_features:
        return None
    
    # Salvar como GeoJSON temporário
    geojson_path = os.path.join(WORK_DIR, f"car_{uf}.geojson")
    with open(geojson_path, 'w') as f:
        json.dump({"type": "FeatureCollection", "features": all_features}, f)
    
    size_mb = os.path.getsize(geojson_path) / (1024*1024)
    print(f"   💾 Salvo: {geojson_path} ({size_mb:.1f} MB)")
    
    return geojson_path

def convert_to_shapefile(geojson_path, uf):
    """Converte GeoJSON para Shapefile usando GeoPandas."""
    print(f"   🔄 Convertendo para Shapefile...")
    
    try:
        gdf = gpd.read_file(geojson_path)
        
        # Truncar nomes de colunas para 10 chars (limite do Shapefile)
        col_map = {}
        for col in gdf.columns:
            if len(col) > 10 and col != 'geometry':
                col_map[col] = col[:10]
        if col_map:
            gdf = gdf.rename(columns=col_map)
        
        shp_dir = os.path.join(WORK_DIR, f"shp_{uf}")
        os.makedirs(shp_dir, exist_ok=True)
        shp_path = os.path.join(shp_dir, f"car_{uf}.shp")
        
        gdf.to_file(shp_path, driver='ESRI Shapefile')
        print(f"   ✅ Shapefile salvo: {shp_path}")
        
        return shp_path
    except Exception as e:
        print(f"   ❌ Erro na conversão: {e}")
        return None

def upload_to_gee(shp_path, uf):
    """Faz upload do Shapefile para o GEE usando a CLI earthengine."""
    asset_id = f"{GEE_PROJECT}/car_{uf}"
    
    print(f"   🚀 Enviando para GEE: {asset_id}")
    
    # Verificar se o asset já existe
    try:
        result = subprocess.run(
            ['earthengine', 'asset', 'info', asset_id],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            print(f"   ⚠️ Asset {asset_id} já existe. Removendo...")
            subprocess.run(
                ['earthengine', 'rm', asset_id],
                capture_output=True, text=True, timeout=30
            )
            time.sleep(2)
    except:
        pass
    
    # Upload via earthengine CLI
    try:
        cmd = [
            'earthengine', 'upload', 'table',
            f'--asset_id={asset_id}',
            shp_path
        ]
        
        print(f"   📤 Executando: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        
        if result.returncode == 0:
            print(f"   ✅ Upload iniciado! {result.stdout.strip()}")
            return asset_id
        else:
            print(f"   ❌ Erro no upload: {result.stderr.strip()}")
            return None
    except Exception as e:
        print(f"   ❌ Erro ao executar earthengine CLI: {e}")
        return None

def check_upload_status(asset_id):
    """Verifica se o upload terminou."""
    try:
        result = subprocess.run(
            ['earthengine', 'task', 'list'],
            capture_output=True, text=True, timeout=30
        )
        return result.stdout
    except:
        return "Não foi possível verificar."

def sync_state(uf):
    """Pipeline completo para um estado: Download → Shapefile → GEE."""
    start_time = time.time()
    
    # 1. Download do WFS
    geojson_path = download_uf_wfs(uf)
    if not geojson_path:
        return False
    
    # 2. Converter para Shapefile
    shp_path = convert_to_shapefile(geojson_path, uf)
    if not shp_path:
        return False
    
    # 3. Upload para o GEE
    asset_id = upload_to_gee(shp_path, uf)
    
    elapsed = time.time() - start_time
    print(f"\n   ⏱️ {uf.upper()} concluído em {elapsed/60:.1f} minutos")
    
    # 4. Limpar arquivos temporários
    try:
        os.remove(geojson_path)
        shp_dir = os.path.join(WORK_DIR, f"shp_{uf}")
        if os.path.exists(shp_dir):
            shutil.rmtree(shp_dir)
    except:
        pass
    
    return asset_id is not None

def update_gee_connector(synced_ufs):
    """Exibe as linhas que devem ser adicionadas ao gee_connector.py."""
    print(f"\n{'='*60}")
    print(f"📋 ATUALIZAÇÃO DO gee_connector.py")
    print(f"{'='*60}")
    print(f"Adicione estes assets na lista CAR_ASSETS:\n")
    for uf in synced_ufs:
        print(f"    'projects/ee-ranjos/assets/car_{uf}',")

# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    import warnings
    warnings.filterwarnings('ignore')
    
    print("🛰️ SYNC CAR → Google Earth Engine")
    print(f"   WFS: {SICAR_WFS_URL}")
    print(f"   GEE: {GEE_PROJECT}/car_{{UF}}")
    print(f"   Work Dir: {WORK_DIR}")
    
    ensure_work_dir()
    
    # Determinar quais UFs processar
    if len(sys.argv) > 1:
        if sys.argv[1] == '--list':
            print(f"\nEstados disponíveis: {', '.join(u.upper() for u in ALL_UFS)}")
            print(f"\nUso: python3 sync_car_gee.py MS MT GO SP")
            sys.exit(0)
        target_ufs = [u.lower() for u in sys.argv[1:]]
    else:
        target_ufs = ALL_UFS
    
    print(f"\n📋 Estados a processar: {', '.join(u.upper() for u in target_ufs)}")
    
    # Contagem prévia
    print(f"\n📊 Contando propriedades por estado...")
    for uf in target_ufs:
        count = get_feature_count(uf)
        print(f"   {uf.upper()}: {count:>10,} propriedades")
    
    print(f"\n🚀 Iniciando sincronização...\n")
    
    synced = []
    failed = []
    
    for uf in target_ufs:
        success = sync_state(uf)
        if success:
            synced.append(uf)
        else:
            failed.append(uf)
    
    # Relatório final
    print(f"\n{'='*60}")
    print(f"📊 RELATÓRIO FINAL")
    print(f"{'='*60}")
    print(f"✅ Sincronizados: {', '.join(u.upper() for u in synced) or 'Nenhum'}")
    print(f"❌ Falharam: {', '.join(u.upper() for u in failed) or 'Nenhum'}")
    
    if synced:
        update_gee_connector(synced)
    
    print(f"\n👉 Acompanhe o progresso dos uploads em:")
    print(f"   https://code.earthengine.google.com/tasks")
