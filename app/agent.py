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

async def process_whatsapp_message(sender_phone: str, user_text: str):
    """
    Funcao principal chamada pelo webhook.
    Recebe o telefone e a mensagem do fazendeiro, repassa pra OpenAI,
    executa funcoes (se necessario) e responde via Zap.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("[Agent WARNING] OPENAI_API_KEY não localizada.")
        resposta_fallback = "Opa! Pelo visto o chefe ainda não configurou o meu Cérebro IA lá no servidor. Volto já!"
        send_whatsapp_text(sender_phone, resposta_fallback)
        return

    client = AsyncOpenAI(api_key=api_key)
    
    # Prepara o histórico se for o começo da conversa (System Prompt)
    if sender_phone not in _conversation_memory:
        s_prompt = (
            "Você é o AnalyticsBov, um consultor agropecuário extremamente experiente e amigável. "
            "Seu principal cliente final é o produtor rural brasileiro (focado em corte/Boi Gordo e agricultura). "
            "Responda a perguntas dele como se estivessem trocando uma ideia no zap. "
            "Seja profissional mas pode usar 'Bom dia parceiro', 'amigo', etc. Não seja mto robótico, nem muito prolixo. "
            "Sempre que o agricultor perguntar de cotação ou futuro de milho/boi, VOCÊ É OBRIGADO a usar as tools disponíveis para buscar os dados em tempo real, "
            "você não deve prever ou estimar valores da sua própria cabeça. "
            "Evite listas gigantes no WhatsApp, resuma os principais meses da B3 (Boi) se ele quiser."
        )
        _conversation_memory[sender_phone] = [{"role": "system", "content": s_prompt}]
        
    # Adiciona o que o usuário disse à memória
    _conversation_memory[sender_phone].append({"role": "user", "content": user_text})
    _ajustar_historico(sender_phone)
    
    try:
        # A IA pensa e decide qual a resposta ou qual 'botao' ela deve apertar
        print(f"[Agent] Consultando a nuvem OpenAI para {sender_phone}...")
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=_conversation_memory[sender_phone],
            tools=get_tools_definition(),
            tool_choice="auto"
        )
        
        response_msg = response.choices[0].message
        
        # Caso 1: A IA decidiu que precisa acionar uma ferramenta (ex: buscar preço na B3)
        if response_msg.tool_calls:
            # 1. Armazena que a IA pediu pra rodar a tool (necessidade da API)
            _conversation_memory[sender_phone].append(response_msg)
            
            # 2. Roda localmente cada tool que a IA pediu
            for tool_call in response_msg.tool_calls:
                func_name = tool_call.function.name
                args_dict = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}
                
                tool_result_str = await run_tool(func_name, args_dict)
                
                # 3. Anota o resultado matemático da execução e devolve pro histórico
                _conversation_memory[sender_phone].append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": tool_result_str
                })
                
            # 4. Arremessa o histórico final de volta pra OpenAI juntar tudo num texto humano
            print("[Agent] Re-enviando resultados da ferramenta para IA sumarizar.")
            second_response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=_conversation_memory[sender_phone]
            )
            
            final_text = second_response.choices[0].message.content
            print(f"[Agent GPT Final]: {final_text}")
            _conversation_memory[sender_phone].append({"role": "assistant", "content": final_text})
            
            # Dispacha via WhatsApp Cloud API nativa
            send_whatsapp_text(sender_phone, final_text)
            
        else:
            # Caso 2: A IA simplesmente respondeu batendo papo (sem precisar de ferramentas)
            final_text = response_msg.content
            print(f"[Agent GPT Chat]: {final_text}")
            _conversation_memory[sender_phone].append({"role": "assistant", "content": final_text})
            
            # Manda via WHatsApp Nativo
            send_whatsapp_text(sender_phone, final_text)
            
    except Exception as e:
        print(f"[Agent Error] {e}")
        send_whatsapp_text(sender_phone, "Eita! Meu cérebro de inteligência artificial aqui deu um soluço. Me dá um tempinho e tenta mandar a mensagem de novo?")
