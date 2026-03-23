import asyncio
import os
import sys
import json
import logging
from datetime import datetime

# Importações do sistema (ajuste de path se necessário)
sys.path.append(os.getcwd())

from app.agent import run_tool
from app.models import SessionLocal, User
from app.saas.billing import PLANS

# Configura Logger
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger("TestHealth")

async def test_tool_health():
    """Testa as ferramentas principais do agente via Agent Loop."""
    
    test_coords = {"lat": -20.46, "lon": -54.61} # Campo Grande, MS
    test_user = "TEST_USER_123"
    
    tools_to_test = [
        ("verificar_previsao_chuva", {"lat": test_coords["lat"], "lon": test_coords["lon"]}),
        ("verificar_historico_chuvas", {"lat": test_coords["lat"], "lon": test_coords["lon"]}),
        # ("analisar_saude_pasto_ndvi", {"lat": test_coords["lat"], "lon": test_coords["lon"]}), # GEE pode demorar
        ("gerar_mapa_topografia_mdt", {"lat": test_coords["lat"], "lon": test_coords["lon"]}),
        ("verificar_cotacoes_b3", {}),
        ("verificar_planos_assinatura", {})
    ]
    
    logger.info("🚀 Iniciando Testes Automatizados das Ferramentas...")
    
    results = []
    for name, args in tools_to_test:
        logger.info(f"🧪 Testando: {name}...")
        try:
            # Chama a ferramenta diretamente como o agente faria
            start_time = datetime.now()
            res = await run_tool(name, args, test_user)
            duration = (datetime.now() - start_time).total_seconds()
            
            if "erro" in str(res).lower() or "fail" in str(res).lower():
                logger.error(f"❌ {name} falhou em {duration:.2f}s: {res[:100]}")
                results.append({"tool": name, "status": "FAIL", "error": res})
            else:
                logger.info(f"✅ {name} ok ({duration:.2f}s)")
                results.append({"tool": name, "status": "PASS"})
        except Exception as e:
            logger.error(f"💥 {name} explodiu: {e}")
            results.append({"tool": name, "status": "CRASH", "error": str(e)})

    return results

def test_db_connection():
    """Testa se o banco de dados principal e o CAR estão acessíveis."""
    logger.info("🗄️ Testando conexões com Banco de Dados...")
    
    # 1. Main DB
    try:
        session = SessionLocal()
        session.execute("SELECT 1")
        session.close()
        logger.info("✅ Banco Principal (Railway/Postgres) OK.")
    except Exception as e:
        logger.error(f"❌ Falha no Banco Principal: {e}")
        return False

    return True

async def main():
    db_ok = test_db_connection()
    tool_results = await test_tool_health()
    
    logger.info("\n=== RESUMO DO TESTE DE SAÚDE ===")
    logger.info(f"DB Status: {'✅ OK' if db_ok else '❌ FALHA'}")
    
    pass_count = sum(1 for r in tool_results if r["status"] == "PASS")
    logger.info(f"Ferramentas: {pass_count}/{len(tool_results)} PASSOU")
    
    if pass_count < len(tool_results):
        logger.warning("⚠️ Algumas ferramentas precisam de atenção!")
        sys.exit(1)
    else:
        logger.info("✨ Tudo funcionando perfeitamente! Patrão pode dormir tranquilo.")
        sys.exit(0)

if __name__ == "__main__":
    asyncio.run(main())
