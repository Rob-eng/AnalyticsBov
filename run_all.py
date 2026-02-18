# Run the application (Unified Entry Point)
# This script runs both the Telegram Bot and the FastAPI service in separate processes.
import time
import os
import multiprocessing
import uvicorn
from api_main import app
from app.models import init_db

# Bot imports
from app.bot import create_bot_application
from app.scheduler import setup_scheduler

def run_api_process():
    """Runs the FastAPI service in a separate process."""
    print("🚀 Starting API Service...")
    try:
        port = int(os.getenv("PORT", 8000))
        uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
    except Exception as e:
        print(f"❌ API Crash: {e}")

def run_bot_process():
    """Runs the Telegram Bot in a separate process."""
    print("🤖 Starting Telegram Bot...")
    import asyncio
    
    async def main():
        # Initialize DB (Essential migrations only)
        print("Initializing Database...")
        try:
             await asyncio.to_thread(init_db)
        except Exception as e:
             print(f"DB Init Warning: {e}")

        application = create_bot_application()
        
        # Setup Scheduler
        print("Setting up Scheduler...")
        scheduler = setup_scheduler(application)
        scheduler.start()
        
        # Start Polling
        print("Starting Bot Polling...")
        await application.initialize()
        await application.start()
        await application.updater.start_polling()
        
        # Keep the bot running
        stop_signal = asyncio.Event()
        await stop_signal.wait()

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"❌ Bot Crash: {e}")
    finally:
        # We can't easily access 'application' here to stop it gracefully in this structure
        # but the process termination handles it.
        # Ideally main() should have a finally block.
        pass

if __name__ == "__main__":
    # Ensure support for spawn on all platforms
    multiprocessing.freeze_support()
    try:
        multiprocessing.set_start_method("spawn", force=True)
    except RuntimeError:
        pass
    
    print("🚀 Main: Launching services...", flush=True)

    # Create processes
    api_proc = multiprocessing.Process(target=run_api_process, name="API_Process")
    bot_proc = multiprocessing.Process(target=run_bot_process, name="Bot_Process")
    
    # Start API first to ensure availability
    api_proc.start()
    time.sleep(2) # Give API a moment to bind port
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
