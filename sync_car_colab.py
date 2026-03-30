# ============================================================
# 🛰️ SYNC CAR → Google Earth Engine (via Google Colab)
# ============================================================
# Cole este script no Google Colab: https://colab.research.google.com
# Ele roda na nuvem do Google, não precisa do seu computador.
#
# INSTRUÇÕES:
# 1. Abra https://colab.research.google.com
# 2. File → New Notebook
# 3. Cole este script inteiro em uma célula
# 4. Clique em "Run" (▶️)
# 5. Na primeira vez, ele vai pedir para autenticar com o Google
# ============================================================

# --- CÉLULA 1: Instalar dependências ---
# !pip install earthengine-api geopandas

# --- CÉLULA 2: Código principal ---

import ee
import os
import json
import time
import requests
import warnings
import subprocess
import re
import shutil
from datetime import datetime

warnings.filterwarnings('ignore')

# ============================================================
# CONFIGURAÇÃO - ALTERE AQUI
# ============================================================
# Estados que você quer sincronizar (minúsculo)
ESTADOS = ['mt', 'go', 'sp', 'mg', 'pr', 'to', 'ba', 'pa', 'rs', 'sc']

# Se True, substitui assets que já existem no GEE
SUBSTITUIR_EXISTENTES = True

# Projeto GEE onde salvar
GEE_PROJECT = 'projects/ee-ranjos/assets'

# Configuração do WFS
SICAR_WFS_URL = "https://geoserver.car.gov.br/geoserver/sicar/wfs"
PAGE_SIZE = 5000
# ============================================================

# Adaptador SSL para o servidor antigo do SICAR
from requests.adapters import HTTPAdapter
try:
    from urllib3.util.ssl_ import create_urllib3_context
    class LegacySSLAdapter(HTTPAdapter):
        def init_poolmanager(self, *args, **kwargs):
            ctx = create_urllib3_context(ciphers='DEFAULT:@SECLEVEL=1')
            kwargs['ssl_context'] = ctx
            return super().init_poolmanager(*args, **kwargs)
    HAS_LEGACY_SSL = True
except:
    HAS_LEGACY_SSL = False

# Sessão HTTP persistente
session = requests.Session()
if HAS_LEGACY_SSL:
    session.mount('https://', LegacySSLAdapter())
session.verify = False

def autenticar_gee():
    """Autentica no GEE (pede login na primeira vez no Colab)."""
    try:
        ee.Initialize(project='ee-ranjos')
        print("✅ GEE já autenticado!")
    except:
        print("🔑 Autenticando no GEE... (siga as instruções abaixo)")
        ee.Authenticate()
        ee.Initialize(project='ee-ranjos')
        print("✅ GEE autenticado com sucesso!")

def contar_features(uf):
    """Conta features de um estado no SICAR."""
    params = {
        'service': 'WFS', 'version': '2.0.0',
        'request': 'GetFeature',
        'typeName': f'sicar:sicar_imoveis_{uf}',
        'resultType': 'hits'
    }
    try:
        r = session.get(SICAR_WFS_URL, params=params, timeout=60)
        m = re.search(r'numberMatched="(\d+)"', r.text)
        return int(m.group(1)) if m else 0
    except Exception as e:
        print(f"   ⚠️ Erro ao contar {uf.upper()}: {e}")
        return 0

def testar_conexao():
    """Testa se conseguimos conectar ao SICAR."""
    print("🔌 Testando conexão com o SICAR...")
    try:
        r = session.get(SICAR_WFS_URL, params={
            'service': 'WFS', 'request': 'GetCapabilities'
        }, timeout=30)
        if r.status_code == 200:
            print(f"   ✅ Conexão OK! (Status {r.status_code})")
            return True
        else:
            print(f"   ❌ Status {r.status_code}: {r.text[:200]}")
            return False
    except Exception as e:
        print(f"   ❌ Falha de conexão: {e}")
        return False

