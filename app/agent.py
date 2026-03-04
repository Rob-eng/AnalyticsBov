import os
import json
import asyncio
from openai import AsyncOpenAI
import datetime
from app.whatsapp.sender import send_whatsapp_text

# Memory storage: para armazenar o histуrico das conversas temporariamente.
# Em produзгo, isso deve ir pro banco de dados (Supabase) pra não perder nos reboots.
_conversation_memory = {}

def get_tools_definition():
    """
    Define as 'ferramentas' (tools) que o ChatGPT pode invocar caso precise de informacoes dinвmicas.
    """
    return [
        {
            "type": "function",
            "function": {
                "name": "consultar_mercado_futuro",
                "description": "Busca a cotação futura APENAS do Boi Gordo (BGI) em tempo real da bolsa B3.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        },
        {
             "type": "function",
             "function": {
                 "name": "obter_cotacao_fisica_atual",
                 "description": "Busca a cotação média do arroba do Boi Gordo físico hoje (Cepea/Scot) no banco de dados.",
                 "parameters": {
                     "type": "object",
                     "properties": {},
                     "required": []
                 }
             }
        },
        {
             "type": "function",
             "function": {
                 "name": "verificar_previsao_chuva",
                 "description": "Busca a previsão oficial de chuva (precipitação) para os próximos dias em uma coordenada específica.",
                 "parameters": {
                     "type": "object",
                     "properties": {
                         "lat": {"type": "number", "description": "Latitude. Ex: -20.5"},
                         "lon": {"type": "number", "description": "Longitude. Ex: -54.6"}
                     },
                     "required": ["lat", "lon"]
                 }
             }
        },
        {
             "type": "function",
             "function": {
                 "name": "analisar_saude_pasto_ndvi",
                 "description": "Acessa satélites do Google Earth Engine para avaliar o verde do pasto (NDVI / Fotossíntese) na fazenda cruzando o perímetro do CAR. Exige coordenada.",
                 "parameters": {
                     "type": "object",
                     "properties": {
                         "lat": {"type": "number", "description": "Latitude. Ex: -20.5"},
                         "lon": {"type": "number", "description": "Longitude. Ex: -54.6"}
                     },
                     "required": ["lat", "lon"]
                 }
             }
        }
    ]

def _ajustar_historico(phone):
    """Garante que a conversa nap exploda e estoure o limite de tokens da API"""
    msgs = _conversation_memory[phone]
    if len(msgs) > 15:
        # Mantem o system prompt e pega as ultimas 10 interacoes
        _conversation_memory[phone] = [msgs[0]] + msgs[-10:]

async def run_tool(name: str, arguments: dict) -> str:
    """Roda a funcao especifica que o modelo solicitou."""
    print(f"[Agent] IA decidiu rodar a tool: {name} | Args: {arguments}")
    try:
        if name == "consultar_mercado_futuro":
            from app.scraper import scrape_mercado_futuro
            loop = asyncio.get_event_loop()
            data = await loop.run_in_executor(None, scrape_mercado_futuro)
            if not data:
                return "Ocorreu um erro ao baixar os dados do site da B3."
            return json.dumps(data, ensure_ascii=False)
            
        elif name == "obter_cotacao_fisica_atual":
            from app.models import get_recent_prices
            loop = asyncio.get_event_loop()
            prices = await loop.run_in_executor(None, get_recent_prices, 1)
            if prices:
                return f"Última cotação física no banco: Boi Gordo R${prices[0].price} em {prices[0].date}. (Fonte: Scot/Cepea)"
            return "Ainda não há cotação registrada hoje para o mercado físico."

        elif name == "verificar_previsao_chuva":
            lat = arguments.get("lat")
            lon = arguments.get("lon")
            if not lat or not lon: return "Coordenadas inválidas. Peça ao produtor latitude e longitude reais."
            
            from app.weather import get_precipitation_data
            loop = asyncio.get_event_loop()
            chuva_data = await loop.run_in_executor(None, get_precipitation_data, float(lat), float(lon))
            if chuva_data:
                return json.dumps(chuva_data, ensure_ascii=False)
            return "Não foi possível obter dados climáticos. Talvez os satélites de clima estejam offline."
            
        elif name == "analisar_saude_pasto_ndvi":
            lat = arguments.get("lat")
            lon = arguments.get("lon")
            if not lat or not lon: return "Coordenadas inválidas."
            
            from app.environmental import fetch_car_perimeter, get_ndvi_analysis
            loop = asyncio.get_event_loop()
            
            # Buscar limitrofes do CAR
            geom_result = await loop.run_in_executor(None, fetch_car_perimeter, float(lat), float(lon))
            if not geom_result:
                return "Aviso: Nenhuma geometria de fazenda detectada pelo CAR nessa coordenada para cortar o satélite."
            
            geometria, _ = geom_result
            
            # Analisar os satélites com essa geometria
            ndvi_result = await loop.run_in_executor(None, get_ndvi_analysis, geometria)
            if ndvi_result and isinstance(ndvi_result, dict):
                # We return only the text summary so the LLM can talk back.
                # Images urls are ignored by the text LLM for now.
                mean = ndvi_result.get('stats', {}).get('mean', 0)
                data_img = ndvi_result.get('date', 'Desconhecida')
                return f"Análise de Satélite (NDVI) realizada na data: {data_img}. O valor médio de Fotossíntese/Vigor do Pasto foi de {mean:.2f} (escala de -1 a 1). Baseado nisso, diga a ele o diagnóstico aproximado do pasto."
            
            return "Ocorreu um erro ao consultar as imagens limpas do Sentinel-2 no núcleo do Earth Engine. Pode haver excesso de nuvens nos últimos meses."

        return "Ferramenta desconhecida. Informe ao usuário."
    except Exception as e:
        return f"Erro interno ao rodar ferramenta: {e}"

async def get_agent_response(user_id: str, user_text: str, context_info: str = "") -> str:
    """
    Motor central da IA. Processa o texto, chama ferramentas se precisar e retorna a resposta final em texto.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("[Agent WARNING] OPENAI_API_KEY não localizada.")
        return "Opa! Pelo visto o chefe ainda não configurou o meu Cérebro IA lá no servidor. Volto já!"

    client = AsyncOpenAI(api_key=api_key)
    
    if user_id not in _conversation_memory:
        s_prompt = (
            "Você é o AnalyticsBov, um consultor agropecuário tecnológico focado na pecuária de corte.\n"
            "SUAS REGRAS DE OURO:\n"
            "1. NÃO ofereça cotação de Milho/Soja. O AnalyticsBov atende exclusivamente pecuaristas (BOI GORDO).\n"
            "2. Responda amigavelmente (Use 'amigo', 'parceiro'). Resuma listas longas de B3.\n"
            "3. Se perguntarem da Cotação do boi firme ou futura, USE as ferramentas `obter_cotacao_fisica_atual` ou `consultar_mercado_futuro`.\n"
            "4. Se o produtor pedir Previsão de Chuva OU Condição do Pasto (NDVI) fornecendo uma coordenada (Latitude e Longitude), "
            "você TEM PERMISSÃO para rodar essas ferramentas para entregar os dados a ele (verificar_previsao_chuva ou analisar_saude_pasto_ndvi).\n"
            "5. NUNCA invente números."
        )
        if context_info:
            s_prompt += f" Contexto adicional: {context_info}"
            
        _conversation_memory[user_id] = [{"role": "system", "content": s_prompt}]
        
    _conversation_memory[user_id].append({"role": "user", "content": user_text})
    _ajustar_historico(user_id)
    
    try:
        print(f"[Agent] Consultando a nuvem OpenAI para {user_id}...")
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=_conversation_memory[user_id],
            tools=get_tools_definition(),
            tool_choice="auto"
        )
        
        response_msg = response.choices[0].message
        
        if response_msg.tool_calls:
            _conversation_memory[user_id].append(response_msg)
            
            for tool_call in response_msg.tool_calls:
                func_name = tool_call.function.name
                args_dict = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}
                
                tool_result_str = await run_tool(func_name, args_dict)
                
                _conversation_memory[user_id].append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": tool_result_str
                })
                
            print("[Agent] Re-enviando resultados da ferramenta para IA sumarizar.")
            second_response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=_conversation_memory[user_id]
            )
            
            final_text = second_response.choices[0].message.content
            _conversation_memory[user_id].append({"role": "assistant", "content": final_text})
            return final_text
            
        else:
            final_text = response_msg.content
            _conversation_memory[user_id].append({"role": "assistant", "content": final_text})
            return final_text
            
    except Exception as e:
        print(f"[Agent Error] {e}")
        return "Eita! Meu cérebro de inteligência artificial aqui deu um soluço. Me dá um tempinho e tenta mandar a mensagem de novo?"

async def process_whatsapp_message(sender_phone: str, user_text: str):
    """
    Funcao principal chamada pelo webhook do Meta/WhatsApp.
    """
    try:
        resposta = await get_agent_response(sender_phone, user_text, context_info="O usuário está conversando via WhatsApp.")
        send_whatsapp_text(sender_phone, resposta)
    except Exception as e:
        print(f"[WhatsApp Worker Error] {e}")
