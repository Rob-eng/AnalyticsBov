"""
Avaliação das respostas do agente (Zé Botina) com conversas-modelo.

Cada cenário manda mensagens ao agente REAL (mesmo prompt e ferramentas de
produção), mas as ferramentas são interceptadas: nada é executado nem enviado.
Confere-se:
  - "tool": qual ferramenta ele chamou e com quais parâmetros (determinístico);
  - "reply": resposta em texto, avaliada por um modelo-juiz com um critério
    em linguagem natural (tom "Patrão", objetividade, não inventar números...).

Ferramentas de consulta de dados (ex.: listar_propriedades) devolvem o texto
fixo de `fake_tools`; a primeira ferramenta fora dessa lista encerra o cenário.

Novo problema visto em produção → vira um cenário aqui, para não voltar.
Rodar:  python -m app.qa.agent_eval        (ou POST /admin/qa/agent)
"""
import asyncio
import json
import os

DUAS_FAZENDAS = (
    "Propriedades cadastradas:\n"
    "1. Faz Santa Fé (lat -20.1417, lon -55.2013)\n"
    "2. Faz Guaviral (lat -22.0360, lon -56.7246)"
)
UMA_FAZENDA = "Propriedades cadastradas:\n1. Faz Santa Fé (lat -20.1417, lon -55.2013)"

SCENARIOS = [
    {"id": "futuro_sem_uf", "messages": ["Futuro"],
     "expect_tool": "consultar_mercado_futuro", "args_absent": ["uf"]},
    {"id": "futuro_com_uf", "messages": ["mercado futuro do boi em Goiás"],
     "expect_tool": "consultar_mercado_futuro", "args_equal": {"uf": "GO"}},
    {"id": "curva_vaca_mt", "messages": ["qual a projeção do preço da vaca no Mato Grosso?"],
     "expect_tool": "consultar_mercado_futuro", "args_equal": {"uf": "MT"}},
    {"id": "arroba_dezembro", "messages": ["quanto vai valer a arroba em dezembro?"],
     "expect_tool": "consultar_mercado_futuro"},
    {"id": "cotacao_hoje", "messages": ["cotação do boi hoje"],
     "expect_tool": "obter_cotacao_fisica_atual"},
    {"id": "prodes_sozinho", "messages": ["prodes"],
     "expect_tool": "analisar_prodes", "args_absent": ["escolha"],
     "fake_tools": {"listar_propriedades": UMA_FAZENDA}},
    {"id": "leilao", "messages": ["quero ver o leilão da correa da costa"],
     "expect_tool": "consultar_leilao_cda"},
    {"id": "meu_plano", "messages": ["qual é o meu plano?"],
     "expect_tool": "consultar_meu_plano"},
    {"id": "chuva_por_nome", "messages": ["vai chover na Faz Santa Fé?"],
     "expect_tool": "verificar_previsao_chuva",
     "fake_tools": {"listar_propriedades": DUAS_FAZENDAS}},
    {"id": "mapa_ambiental", "messages": ["quero o mapa ambiental da Faz Santa Fé"],
     "expect_tool": "gerar_mapa_car",
     "fake_tools": {"listar_propriedades": DUAS_FAZENDAS}},
    {"id": "mapa_car_codigo", "messages": ["me manda as camadas do CAR MS-5001102-F4C226D613B14507A3417DE2438AC122"],
     "expect_tool": "gerar_mapa_car",
     "args_equal": {"codigo_car": "MS-5001102-F4C226D613B14507A3417DE2438AC122"}},
    {"id": "reserva_legal", "messages": ["quanto tenho de reserva legal na Faz Santa Fé?"],
     "expect_tool": "gerar_mapa_car",
     "fake_tools": {"listar_propriedades": DUAS_FAZENDAS}},
    {"id": "ndvi_duas_fazendas", "messages": ["como está o pasto pelo satélite?"],
     "expect_reply": "Pergunta ao Patrão QUAL das fazendas (Santa Fé ou Guaviral) ele quer analisar, "
                     "sem escolher sozinho e sem rodar a análise.",
     "fake_tools": {"listar_propriedades": DUAS_FAZENDAS}},
    {"id": "milho", "messages": ["qual a cotação do milho hoje?"],
     "expect_reply": "Recusa educadamente cotação de milho/soja, explica que atende pecuária de corte "
                     "(boi gordo) e oferece algo relacionado ao boi. NÃO informa nenhum preço de milho."},
    {"id": "saudacao", "messages": ["oi"],
     "expect_tool": "mostrar_menu_principal"},
    {"id": "duvida_ndvi", "messages": ["o que é esse tal de NDVI?"],
     "expect_reply": "Explica de forma simples o que é NDVI (índice de vegetação por satélite, saúde do "
                     "pasto), chamando o usuário de 'Patrão', sem inventar números e oferecendo fazer a análise."},
]