def baixar_estado(uf):
    """Baixa todas as propriedades de um estado via WFS."""
    total = contar_features(uf)
    print(f"\n{'='*50}")
    print(f"📥 {uf.upper()} — {total:,} propriedades")
    print(f"{'='*50}")
    
    if total == 0:
        print(f"   ⚠️ Sem dados para {uf.upper()}")
        return None
    
    all_features = []
    start = 0
    
    while start < total:
        params = {
            'service': 'WFS', 'version': '2.0.0',
            'request': 'GetFeature',
            'typeName': f'sicar:sicar_imoveis_{uf}',
            'outputFormat': 'application/json',
            'count': PAGE_SIZE,
            'startIndex': start
        }
        
        for tentativa in range(3):
            try:
                r = session.get(SICAR_WFS_URL, params=params, timeout=300)
                if r.status_code == 200:
                    feats = r.json().get('features', [])
                    if not feats:
                        break
                    all_features.extend(feats)
                    pct = min(100, len(all_features) * 100 // total)
                    print(f"   📦 {len(all_features):,}/{total:,} ({pct}%)", end='\r')
                    if len(feats) < PAGE_SIZE:
                        break
                    start += PAGE_SIZE
                    time.sleep(0.5)
                    break
                else:
                    time.sleep(2)
            except Exception as e:
                print(f"\n   ⚠️ Tentativa {tentativa+1}: {e}")
                time.sleep(5)
        else:
            break
        if not feats:
            break
    
    print(f"\n   ✅ {len(all_features):,} baixadas")
    
    if not all_features:
        return None
    
    # Salvar como GeoJSON
    path = f'/tmp/car_{uf}.geojson'
    with open(path, 'w') as f:
        json.dump({"type": "FeatureCollection", "features": all_features}, f)
    
    mb = os.path.getsize(path) / 1024 / 1024
    print(f"   💾 Salvo: {path} ({mb:.1f} MB)")
    return path

def converter_shapefile(geojson_path, uf):
    """Converte GeoJSON para Shapefile."""
    print(f"   🔄 Convertendo para Shapefile...")
    try:
        import geopandas as gpd
    except ImportError:
        os.system('pip install geopandas -q')
        import geopandas as gpd
    
    try:
        gdf = gpd.read_file(geojson_path)
        
        # Truncar nomes > 10 chars (limite do SHP)
        renames = {c: c[:10] for c in gdf.columns if len(c) > 10 and c != 'geometry'}
        if renames:
            gdf = gdf.rename(columns=renames)
        
        shp_dir = f'/tmp/shp_{uf}'
        os.makedirs(shp_dir, exist_ok=True)
        shp_path = f'{shp_dir}/car_{uf}.shp'
        gdf.to_file(shp_path, driver='ESRI Shapefile')
        print(f"   ✅ Shapefile: {shp_path}")
        return shp_path
    except Exception as e:
        print(f"   ❌ Erro: {e}")
        return None

def upload_para_gee(shp_path, uf):
    """Upload via earthengine CLI."""
    asset_id = f'{GEE_PROJECT}/car_{uf}'
    
    # Verificar se já existe
    if SUBSTITUIR_EXISTENTES:
        try:
            ee.data.getAsset(asset_id)
            print(f"   🗑️ Removendo asset existente...")
            ee.data.deleteAsset(asset_id)
            time.sleep(2)
        except:
            pass
    
    print(f"   🚀 Upload: {asset_id}")
    
    # Upload via CLI (disponível no Colab)
    import subprocess
    cmd = f'earthengine upload table --asset_id={asset_id} {shp_path}'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    
    if result.returncode == 0:
        print(f"   ✅ Upload iniciado! {result.stdout.strip()}")
        return True
    else:
        print(f"   ❌ Erro: {result.stderr.strip()}")
        return False

def sincronizar_estado(uf):
    """Pipeline completo para um estado."""
    t0 = time.time()
    
    geojson = baixar_estado(uf)
    if not geojson:
        return False
    
    shp = converter_shapefile(geojson, uf)
    if not shp:
        return False
    
    ok = upload_para_gee(shp, uf)
    
    # Limpar
    try:
        os.remove(geojson)
        import shutil
        shutil.rmtree(f'/tmp/shp_{uf}', ignore_errors=True)
    except:
        pass
    
    mins = (time.time() - t0) / 60
    print(f"   ⏱️ {uf.upper()} em {mins:.1f} min")
    return ok

# ============================================================
# EXECUÇÃO
# ============================================================
if __name__ == '__main__':
    print("🛰️ SYNC CAR → Google Earth Engine")
    print(f"   Estados: {', '.join(u.upper() for u in ESTADOS)}")
    print(f"   Destino: {GEE_PROJECT}/car_{{uf}}\n")
    
    autenticar_gee()
    
    # Testar conexão com o SICAR primeiro
    if not testar_conexao():
        print("\n❌ Não foi possível conectar ao SICAR.")
        print("   Possíveis causas:")
        print("   1. O servidor geoserver.car.gov.br pode estar fora do ar")
        print("   2. O Colab pode estar bloqueando a conexão SSL")
        print("   Tente rodar localmente: python3 sync_car_gee.py MT GO SP")
        exit(1)
    
    # Contagem prévia
    print("\n📊 Propriedades por estado:")
    for uf in ESTADOS:
        n = contar_features(uf)
        print(f"   {uf.upper()}: {n:>10,}")
    
    # Sincronizar
    ok, fail = [], []
    for uf in ESTADOS:
        if sincronizar_estado(uf):
            ok.append(uf)
        else:
            fail.append(uf)
    
    print(f"\n{'='*50}")
    print(f"📊 RESULTADO")
    print(f"{'='*50}")
    print(f"✅ OK: {', '.join(u.upper() for u in ok) or '—'}")
    print(f"❌ Falha: {', '.join(u.upper() for u in fail) or '—'}")
    print(f"\n👉 Acompanhe: https://code.earthengine.google.com/tasks")
