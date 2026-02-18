# Run the application (Unified Entry Point)
# This script runs both the Telegram Bot and the FastAPI service in the same event loop.

import asyncio
import os
import uvicorn
from api_main import app
from app.models import init_db

# Bot imports
from app.bot import create_bot_application
from app.scheduler import setup_scheduler

async def run_api():
    config = uvicorn.Config(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)), log_level="info")
    server = uvicorn.Server(config)
    await server.serve()

async def run_bot():
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
    await application.updater.start_polling()
    await application.start()
    
    # Keep the bot running
    try:
        # Wait forever
        await asyncio.Event().wait() 
    finally:
        await application.stop()
        await application.updater.stop()

async def main():
    # Execute both tasks concurrently
    await asyncio.gather(
        run_api(),
        run_bot()
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"Fatal error in run_all: {e}")
