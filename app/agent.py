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
                "description": "Busca a cotação futura do Boi Gordo e do Milho em tempo real da bolsa B3.",
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
                 "description": "Busca a cotação média do arroba do Boi Gordo físico hoje (Cepea/Scot).",
                 "parameters": {
                     "type": "object",
                     "properties": {},
                     "required": []
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
    print(f"[Agent] IA decidiu rodar a tool: {name}")
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
            "Você é o AnalyticsBov, um consultor agropecuário extremamente experiente e amigável. "
            "Seu principal cliente final é o produtor rural brasileiro (focado em corte/Boi Gordo e agricultura). "
            "Responda a perguntas dele como se estivessem trocando uma ideia no zap. "
            "Seja profissional mas pode usar 'Bom dia parceiro', 'amigo', etc. Não seja mto robótico, nem muito prolixo. "
            "Sempre que o agricultor perguntar de cotação ou futuro de milho/boi, VOCÊ É OBRIGADO a usar as tools disponíveis para buscar os dados em tempo real, "
            "você não deve prever ou estimar valores da sua própria cabeça. "
            "Evite listas gigantes no WhatsApp, resuma os principais meses da B3 (Boi) se ele quiser."
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
