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

from PIL import Image

def solve_image_captcha(image_bytes):
    """
    Usa o CapSolver para resolver captchas de texto (ImageToTextTask)
    Com pré-processamento para remover a linha vermelha que atrapalha a IA.
    """
    if not CAPSOLVER_API_KEY:
        print("❌ [CapSolver] Chave API não configurada.")
        return None

    try:
        # 1. PRÉ-PROCESSAMENTO (Limpeza da Linha Vermelha do SICAR)
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        pixels = img.load()
        width, height = img.size
        for x in range(width):
            for y in range(height):
                r, g, b = pixels[x, y]
                # Se for "muito vermelho" (linha do SICAR), transforma em branco
                if r > 150 and g < 100 and b < 100:
                    pixels[x, y] = (255, 255, 255)
        
        # Salva imagem limpa para buffer
        clean_buf = io.BytesIO()
        img.save(clean_buf, format='PNG')
        clean_bytes = clean_buf.getvalue()
        
        # 2. RESOLUÇÃO VIA IA
        img_b64 = base64.b64encode(clean_bytes).decode('utf-8')
        
        payload = {
            "clientKey": CAPSOLVER_API_KEY,
            "task": {
                "type": "ImageToTextTask",
                "body": img_b64,
                "caseSensitive": True
            }
        }
        
        resp = requests.post("https://api.capsolver.com/createTask", json=payload, timeout=15)
        task_data = resp.json()
        
        if task_data.get("errorId") == 0:
            return task_data.get("solution", {}).get("text")
        else:
            print(f"❌ [CapSolver] Erro: {task_data.get('errorDescription')}")
    except Exception as e:
        print(f"❌ [CapSolver] Falha na comunicação: {e}")
    
    return None

def download_car_shapefile(car_code: str):
    """
    Fluxo Completo de Download Automatizado:
    1. Pesquisa o CAR para obter o ID interno (Base64)
    2. Baixa a imagem do Captcha
    3. Resolve via CapSolver
    4. Baixa o arquivo ZIP
    """
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36",
        "Referer": f"{BASE_URL}/imoveis/index",
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7"
    })

    print(f"🕵️‍♂️ [SICAR] Iniciando busca para: {car_code}")
    
    try:
        # 0. Hit na Index para estabelecer Cookies (Obrigatório)
        session.get(f"{BASE_URL}/imoveis/index", verify=False)
        time.sleep(1)

        # 1. Pesquisa o Imóvel
        resp = session.get(SEARCH_URL, params={"text": car_code}, verify=False)
        if resp.status_code != 200:
            print(f"❌ [SICAR] Código de erro: {resp.status_code}")
            return None, f"Erro na busca (Status {resp.status_code})"
        
        try:
            data = resp.json()
        except:
            print(f"❌ [SICAR] Resposta não é JSON: {resp.text[:500]}")
            return None, "Erro ao processar dados do governo (Resposta inválida)."
        
        features = data.get("features", [])
        if not features:
            return None, "Imóvel não encontrado na base pública do governo."
        
        # Pega o ID do primeiro resultado (id codificado do Play Framework)
        imovel_id = features[0].get("id")
        print(f"✅ [SICAR] ID Interno localizado: {imovel_id}")

        for attempt in range(1, 7):
            print(f"⏳ [SICAR] Tentativa {attempt} de download (Captcha)...")
            
            # 2. Baixa o Captcha
            captcha_resp = session.get(f"{CAPTCHA_URL}?id={int(time.time()*1000)}", verify=False)
            if captcha_resp.status_code != 200:
                print(f"⚠️ [SICAR] Erro ao baixar captcha: {captcha_resp.status_code}")
                continue
            
            # 3. Resolve o Captcha
            captcha_text = solve_image_captcha(captcha_resp.content)
            if not captcha_text:
                print("⚠️ [SICAR] CapSolver não retornou texto.")
                continue
            
            print(f"✅ [SICAR] Captcha resolvido: [{captcha_text}]. Requisitando ZIP...")

            # 4. Faz o Download do Shapefile
            params = {
                "idImovel": imovel_id,
                "ReCaptcha": captcha_text
            }
            
            dl_resp = session.get(DOWNLOAD_URL, params=params, verify=False)
            
            # Verifica se é um ZIP real e tem um tamanho decente (> 1KB)
            content_type = dl_resp.headers.get('Content-Type', '').lower()
            if dl_resp.status_code == 200 and 'zip' in content_type and len(dl_resp.content) > 1000:
                print(f"🎉 [SICAR] Download concluído com sucesso na tentativa {attempt}!")
                return dl_resp.content, None
            else:
                # Se não é ZIP, o governo provavelmente mandou a página de erro (Captcha Incorreto)
                print(f"⚠️ [SICAR] Falha na tentativa {attempt}. Status: {dl_resp.status_code}, Tipo: {content_type}, Bytes: {len(dl_resp.content)}")
                time.sleep(1.5)

        # Retorna a imagem do ÚLTIMO captcha e a sessão para modo assistido
        return None, {
            "error": "Captcha persistente ou erro no servidor do Governo.",
            "last_captcha": captcha_resp.content if 'captcha_resp' in locals() else None,
            "session": session,
            "imovel_id": imovel_id
        }

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

