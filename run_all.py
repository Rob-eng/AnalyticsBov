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

        # ── SCHEDULER: Ativar tarefas agendadas (cotação semanal + NDVI diário) ──
        from app.scheduler import setup_scheduler
        scheduler = setup_scheduler(application)
        scheduler.start()
        print("✅ Scheduler started!", flush=True)

        # Start Polling
        print("Starting Bot Polling...", flush=True)
        await application.initialize()
        await application.start()

        # Drop pending updates to flush any old conflicting offset
        print(" Clearing pending updates...", flush=True)
        await application.updater.start_polling(drop_pending_updates=True)

        print("✅ Bot Polling Started Successfully!", flush=True)

        # Keep the bot running and monitor polling status
        try:
            while application.updater.running:
                await asyncio.sleep(5)
            
            # Se saiu do loop mas não mandamos, a polling crashou (Conflict)
            print("⚠️ Telegram Polling parou inesperadamente. Disparando retry...", flush=True)
            raise RuntimeError("Conflict: Telegram Polling parado.")
            
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
    
    # Start API first to ensure availability
    api_proc.start()
    time.sleep(2) # Give API a moment to bind port
    
    # Re-enable Bot
    bot_proc.start()
    
    try:
        # Monitor processes
        while True:
            if not api_proc.is_alive():
                print("⚠️ API Process died! Restarting...", flush=True)
                api_proc = multiprocessing.Process(target=run_api_process, name="API_Process")
                api_proc.start()
            
            if not bot_proc.is_alive():
                print("⚠️ Bot Process died! Restarting...", flush=True)
                bot_proc = multiprocessing.Process(target=run_bot_process, name="Bot_Process")
                bot_proc.start()
            
            time.sleep(5)
    except KeyboardInterrupt:
        print("Stopping services...")
        api_proc.terminate()
        bot_proc.terminate()
        api_proc.join()
        bot_proc.join()
