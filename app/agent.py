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
                 "name": "analisar_camada_ambiental_teste",
                 "description": "Manda uma coordenada (Latitude e Longitude) para a nuvem do Google Earth Engine para cruzar a fazenda do produtor com o Shapefile guardado na nuvem (TESTE_GEO). O produtor DEVE informar uma coordenada para acionar essa função.",
                 "parameters": {
                     "type": "object",
                     "properties": {
                         "lat": {"type": "number", "description": "Latitude da fazenda (ex: -20.5)"},
                         "lon": {"type": "number", "description": "Longitude da fazenda (ex: -54.6)"}
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
            # Para nao travar o loop assincrono com raspagem pesada do BS4:
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
                # Retorna os dados como string pro bot
                return f"Última cotação inserida no banco: Boe {prices[0].price} na data {prices[0].date}. (Fonte: Scot/MS)"
            return "Ainda não há cotação registrada hoje para o mercado físico."

        elif name == "analisar_camada_ambiental_teste":
            lat = arguments.get('lat')
            lon = arguments.get('lon')
            if not lat or not lon:
                return "O produtor não informou latitude e longitude válidas."
            
            from app.environmental import fetch_car_perimeter
            from app.gee_connector import get_asset_intersection_area
            
            # Buscar a geometria da fazenda no Supabase/CAR
            loop = asyncio.get_event_loop()
            geom_result = await loop.run_in_executor(None, fetch_car_perimeter, float(lat), float(lon))
            
            if not geom_result:
                 return "Não foi possível encontrar a geometria desta fazenda."
                 
            geometria, status_busca = geom_result
            
            # ID Exato gravado pelo Robson lá no Google Earth Engine
            asset_id = "projects/ee-ranjos/assets/TESTE_GEO"
            
            # Subir a geometria temporariamente no supercomputador pra cruzar o mapa
            area_ha = await loop.run_in_executor(None, get_asset_intersection_area, asset_id, geometria)
            
            return (
                f"Busca da borda no CAR: {status_busca}. "
                f"O Google cruzou os satélites com a camada TESTE_GEO. A área da fazenda ({lat}, {lon}) que cruza "
                f"com a sua camada privada é de exatamente {area_ha:.2f} Hectares."
            )
            
        return "Ferramenta desconhecida. Informe ao usuário."
    except Exception as e:
        return f"Erro interno ao rodar ferramenta: {e}"

async def get_agent_response(user_id: str, user_text: str, context_info: str = "") -> str:
    """
    Motor central da IA. Processa o texto, chama ferramentas se precisar e retorna a resposta final em texto.
    O `context_info` pode ser usado para dar dicas (como 'O usuário está no Telegram').
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("[Agent WARNING] OPENAI_API_KEY não localizada.")
        return "Opa! Pelo visto o chefe ainda não configurou o meu Cérebro IA lá no servidor. Volto já!"

    client = AsyncOpenAI(api_key=api_key)
    
    if user_id not in _conversation_memory:
        s_prompt = (
            "Você é o AnalyticsBov, um consultor agropecuário focado na pecuária de corte (Boi Gordo). "
            "Responda ao produtor rural de forma objetiva, profissional e amigável. "
            "SUAS REGRAS DE OURO:\n"
            "1. NÃO ofereça cotação de Milho, Soja ou outras culturas, monitoramos exclusivamente o BOI GORDO.\n"
            "2. Nunca invente valores financeiros: Se pedirem a cotação (física ou futura), você DEVE rodar as suas tools acopladas para buscar o dado real.\n"
            "3. Se o produtor perguntar sobre Previsão de Chuva ou Análise de NDVI (Pasto), Diga a ele com educação que essa função "
            "deve ser acionada diretamente pelos botões do Menu Principal ou enviando a localização GPS dele diretamente na conversa.\n"
            "Evite listas gigantes no WhatsApp, resuma os principais meses da B3 se ele quiser."
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
