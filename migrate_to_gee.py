import ee
import os
import json
import time
from google.cloud import storage

# --- CONFIGURAÇÃO ---
# Nome do seu projeto GEE
PROJECT_ID = 'analyticsbov'
# Nome do balde (bucket) no Google Cloud Storage para servir de ponte
# (O script tentará criar um se não existir)
BUCKET_NAME = f'{PROJECT_ID}-gee-migration'
# Pasta de destino no GEE
GEE_ASSETS_BASE = f'projects/{PROJECT_ID}/assets/analyticsbov/car/imovel'
# --------------------

def initialize_all(key_file="service_account.json"):
    """Inicializa as APIs do Google Earth Engine e Cloud Storage."""
    if not os.path.exists(key_file):
        print(f"❌ Erro: Arquivo '{key_file}' não encontrado na pasta atual.")
        return False, None
        
    try:
        with open(key_file) as f:
            creds_info = json.load(f)
        
        # 1. Earth Engine
        print("🛰️ Inicializando Google Earth Engine...")
        credentials = ee.ServiceAccountCredentials(creds_info['client_email'], key_file)
        ee.Initialize(credentials, project=PROJECT_ID)
        
        # 2. Cloud Storage
        print("☁️ Inicializando Google Cloud Storage...")
        storage_client = storage.Client.from_service_account_json(key_file)
        
        return True, storage_client
    except Exception as e:
        print(f"❌ Erro na inicialização: {e}")
        return False, None

def get_or_create_bucket(storage_client):
    """Garante que o bucket de migração existe."""
    try:
        bucket = storage_client.get_bucket(BUCKET_NAME)
        print(f"✅ Bucket '{BUCKET_NAME}' já existe.")
        return bucket
    except:
        print(f"🆕 Criando bucket '{BUCKET_NAME}'...")
        try:
            return storage_client.create_bucket(BUCKET_NAME, location='SOUTHAMERICA-EAST1')
        except Exception as e:
            print(f"❌ Falha ao criar bucket: {e}")
            # Tentativa com US se o de SP falhar por região
            try:
                return storage_client.create_bucket(BUCKET_NAME, location='US')
            except:
                return None

def migrate_uf(uf, geojson_path, storage_client, bucket):
    """Realiza o upload do GeoJSON e inicia a ingestão no GEE."""
    uf = uf.lower()
    asset_folder = f"{GEE_ASSETS_BASE}/{uf}_chunks"
    
    # 1. Criar pasta no GEE se não existir
    try:
        ee.data.createAsset({'type': 'FOLDER'}, asset_folder)
        print(f"📂 Pasta GEE criada: {asset_folder}")
    except ee.ee_exception.EEException as e:
         if "already exists" not in str(e):
              print(f"⚠️ Nota (Pasta GEE): {e}")
    
    # 2. Upload para o GCS (Google Cloud Storage)
    gcs_filename = f"migration_{uf}_{int(time.time())}.geojson"
    blob = bucket.blob(gcs_filename)
    
    print(f"🔼 Enviando {geojson_path} para o Cloud Storage...")
    blob.upload_from_filename(geojson_path)
    gcs_uri = f"gs://{BUCKET_NAME}/{gcs_filename}"
    print(f"✅ Upload concluído: {gcs_uri}")
    
    # 3. Ingestão no GEE (Earth Engine Asset)
    asset_id = f"{asset_folder}/car_{uf}_full"
    print(f"🚀 Iniciando tarefa de ingestão no GEE: {asset_id}")
    
    # Parâmetros de ingestão
    params = {
        'name': asset_id,
        'sources': [{'uris': [gcs_uri]}]
    }
    
    # O GEE usa Task ID para acompanhar o ingest
    task_id = ee.data.newTaskId()[0]
    ee.data.startTableIngestion(task_id, params)
    
    print(f"\n✨ TAREFA INICIADA! ID: {task_id}")
    print(f"👉 Acompanhe o progresso em: https://code.earthengine.google.com/tasks")
    print("\n📦 Após o status ficar 'COMPLETED', o Robô já reconhecerá os perímetros automaticamente!")

if __name__ == "__main__":
    print("-" * 50)
    print("🚀 --- MIGRAR CAR PARA GOOGLE EARTH ENGINE --- 🚀")
    print("-" * 50)
    
    success, s_client = initialize_all()
    if not success:
        print("❌ Verifique sua conexão e se o service_account.json está correto.")
        exit(1)
        
    bucket = get_or_create_bucket(s_client)
    if not bucket:
        print("❌ Não foi possível criar/acessar um bucket no Cloud Storage.")
        exit(1)
        
    uf_input = input("\n👉 Qual UF você quer migrar agora? (ex: SP, GO, MG): ").strip().upper()
    path_input = input(f"👉 Digite o nome do arquivo GeoJSON (ex: car_{uf_input.lower()}.geojson): ").strip()
    
    if not os.path.exists(path_input):
        print(f"❌ Arquivo '{path_input}' não encontrado na pasta atual.")
    else:
        migrate_uf(uf_input, path_input, s_client, bucket)
