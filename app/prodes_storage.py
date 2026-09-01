"""
Camada fina de armazenamento (Google Cloud Storage) para os PDFs/PNGs
gerados pela ferramenta PRODES. Reaproveita a mesma credencial já usada
para o Earth Engine (google-cloud-storage já é dependência do projeto).

Caminho determinístico: prodes/{idempotency_key}/{before.png|after.png|report.pdf}
— o próprio path já funciona como chave de cache.

Se PRODES_GCS_BUCKET não estiver configurada, a feature funciona sem cache
persistente (get_bucket() levanta RuntimeError, tratado pelo worker como
"sem cache disponível", não como erro fatal do job).
"""
from __future__ import annotations

from app.config import Config

_bucket_cache = None


def _client():
    from google.cloud import storage
    import os
    import json

    creds_json = os.environ.get('GEE_CREDENTIALS_JSON')
    if creds_json:
        from google.oauth2 import service_account
        info = json.loads(creds_json)
        credentials = service_account.Credentials.from_service_account_info(info)
        return storage.Client(credentials=credentials, project=info.get('project_id'))

    if os.path.exists('service_account.json'):
        return storage.Client.from_service_account_json('service_account.json')

    # Ambiente com Application Default Credentials configurado (ex.: GCE/Cloud Run)
    return storage.Client()


def get_bucket():
    global _bucket_cache
    if _bucket_cache is not None:
        return _bucket_cache
    if not Config.PRODES_GCS_BUCKET:
        raise RuntimeError("PRODES_GCS_BUCKET não configurada — storage indisponível.")
    _bucket_cache = _client().bucket(Config.PRODES_GCS_BUCKET)
    return _bucket_cache


def object_exists(path: str) -> bool:
    try:
        bucket = get_bucket()
    except RuntimeError:
        return False
    try:
        return bucket.blob(path).exists()
    except Exception as e:
        print(f"[PRODES STORAGE] Falha ao checar {path}: {e}", flush=True)
        return False


def upload_bytes(path: str, data: bytes, content_type: str) -> str:
    bucket = get_bucket()
    blob = bucket.blob(path)
    blob.upload_from_string(data, content_type=content_type)
    print(f"[PRODES STORAGE] Upload OK: gs://{Config.PRODES_GCS_BUCKET}/{path} ({len(data)//1024}KB)", flush=True)
    return path


def download_bytes(path: str) -> bytes | None:
    try:
        bucket = get_bucket()
    except RuntimeError:
        return None
    blob = bucket.blob(path)
    try:
        if not blob.exists():
            return None
        return blob.download_as_bytes()
    except Exception as e:
        print(f"[PRODES STORAGE] Falha ao baixar {path}: {e}", flush=True)
        return None
