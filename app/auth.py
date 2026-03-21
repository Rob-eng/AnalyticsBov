import os
from fastapi import Security, HTTPException, Security
from fastapi.security.api_key import APIKeyHeader, APIKeyQuery
from starlette.status import HTTP_403_FORBIDDEN

# Security: Basic API Key
API_KEY = os.getenv("CAR_API_KEY", "your-default-secure-key")
API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)
api_key_query = APIKeyQuery(name="api_key", auto_error=False)

async def get_api_key(
    api_key_header: str = Security(api_key_header),
    api_key_query: str = Security(api_key_query),
):
    """
    Verificador central de seguranca para a API.
    Aceita via Header (X-API-Key) ou Query String (?api_key=).
    """
    if api_key_header == API_KEY:
        return api_key_header
    if api_key_query == API_KEY:
        return api_key_query
    
    print(f"🛑 BLOQUEADO: Tentativa de acesso sem chave válida.")
    raise HTTPException(
        status_code=HTTP_403_FORBIDDEN, detail="Could not validate credentials"
    )
