# Run the application (Unified Entry Point)
# This script runs both the Telegram Bot and the FastAPI service in separate processes.
import time
import os
import multiprocessing
import uvicorn
import sys

# Debug: Log process info immediately
print(f"🔍 Process Starting | PID: {os.getpid()} | PPID: {os.getppid()} | Name: {multiprocessing.current_process().name}", flush=True)

from api_main import app
from app.models import init_db

# Bot imports
from app.bot import create_bot_application
from app.scheduler import setup_scheduler
import migrate_ms # Import master migration script

def run_api_process():
    """Runs the FastAPI service in a separate process."""
    print("🚀 Starting API Service...")
    
    # SQLAlchemy Multiprocessing safety: Dispose engines to reset connection pool in child process
    from app.models import engine, car_engine
    engine.dispose()
    car_engine.dispose()

    try:
        port = int(os.getenv("PORT", 8000))
        uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
    except Exception as e:
        print(f"❌ API Crash: {e}")

def run_bot_process():
    """Runs the Telegram Bot in a separate process."""
    print(f"🤖 Starting Telegram Bot... | PID: {os.getpid()}", flush=True)
    
    # SQLAlchemy Multiprocessing safety: Dispose engines to reset connection pool in child process
    from app.models import engine, car_engine
    engine.dispose()
    car_engine.dispose()

    import asyncio
    
    async def main():
        # Initialize DB (Essential migrations only)
        # We wrap this in a timeout so the bot doesn't hang if DB is slow/down
        print("Initializing Database...", flush=True)
        try:
             await asyncio.wait_for(asyncio.to_thread(init_db), timeout=5.0)
        except asyncio.TimeoutError:
             print("⚠️ DB Init timed out! Starting bot anyway (DB might be slow).", flush=True)
        except Exception as e:
             print(f"DB Init Warning: {e}", flush=True)

        application = create_bot_application()

        # ── SCHEDULER: NÃO iniciar aqui! ──────────────────────────────────────
        # api_main.py (rodando no processo da API, run_api_process) já chama
        # setup_scheduler() incondicionalmente no evento "startup" do FastAPI.
        # Se este processo (Bot Polling) também iniciasse seu próprio scheduler,
        # teríamos DOIS AsyncIOScheduler independentes (um por processo) disparando
        # os mesmos cron jobs (alerta NDVI 06:00, ingestão CDA 05:30) ao mesmo tempo
        # — causa confirmada do bug de imagens NDVI duplicadas. O scheduler é
        # responsabilidade exclusiva do processo da API.
        print("ℹ️ Scheduler gerenciado pelo processo da API (não duplicar aqui).", flush=True)

        # Start Polling
        print("Starting Bot Polling...", flush=True)
        await application.initialize()
        
        # Garante que não existe webhook ativo atrapalhando o polling
        print(" Removing any existing Webhooks...", flush=True)
        await application.bot.delete_webhook(drop_pending_updates=True)
        
        await application.start()

        # Drop pending updates to flush any old conflicting offset
        print(" Retaking control of @updates...", flush=True)
        await application.updater.start_polling(drop_pending_updates=True)

        print("✅ Bot Polling Started Successfully!", flush=True)

        # Monitoramento ativo contra Conflitos do Telegram
        try:
            while application.updater.running:
                # Se a aplicação ainda está 'rodando' mas parou de receber updates
                # podemos checar o status interno se quisermos, mas o updater 
                # costuma lançar erros no log. 
                # Vamos apenas manter o loop vivo.
                await asyncio.sleep(5)
            
            print("⚠️ Telegram Polling parou inesperadamente.", flush=True)
            
        except Exception as inner_e:
            print(f"⚠️ Erro no loop do Bot: {inner_e}", flush=True)
            
        finally:
            print("🛑 Bot shutting down...", flush=True)
            if application.updater.running:
                await application.updater.stop()
            await application.stop()
            await application.shutdown()

    MAX_RETRIES = 10
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            asyncio.run(main())
            break  # Clean exit
        except KeyboardInterrupt:
            break
        except Exception as e:
            err_str = str(e)
            if "Conflict" in err_str or "getUpdates" in err_str:
                # Se houver conflito, esperamos um pouco menos e tentamos 'retomar' o controle
                # O drop_pending_updates na próxima tentativa deve forçar a nova instância a ser a oficial.
                wait_sec = 20
                print(f"⚠️ Telegram Conflict (instância anterior ainda ativa). Aguardando {wait_sec}s para retomar... 🔄", flush=True)
                time.sleep(wait_sec)
            else:
                print(f"❌ Bot Crash (tentativa {attempt}/{MAX_RETRIES}): {e}", flush=True)
                time.sleep(5)

if __name__ == "__main__":
    # Ensure support for spawn on all platforms (optional but good practice)
    multiprocessing.freeze_support()
    
    print("🚀 Main: Launching services...", flush=True)

    # Create processes
    api_proc = multiprocessing.Process(target=run_api_process, name="API_Process")
    bot_proc = multiprocessing.Process(target=run_bot_process, name="Bot_Process")
    
    # 1. Start API (Main process)
    # The API now handles Scheduler + Webhooks for Telegram/WhatsApp
    api_proc.start()
    time.sleep(2) # Give API a moment to bind port
    
    # 2. Re-enable Bot ONLY if NOT using Webhooks (Fallback/Dev)
    webhook_url = os.getenv("TELEGRAM_WEBHOOK_URL")
    if not webhook_url:
        print("🤖 [run_all] No Webhook URL. Starting Bot Polling as separate process...", flush=True)
        bot_proc.start()
    else:
        print("🌍 [run_all] Webhook URL found. Integrated Webhook mode active. 🚀", flush=True)
    
    try:
        # Monitor processes
        while True:
            if not api_proc.is_alive():
                print("⚠️ [run_all] API Process died! Restarting...", flush=True)
                api_proc = multiprocessing.Process(target=run_api_process, name="API_Process")
                api_proc.start()
            
            # Restart Bot Polling if it died (only if not in Webhook mode)
            if not webhook_url and not bot_proc.is_alive():
                print("⚠️ [run_all] Bot Polling Process died! Restarting...", flush=True)
                bot_proc = multiprocessing.Process(target=run_bot_process, name="Bot_Process")
                bot_proc.start()
            
            time.sleep(10)
    except KeyboardInterrupt:
        print("Stopping services...")
        api_proc.terminate()
        if not webhook_url:
            bot_proc.terminate()
        api_proc.join()
        if not webhook_url:
            bot_proc.join()