JUDGE_MODEL = "gpt-4o-mini"


class _StopScenario(BaseException):
    # BaseException: atravessa o `except Exception` de get_agent_response sem
    # virar "[Agent Error]" no log — a interrupção é intencional.
    def __init__(self, name, args):
        self.name, self.args = name, args


async def _run_scenario(sc: dict) -> dict:
    import app.agent as agent

    user_id = f"qa-{sc['id']}"
    agent._conversation_memory.pop(user_id, None)
    calls = []
    fakes = sc.get("fake_tools", {})
    original = agent.run_tool

    async def fake_run_tool(name, arguments, media_list, uid):
        calls.append((name, arguments))
        if name in fakes:
            return fakes[name]
        raise _StopScenario(name, arguments)

    agent.run_tool = fake_run_tool
    reply = None
    try:
        for msg in sc["messages"]:
            try:
                reply, _ = await agent.get_agent_response(user_id, msg)
            except _StopScenario:
                break
    finally:
        agent.run_tool = original
        agent._conversation_memory.pop(user_id, None)

    # get_agent_response engole exceções: a ferramenta final fica registrada em `calls`
    final_call = next(((n, a) for n, a in reversed(calls) if n not in fakes), None)
    return {"calls": calls, "final_call": final_call, "reply": reply}


async def _judge(criterion: str, messages: list, reply: str) -> tuple:
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    prompt = (
        "Você avalia respostas de um assistente de WhatsApp para pecuaristas.\n"
        f"Mensagens do usuário: {json.dumps(messages, ensure_ascii=False)}\n"
        f"Resposta do assistente:\n<<<\n{reply}\n>>>\n"
        f"Critério esperado: {criterion}\n"
        'Responda só JSON: {"pass": true|false, "reason": "motivo curto em português"}'
    )
    resp = await client.chat.completions.create(
        model=JUDGE_MODEL, messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"}, temperature=0,
    )
    data = json.loads(resp.choices[0].message.content)
    return bool(data.get("pass")), data.get("reason", "")


async def _evaluate(sc: dict) -> dict:
    run = await _run_scenario(sc)
    result = {"id": sc["id"], "messages": sc["messages"], "passed": True, "detail": ""}

    if "expect_tool" in sc:
        call = run["final_call"]
        if not call or call[0] != sc["expect_tool"]:
            got = call[0] if call else f"nenhuma (respondeu: {(run['reply'] or '')[:120]!r})"
            result.update(passed=False, detail=f"esperava {sc['expect_tool']}, veio {got}")
            return result
        args = call[1] or {}
        for k, v in sc.get("args_equal", {}).items():
            if str(args.get(k, "")).upper() != str(v).upper():
                result.update(passed=False, detail=f"{k}={args.get(k)!r}, esperado {v!r}")
                return result
        for k in sc.get("args_absent", []):
            if args.get(k):
                result.update(passed=False, detail=f"não devia passar {k} (veio {args[k]!r})")
                return result
        result["detail"] = f"{call[0]}({json.dumps(args, ensure_ascii=False)})"

    if "expect_reply" in sc:
        if run["final_call"]:
            result.update(passed=False, detail=f"chamou {run['final_call'][0]} em vez de responder")
            return result
        ok, reason = await _judge(sc["expect_reply"], sc["messages"], run["reply"] or "")
        result.update(passed=ok, detail=reason, reply=run["reply"])
    return result


async def _evaluate_with_retry(sc: dict) -> dict:
    """O modelo não é determinístico: falhou uma vez → roda de novo. Passou na 2ª = 'instável'."""
    first = await _evaluate(sc)
    if first["passed"]:
        return first
    second = await _evaluate(sc)
    if second["passed"]:
        second["detail"] = f"INSTÁVEL (falhou 1 de 2: {first['detail']})"
        second["flaky"] = True
    return second


async def run_agent_eval_async(notify: bool = True) -> dict:
    results = [await _evaluate_with_retry(sc) for sc in SCENARIOS]
    passed = sum(r["passed"] for r in results)
    for r in results:
        print(f"[QA-AGENTE] {'✅' if r['passed'] else '❌'} {r['id']}: {r['detail']}", flush=True)
    summary = {"passed": passed, "total": len(results), "results": results}
    print(f"[QA-AGENTE] {passed}/{len(results)} cenários OK", flush=True)

    if notify and passed < len(results):
        from app.notifications import notify_admin
        lines = [f"❌ {r['id']}: {r['detail']}" for r in results if not r["passed"]]
        notify_admin(f"*QA do agente: {passed}/{len(results)} cenários OK*\n\n" + "\n".join(lines))
    return summary


def run_agent_eval(notify: bool = True) -> dict:
    return asyncio.run(run_agent_eval_async(notify))


if __name__ == "__main__":
    run_agent_eval(notify=False)
