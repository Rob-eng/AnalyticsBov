import asyncio
import os
import uvicorn
from main import main as bot_main
from api_main import app
from app.models import init_db
from app.bot import create_bot_application, start, status, current_analysis, future_market, sync_history, list_users, start_feedback, receive_feedback, cancel_feedback, start_weather, receive_weather_location, cancel_weather, start_env_analysis, receive_env_location, cancel_env, start_broadcast, send_broadcast, cancel_broadcast, handle_keyboard_buttons, WAITING_FEEDBACK, WAITING_WEATHER_LOCATION, WAITING_ENV_LOCATION, WAITING_BROADCAST_MESSAGE, WAITING_LOCATION_MENU, WAITING_LOCATION_NAME, WAITING_LOCATION_COORDS, WAITING_LOCATION_DELETE, handle_location_buttons, receive_location_name, receive_location_coords, confirm_delete_location, cancel_locations, list_all_locations_admin
from app.scheduler import setup_scheduler
from telegram.ext import CommandHandler, MessageHandler, filters, ConversationHandler

async def post_init(application):
    print("Setting up Scheduler...")
    scheduler = setup_scheduler(application)
    scheduler.start()

async def run_bot():
    print("Setting up Bot...")
    # Initialize Database here as well to be safe
    init_db()
    
    application = create_bot_application(post_init=post_init)
    
    # Re-add all handlers (copied from main.py for clean execution)
    # Note: In a real refactor, main.py should expose a setup_handlers function
    
    # ... (skipping long setup for brevity in this call, I'll import it if possible)
    # Actually, main.py has logic inside main(). I should refactor main.py to be modular.
    pass

async def run_api():
    print("Starting API Service...")
    config = uvicorn.Config(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)), log_level="info")
    server = uvicorn.Server(config)
    await server.serve()

async def start_everything():
    # Modular way: Refactor main.py to allow importing the app setup
    # For now, I'll just run them as separate processes or use a modified main.
    
    # Let's use multiprocessing for simplicity and isolation
    import multiprocessing
    
    def start_bot():
        from main import main
        main()
        
    def start_api():
        import uvicorn
        from api_main import app
        uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))

    p1 = multiprocessing.Process(target=start_bot)
    p2 = multiprocessing.Process(target=start_api)
    
    p1.start()
    p2.start()
    
    p1.join()
    p2.join()

if __name__ == "__main__":
    import multiprocessing
    # For Windows compatibility (not needed here but good practice)
    multiprocessing.freeze_support()
    
    # Check if we should only run one (for flexible Railway scaling)
    mode = os.getenv("RUN_MODE", "BOTH")
    
    if mode == "BOT":
        from main import main
        main()
    elif mode == "API":
        import uvicorn
        from api_main import app
        uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
    else:
        # Run both
        from main import main
        from api_main import app
        
        p1 = multiprocessing.Process(target=main)
        # Wrap api call to use env port
        def run_api():
            uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
        p2 = multiprocessing.Process(target=run_api)
        
        p1.start()
        p2.start()
        
        p1.join()
        p2.join()
