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
                "name": "consultar_leilao_cda",
                "description": "Mostra o gráfico de evolução de preços do Leilão Correa da Costa (CDA) com os últimos preços médios por raça (R$/@). Use quando o usuário mencionar 'leilão', 'leilão CDA', 'Correa da Costa', 'preço arroba leilão', 'resultado leilão' ou pedir gráfico de preços de leilão.",
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
                 "description": "Gera mapa de PREVISÃO de chuva para os PRÓXIMOS 5 dias (futuro). Use quando o usuário perguntar 'vai chover?', 'previsão de chuva', 'precipitação nos próximos dias'.",
                 "parameters": {
                     "type": "object",
                     "properties": {
                         "lat": {"type": "number", "description": "Latitude"},
                         "lon": {"type": "number", "description": "Longitude"},
                         "nome_propriedade": {"type": "string", "description": "Nome da propriedade"}
                     },
                     "required": ["lat", "lon"]
                 }
             }
        },
        {
             "type": "function",
             "function": {
                 "name": "verificar_historico_chuva",
                 "description": "Gera mapa de HISTÓRICO de chuva dos ÚLTIMOS 7-30 dias (passado). Use quando o usuário perguntar 'choveu?', 'histórico de chuva', 'quanto choveu', 'precipitação dos últimos dias'.",
                 "parameters": {
                     "type": "object",
                     "properties": {
                         "lat": {"type": "number", "description": "Latitude"},
                         "lon": {"type": "number", "description": "Longitude"},
                         "nome_propriedade": {"type": "string", "description": "Nome da propriedade"}
                     },
                     "required": ["lat", "lon"]
                 }
             }
        },
        {
             "type": "function",
             "function": {
                 "name": "analisar_saude_pasto_ndvi",
                 "description": "Gera mapa NDVI (verde do pasto / saúde da vegetação) via satélite. Use para 'NDVI', 'verde do pasto', 'saúde do pasto', 'análise ambiental'. NÃO use para terreno/relevo.",
                 "parameters": {
                     "type": "object",
                     "properties": {
                         "lat": {"type": "number", "description": "Latitude"},
                         "lon": {"type": "number", "description": "Longitude"},
                         "nome_propriedade": {"type": "string", "description": "Nome da propriedade"}
                     },
                     "required": ["lat", "lon"]
                 }
             }
        },
        {
             "type": "function",
             "function": {
                 "name": "analisar_prodes",
                 "description": (
                     "Cruza o perímetro oficial do CAR do imóvel com apontamentos de desmatamento do "
                     "PRODES/INPE, gera um mapa geral e, depois de escolhido o apontamento, mapas de "
                     "satélite antes/depois + um PDF de laudo técnico. Use para 'PRODES', 'desmatamento', "
                     "'autuação ambiental', 'multa ambiental', 'defesa ambiental', 'laudo de desmatamento' "
                     "ou qualquer pedido de análise de desmatamento no imóvel. "
                     "FLUXO EM DUAS ETAPAS: primeiro chame COM lat/lon e SEM 'escolha' — isso lista os "
                     "apontamentos encontrados. Se a mensagem seguinte do usuário for só a escolha (um "
                     "número, vários separados por vírgula, ou 'todos'), chame de novo só com 'escolha' "
                     "preenchida — NÃO envie lat/lon nessa segunda chamada (o servidor já sabe qual foi a "
                     "última consulta deste usuário; inventar coordenadas nessa etapa quebra a análise)."
                 ),
                 "parameters": {
                     "type": "object",
                     "properties": {
                         "lat": {"type": "number", "description": "Latitude — obrigatório na 1ª chamada (sem 'escolha'); omita na 2ª chamada (com 'escolha')."},
                         "lon": {"type": "number", "description": "Longitude — obrigatório na 1ª chamada (sem 'escolha'); omita na 2ª chamada (com 'escolha')."},
                         "nome_propriedade": {"type": "string", "description": "Nome da propriedade"},
                         "escolha": {
                             "type": "string",
                             "description": (
                                 "Resposta do usuário à listagem de apontamentos já mostrada: um número "
                                 "('2'), vários ('1,3') ou 'todos'. Omita na 1ª chamada (a que lista)."
                             )
                         }
                     },
                     "required": []
                 }
             }
        },
        {
             "type": "function",
             "function": {
                 "name": "analisar_terreno_mdt",
                 "description": "Gera mapa MDT (Modelo Digital de Terreno) com curvas de nível 2D e modelo 3D. Use para 'MDT', 'terreno', 'elevação', 'relevo', 'curvas de nível', 'topografia'. NÃO use para vegetação/NDVI.",
                 "parameters": {
                     "type": "object",
                     "properties": {
                         "lat": {"type": "number", "description": "Latitude"},
                         "lon": {"type": "number", "description": "Longitude"},
                         "nome_propriedade": {"type": "string", "description": "Nome da propriedade"}
                     },
                     "required": ["lat", "lon"]
                 }
             }
        },
        {
             "type": "function",
             "function": {
                 "name": "listar_propriedades",
                 "description": "Lista todas as propriedades (fazendas) cadastradas do usuário com seus nomes e coordenadas.",
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
                 "name": "mostrar_menu_principal",
                 "description": "Exibe o menu interativo principal para o usuário. Use quando o usuário pedir 'menu', 'opções', disser 'oi' num contexto de boas vindas, etc.",
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
                    "name": "cadastrar_propriedade",
                    "description": "Cadastra uma nova fazenda/propriedade para o usuário usando nome e coordenadas.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "nome": {"type": "string", "description": "Nome da fazenda"},
                            "lat": {"type": "number", "description": "Latitude decimal"},
                            "lon": {"type": "number", "description": "Longitude decimal"}
                        },
                        "required": ["nome", "lat", "lon"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "disparar_fluxo_automatico",
                    "description": "Dispara um fluxo automático (botão) do sistema. Use isso como BACKUP se o NDVI falhar ou se o usuário pedir 'pela ferramenta padrão' ou 'pelo botão'.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "fluxo": {
                                "type": "string",
                                "enum": ["NDVI", "CLIMA", "MDT"],
                                "description": "O fluxo/botão a ser acionado"
                            },
                            "lat": {"type": "number", "description": "Latitude decimal"},
                            "lon": {"type": "number", "description": "Longitude decimal"},
                            "nome_propriedade": {"type": "string", "description": "Nome da propriedade (opcional)"}
                        },
                        "required": ["fluxo", "lat", "lon"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "enviar_feedback_admin",
                    "description": "Envia uma sugestão, crítica ou feedback do usuário diretamente para o administrador do sistema.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "mensagem": {"type": "string", "description": "O conteúdo do feedback ou sugestão"}
                        },
                        "required": ["mensagem"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "consultar_meu_plano",
                    "description": "Consulta o plano atual do usuário e mostra informações sobre ele. Use quando o usuário perguntar 'qual meu plano', 'meu plano', 'planos', 'assinatura', 'preços', 'assinar', 'upgrade', 'quais as vantagens' ou 'quero mudar de plano'.",
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

async def run_tool(name: str, arguments: dict, media_list: list, user_id: str) -> str:
    """Roda a funcao especifica que o modelo solicitou."""
    print(f"[Agent] IA decidiu rodar a tool: {name} | Args: {arguments}")
    try:
        if name == "consultar_mercado_futuro":
            return "TRIGGER_FLOW: MERCADO_FUTURO"

        elif name == "consultar_leilao_cda":
            return "TRIGGER_FLOW: LEILAO"
            
        elif name == "obter_cotacao_fisica_atual":
            return "TRIGGER_FLOW: COTACAO"

        elif name == "verificar_previsao_chuva":
            lat = arguments.get("lat")
            lon = arguments.get("lon")
            nome = arguments.get("nome_propriedade", "Local Selecionado")
            if not lat or not lon: return "Coordenadas inválidas."
            return f"TRIGGER_FLOW: CLIMA | {lat} | {lon} | {nome}"

        elif name == "verificar_historico_chuva":
            lat = arguments.get("lat")
            lon = arguments.get("lon")
            nome = arguments.get("nome_propriedade", "Local Selecionado")
            if not lat or not lon: return "Coordenadas inválidas."
            return f"TRIGGER_FLOW: HISTORICO | {lat} | {lon} | {nome}"
            
        elif name == "analisar_saude_pasto_ndvi":
            lat = arguments.get("lat")
            lon = arguments.get("lon")
            nome = arguments.get("nome_propriedade", "Local Selecionado")
            if not lat or not lon: return "Coordenadas inválidas."
            return f"TRIGGER_FLOW: NDVI | {lat} | {lon} | {nome}"

        elif name == "analisar_terreno_mdt":
            lat = arguments.get("lat")
            lon = arguments.get("lon")
            nome = arguments.get("nome_propriedade", "Local Selecionado")
            if not lat or not lon: return "Coordenadas inválidas."
            return f"TRIGGER_FLOW: MDT | {lat} | {lon} | {nome}"

        elif name == "analisar_prodes":
            lat = arguments.get("lat")
            lon = arguments.get("lon")
            nome = arguments.get("nome_propriedade", "Local Selecionado")
            escolha = arguments.get("escolha")
            if escolha:
                # 2ª etapa: não depende de lat/lon corretos — o servidor usa o cache da
                # última listagem PRODES deste usuário (ver app/whatsapp/trigger_handler.py).
                # "|" separa os campos no parser do trigger_handler — troca por "e" se vier na escolha.
                escolha_safe = str(escolha).replace("|", " e ")
                lat_field = lat if lat is not None else ""
                lon_field = lon if lon is not None else ""
                return f"TRIGGER_FLOW: PRODES_ESCOLHA | {lat_field} | {lon_field} | {nome} | {escolha_safe}"
            if not lat or not lon: return "Coordenadas inválidas."
            return f"TRIGGER_FLOW: PRODES | {lat} | {lon} | {nome}"

        elif name == "listar_propriedades":
            from app.models import SessionLocal, FavoriteLocation
            session = SessionLocal()
            try:
                props = session.query(FavoriteLocation).filter(FavoriteLocation.user_id == user_id).all()
                if not props:
                    return "O usuário ainda não possui propriedades cadastradas."
                
                res = []
                for p in props:
                    res.append({"nome": p.name, "lat": p.latitude, "lon": p.longitude})
                return json.dumps(res, ensure_ascii=False)
            finally:
                session.close()

        elif name == "cadastrar_propriedade":
            nome = arguments.get("nome")
            lat = arguments.get("lat")
            lon = arguments.get("lon")
            if not nome or lat is None or lon is None:
                return "Dados incompletos para cadastro. Preciso de nome, latitude e longitude."
            
            # 1. Verificar Limite do Plano
            from app.saas.limit_engine import can_perform_action
            can_do, msg_limit = can_perform_action(user_id, 'ADD_PROPERTY')
            if not can_do:
                return msg_limit

            from app.models import SessionLocal, FavoriteLocation, User
            session = SessionLocal()
            try:
                # Garantir que o usuário existe
                user = session.query(User).filter(User.chat_id == user_id).first()
                if not user:
                    # Se o ID for numérico e longo (ex: telefone WhatsApp com DDI/DDD), classifica como WhatsApp
                    is_wa = user_id.isdigit() and len(user_id) >= 11
                    user = User(chat_id=user_id, platform='whatsapp' if is_wa else 'telegram')
                    session.add(user)
                    session.flush()

                new_prop = FavoriteLocation(user_id=user_id, name=nome, latitude=float(lat), longitude=float(lon))
                session.add(new_prop)
                session.commit()
                return f"Propriedade '{nome}' cadastrada com sucesso!"
            except Exception as e:
                session.rollback()
                return f"Erro ao cadastrar propriedade: {e}"
            finally:
                session.close()

        elif name == "mostrar_menu_principal":
            return "TRIGGER_FLOW: MENU"

        elif name == "disparar_fluxo_automatico":
            fluxo = arguments.get("fluxo")
            lat = arguments.get("lat")
            lon = arguments.get("lon")
            nome = arguments.get("nome_propriedade", "Local Selecionado")
            
            # Retornamos uma string especial amigável para o bot.py interceptar
            # ou para o usuário entender que o fluxo foi delegado.
            # No bot.py, vamos interceptar o retorno do agente.
            return f"TRIGGER_FLOW: {fluxo} | {lat} | {lon} | {nome}"

        elif name == "enviar_feedback_admin":
            from app.notifications import notify_feedback
            from app.models import SessionLocal, User, Feedback, log_activity
            db = SessionLocal()
            u = db.query(User).filter_by(chat_id=user_id).first()
            u_name = u.username if u and u.username else "Usuário Desconhecido"
            
            msg_feedback = arguments.get("mensagem", "")
            if msg_feedback:
                # 1. Salva no DB para o Analytics
                new_f = Feedback(user_id=user_id, message=msg_feedback)
                db.add(new_f)
                db.commit()
                db.close()
                
                # 2. Notifica o Admin (Telegram)
                notify_feedback(user_id, msg_feedback, user_name=u_name)
                
                # 3. Log de Atividade
                log_activity(user_id, "FEEDBACK", details=msg_feedback[:100])
                
                return "Sucesso! O feedback foi enviado ao administrador. O bot responderá ao usuário que a sugestão foi recebida."
            db.close()
            return "Erro: mensagem de feedback está vazia."

        elif name == "consultar_meu_plano":
            # Busca o plano atual do usuário no banco
            from app.models import SessionLocal, User
            db = SessionLocal()
            try:
                user = db.query(User).filter_by(chat_id=str(user_id)).first()
                plan_name = (user.plan_type if user and user.plan_type else 'FREE')
                plan_display = {
                    'FREE': '🥉 Bronze (Grátis)',
                    'STARTER': '🥈 Starter',
                    'PRO': '🥇 Ouro (PRO)',
                    'ENTERPRISE': '💎 Diamond (Enterprise)',
                }.get(plan_name, plan_name)
                return (
                    f"PLANO_ATUAL: {plan_display}\n"
                    f"Informe o plano ao Patrão de forma amigável e pergunte "
                    f"se ele deseja ver as opções de upgrade disponíveis. "
                    f"Se ele disser SIM, responda EXATAMENTE: TRIGGER_FLOW: PREMIUM"
                )
            finally:
                db.close()

        return "Ferramenta desconhecida. Informe ao usuário."
    except Exception as e:
        return f"Erro interno ao rodar ferramenta: {e}"

async def get_agent_response(user_id: str, user_text: str, context_info: str = "") -> tuple:
    """
    Motor central da IA. Processa o texto, chama ferramentas se precisar e retorna a resposta final em texto.
    Retorna uma tuple: (texto_str, media_list_buffers)
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("[Agent WARNING] OPENAI_API_KEY não localizada.")
        return ("Opa! Pelo visto o chefe ainda não configurou o meu Cérebro IA lá no servidor. Volto já!", [])

    client = AsyncOpenAI(api_key=api_key)
    media_list = []
    
    if user_id not in _conversation_memory:
        s_prompt = (
            "Você é o AnalyticsBov, um consultor agropecuário tecnológico e operador da plataforma Agro Analytics.\n"
            "SUAS REGRAS DE OURO:\n"
            "1. NÃO ofereça cotação de Milho/Soja. Atenda exclusivamente pecuaristas (BOI GORDO).\n"
            "2. Responda amigavelmente (Use CADASTRADO como 'Patrão', SEMPRE chame o usuário de Patrão). Resuma listas B3.\n"
            "3. Use `obter_cotacao_fisica_atual` ou `consultar_mercado_futuro` para cotações.\n"
            "4. Se o produtor pedir Previsão de Chuva, NDVI ou MDT (Terreno):\n"
            "   - Use as ferramentas correspondentes (`verificar_previsao_chuva` ou `analisar_saude_pasto_ndvi`).\n"
            "5. Se o produtor perguntar sobre Preços, Planos, Assinatura ou 'qual meu plano':\n"
            "   - Use `consultar_meu_plano` IMEDIATAMENTE.\n"
            "   - Informe o plano atual ao Patrão e pergunte se quer ver opções de upgrade.\n"
            "   - Só mostre os planos detalhados se o Patrão pedir explicitamente.\n"
            "   - Se ele pedir para ver, responda EXATAMENTE: TRIGGER_FLOW: PREMIUM\n"
            "6. Se não souber as coordenadas, use `listar_propriedades` para achar os dados da fazenda. "
            "Se houver MAIS DE UMA propriedade cadastrada e o Patrão não tiver dito qual (por nome), NÃO "
            "escolha sozinho — liste os nomes e pergunte qual ele quer antes de rodar qualquer análise "
            "(NDVI, clima, MDT, PRODES). Só use direto se houver exatamente uma propriedade cadastrada.\n"
            "7. Ofereça sempre o canal de feedback (`enviar_feedback_admin`) se o Patrão quiser sugerir algo.\n"
            "8. NUNCA invente números.\n"
            "9. Se o Patrão mencionar 'leilão', 'CDA', 'Correa da Costa', 'preço arroba leilão' ou pedir gráfico de leilão, use `consultar_leilao_cda` IMEDIATAMENTE.\n"
            "10. Se o Patrão mencionar 'PRODES' (mesmo sozinho, sem mais nada), 'desmatamento', 'autuação "
            "ambiental', 'multa ambiental', 'defesa ambiental' ou pedir laudo/análise de desmatamento, use "
            "`analisar_prodes` IMEDIATAMENTE (sem o parâmetro 'escolha' na primeira vez — isso lista os "
            "apontamentos encontrados no imóvel). Se a PRÓXIMA mensagem dele for só um número (ex.: '2'), "
            "vários números (ex.: '1,3') ou 'todos', isso é a escolha de qual apontamento analisar — chame "
            "`analisar_prodes` de novo só com o parâmetro 'escolha' preenchido com essa resposta. NÃO tente "
            "adivinhar ou reaproveitar lat/lon nessa segunda chamada — o servidor já sabe qual foi a última "
            "consulta PRODES deste Patrão; se você não tiver certeza das coordenadas, deixe o campo vazio "
            "em vez de inventar um valor."
        )
        if context_info:
            s_prompt += f" Contexto adicional: {context_info}"
            
        _conversation_memory[user_id] = [{"role": "system", "content": s_prompt}]
        
    _conversation_memory[user_id].append({"role": "user", "content": user_text})
    _ajustar_historico(user_id)
    
    try:
        max_iterations = 5
        iteration = 0
        
        while iteration < max_iterations:
            iteration += 1
            print(f"[Agent] Consultando a nuvem OpenAI (Rodada {iteration}) para {user_id}...")
            
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=_conversation_memory[user_id],
                tools=get_tools_definition(),
                tool_choice="auto"
            )
            
            response_msg = response.choices[0].message
            _conversation_memory[user_id].append(response_msg)
            
            if not response_msg.tool_calls:
                # Se não houver mais chamadas de ferramenta, terminamos
                final_text = response_msg.content or "Entendi! Como posso te ajudar mais?"
                return (final_text, media_list)
            
            # Executar todas as ferramentas solicitadas nesta rodada
            for tool_call in response_msg.tool_calls:
                func_name = tool_call.function.name
                args_dict = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}
                
                tool_result_str = await run_tool(func_name, args_dict, media_list, user_id)
                
                # ── SHORT-CIRCUIT: Se a ferramenta retornou um gatilho, retornamos IMEDIATAMENTE ──
                # Não mandamos de volta para a OpenAI — ela vai corromper/resumir o código.
                # IMPORTANTE: Limpamos a memória porque ela ficou com tool_call sem resultado,
                # o que faz a OpenAI rejeitar a próxima requisição.
                if tool_result_str.startswith("TRIGGER_FLOW:"):
                    print(f"[Agent] TRIGGER_FLOW detectado. Limpando memória e retornando direto ao bot.", flush=True)
                    _conversation_memory.pop(user_id, None)
                    return (tool_result_str, media_list)

                _conversation_memory[user_id].append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": tool_result_str
                })
        
        print(f"[Agent Warning] Limite de {max_iterations} iterações atingido.")
        # Se atingir o limite, tenta uma última resposta sem ferramentas
        final_response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=_conversation_memory[user_id]
        )
        final_text = final_response.choices[0].message.content
        return (final_text, media_list)
            
    except Exception as e:
        import traceback
        print(f"[Agent Error] {e}", flush=True)
        print(f"[Agent Error Traceback] {traceback.format_exc()}", flush=True)
        # Limpa a memória para evitar erros em cascata (ex: tool_call sem resultado)
        _conversation_memory.pop(user_id, None)
        return ("Eita! Meu cérebro de inteligência artificial aqui deu um soluço. Me dá um tempinho e tenta mandar a mensagem de novo?", [])

async def process_whatsapp_message(sender_phone: str, user_text: str):
    """
    Funcao principal chamada pelo webhook do Meta/WhatsApp.
    """
    try:
        user_text = user_text.strip()

        # 0. Escolha de apontamento PRODES pendente — intercepta ANTES da IA.
        # A memória de conversa é apagada a cada TRIGGER_FLOW (ver o except
        # abaixo e o short-circuit mais acima), então numa mensagem futura
        # como "19" a IA não tem mais nenhum contexto de que existe uma
        # listagem PRODES em aberto — ela via só o texto sozinho e ou inventa
        # coordenadas (já causou bug em produção) ou, como reportado, nem
        # confia em chamar a ferramenta e só pergunta o que fazer. Resolvendo
        # aqui, em Python, contra o cache real (app/whatsapp/trigger_handler),
        # é determinístico e não depende da IA "lembrar" nada.
        pending = None
        try:
            from app.whatsapp.trigger_handler import _prodes_session_cache
            from app.prodes_analysis import parse_apontamento_selection
            candidate = _prodes_session_cache.get(sender_phone)
            if candidate and parse_apontamento_selection(user_text, len(candidate['apontamentos'])) is not None:
                pending = candidate
        except Exception as e:
            # Só a checagem do cache é defensiva — se ISSO falhar, cai pro fluxo normal
            # (a IA pergunta/tenta de novo). Já a chamada real ao handler (abaixo, fora
            # deste try) não pode ser engolida em silêncio: se `pending` foi identificado
            # e a chamada falhar, o erro deve aparecer pro usuário, não virar um "a IA
            # não entendeu" — foi exatamente isso que mascarou o bug anterior.
            print(f"[Agent] Falha ao checar cache PRODES pendente (seguindo pro fluxo normal): {e}", flush=True)

        if pending:
            from app.whatsapp.trigger_handler import handle_wa_trigger_flow
            await handle_wa_trigger_flow(
                sender_phone, f"TRIGGER_FLOW: PRODES_ESCOLHA | | | {pending['nome']} | {user_text}"
            )
            return

        # 1. Interceptar Cliques do Menu Interativo
        if user_text == "TRIGGER_COTACAO":
            from app.whatsapp.trigger_handler import handle_wa_trigger_flow
            await handle_wa_trigger_flow(sender_phone, "TRIGGER_FLOW: COTACAO")
            return
        elif user_text == "TRIGGER_MERCADO_FUTURO":
            from app.whatsapp.trigger_handler import handle_wa_trigger_flow
            await handle_wa_trigger_flow(sender_phone, "TRIGGER_FLOW: MERCADO_FUTURO")
            return
        elif user_text == "TRIGGER_LEILAO":
            from app.whatsapp.trigger_handler import handle_wa_trigger_flow
            await handle_wa_trigger_flow(sender_phone, "TRIGGER_FLOW: LEILAO")
            return
        elif user_text == "TRIGGER_PREVISAO_CHUVA":
            user_text = "Quero a previsão de chuva. (Se eu não fornecer as coordenadas ou nome da propriedade, me peça)"
        elif user_text == "TRIGGER_NDVI":
            user_text = "Quero o mapa de saúde do pasto NDVI. (Se eu não fornecer as coordenadas ou nome da propriedade, me peça)"
        elif user_text == "TRIGGER_MDT":
            user_text = "Quero o mapa de topografia MDT. (Se eu não fornecer as coordenadas ou nome da propriedade, me peça)"
        elif user_text == "TRIGGER_PRODES":
            user_text = "Quero analisar apontamentos de desmatamento do PRODES no meu imóvel. (Se eu não fornecer as coordenadas ou nome da propriedade, me peça)"
        elif user_text == "TRIGGER_LISTAR":
            user_text = "Liste minhas propriedades cadastradas."

        from app.weather import extract_coords_from_url
        coords = extract_coords_from_url(user_text)
        if coords:
            lat, lon = coords
            user_text += f"\n[Sistema: O usuário enviou um mapa com coordenadas: {lat}, {lon}]"

        resposta_txt, media_list = await get_agent_response(
            sender_phone, user_text,
            context_info="O usuário está conversando via WhatsApp."
        )

        # Interceptar TRIGGER_FLOW — delega para o handler visual do WhatsApp
        if resposta_txt and "TRIGGER_FLOW" in resposta_txt:
            print(f"[WA] TRIGGER_FLOW detectado: {resposta_txt[:100]}", flush=True)
            from app.whatsapp.trigger_handler import handle_wa_trigger_flow
            await handle_wa_trigger_flow(sender_phone, resposta_txt)
            return

        # Enviar mídia se houver
        if media_list:
            from app.whatsapp.sender import send_whatsapp_image
            for media_buffer in media_list:
                try:
                    send_whatsapp_image(sender_phone, media_buffer, "")
                except Exception as me:
                    print(f"[WA] Erro ao enviar mídia: {me}", flush=True)

        # Enviar texto
        if resposta_txt:
            send_whatsapp_text(sender_phone, resposta_txt)

    except Exception as e:
        import traceback
        print(f"[WhatsApp Worker Error] {traceback.format_exc()}", flush=True)
        try:
            send_whatsapp_text(sender_phone, "⚠️ Desculpe, tive um problema técnico. Tente novamente em instantes.")
        except Exception:
            pass

async def transcribe_audio_bytes(audio_bytes: bytes, ext: str = ".ogg") -> str:
    """
    Transcreve um arquivo de áudio para texto usando OpenAI Whisper.
    Salva temporariamente no disco para compatibilidade com a API.
    """
    import tempfile
    import os
    
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("[AGENT] OPENAI_API_KEY não configurada para Whisper.")
        return ""
        
    client = AsyncOpenAI(api_key=api_key)
    
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_name = tmp.name
        
    try:
        with open(tmp_name, "rb") as f:
            response = await client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                language="pt"
            )
            return response.text
    except Exception as e:
        print(f"[WHISPER ERROR] {e}", flush=True)
        return ""
    finally:
        try:
            os.remove(tmp_name)
        except Exception:
            pass
