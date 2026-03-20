import os
import time
import requests
import json
import io
import base64
from urllib.parse import urlparse, quote
import urllib3

urllib3.disable_warnings()

# Esta chave deve ser configurada na Railway como variável de ambiente
CAPSOLVER_API_KEY = os.environ.get("CAPSOLVER_API_KEY", "")

# URLs Oficiais do Portal de Consulta Pública (consultapublica é mais estável para JSON)
BASE_URL = "https://consultapublica.car.gov.br/publico"
SEARCH_URL = f"{BASE_URL}/imoveis/search"
CAPTCHA_URL = f"{BASE_URL}/municipios/ReCaptcha"
DOWNLOAD_URL = f"{BASE_URL}/imoveis/exportShapeFile"

from PIL import Image, ImageEnhance

def solve_image_captcha(image_bytes):
    """
    Usa o CapSolver para resolver captchas de texto (ImageToTextTask)
    Com filtragem avançada de cores (Binarização P&B) para remover ruído do SICAR.
    """
    if not CAPSOLVER_API_KEY:
        print("❌ [CapSolver] Chave API não configurada.")
        return None

    try:
        # 🧪 FILTRAGEM DE CORES (MODO BLACK-PIXEL)
        img = Image.open(io.BytesIO(image_bytes)).convert("L") # Escala de cinza
        # Aumentar contraste
        img = ImageEnhance.Contrast(img).enhance(2.0)
        # Binarização (Limiar): Tudo que não for quase preto vira Branco
        img = img.point(lambda p: 0 if p < 110 else 255)
        
        clean_buf = io.BytesIO()
        img.save(clean_buf, format='PNG')
        clean_bytes = clean_buf.getvalue()
        
        # 🔗 RESOLUÇÃO VIA IA (CapSolver)
        img_b64 = base64.b64encode(clean_bytes).decode('utf-8')
        
        payload = {
            "clientKey": CAPSOLVER_API_KEY,
            "task": {
                "type": "ImageToTextTask",
                "body": img_b64,
                "caseSensitive": True
            }
        }
        
        resp = requests.post("https://api.capsolver.com/createTask", json=payload, timeout=20)
        task_data = resp.json()
        
        if task_data.get("errorId") == 0:
            return task_data.get("solution", {}).get("text")
    except Exception as e:
        print(f"❌ [CapSolver] Erro vision: {e}")
    
    return None

def download_car_shapefile(car_code: str):
    """
    Motor 100% Silencioso e Automático.
    Tenta até 15 vezes nos bastidores antes de avisar falha.
    """
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36",
        "Referer": f"{BASE_URL}/imoveis/index",
        "Accept": "application/json, text/javascript, */*; q=0.01"
    })

    print(f"🕵️‍♂️ [SICAR] Busca Silenciosa: {car_code}")
    
    try:
        # Warmup
        session.get(f"{BASE_URL}/imoveis/index", verify=False)

        # Buscar ID
        resp = session.get(SEARCH_URL, params={"text": car_code}, verify=False)
        if resp.status_code != 200:
            return None, "Servidor do governo instável (Erro 500/404)."
        
        data = resp.json()
        features = data.get("features", [])
        if not features:
            return None, "Imóvel não encontrado na base pública."
        
        imovel_id = features[0].get("id")

        # Loop Silencioso (15 Tentativas)
        for attempt in range(1, 16):
            # Captcha
            captcha_resp = session.get(f"{CAPTCHA_URL}?id={int(time.time()*1000)}", verify=False)
            if captcha_resp.status_code != 200: continue
            
            captcha_text = solve_image_captcha(captcha_resp.content)
            if not captcha_text: continue
            
            # Download
            params = {"idImovel": imovel_id, "ReCaptcha": captcha_text}
            dl_resp = session.get(DOWNLOAD_URL, params=params, verify=False)
            
            content_type = dl_resp.headers.get('Content-Type', '').lower()
            if dl_resp.status_code == 200 and 'zip' in content_type and len(dl_resp.content) > 1000:
                print(f"🎉 SUCCESSO na tentativa {attempt}!")
                return dl_resp.content, None
            
            # Pequeno delay entre tentativas
            time.sleep(1)

        return None, "O servidor do governo recusou todas as tentativas automatizadas hoje."

    except Exception as e:
        return None, f"Erro de integração: {str(e)}"

    except Exception as e:
        print(f"❌ [SICAR] Erro crítico: {e}")
        return None, {"error": f"Falha na integração: {str(e)}"}


def final_download_with_session(session, imovel_id, captcha_text):
    """
    Tenta o download final usando uma sessão já estabelecida e o texto do usuário.
    """
    params = {
        "idImovel": imovel_id,
        "ReCaptcha": captcha_text
    }
    
    try:
        dl_resp = session.get(DOWNLOAD_URL, params=params, verify=False, timeout=30)
        content_type = dl_resp.headers.get('Content-Type', '').lower()
        
        if dl_resp.status_code == 200 and 'zip' in content_type and len(dl_resp.content) > 1000:
            return dl_resp.content, None
        else:
            return None, "Captcha incorreto ou sessão expirada no governo."
    except Exception as e:
        return None, str(e)

