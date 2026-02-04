import asyncio
from app.models import init_db
from app.bot import create_bot_application, start, status
from app.scheduler import setup_scheduler
from telegram.ext import CommandHandler

async def post_init(application):
    print("Setting up Scheduler...")
    scheduler = setup_scheduler(application)
    scheduler.start()

def main():
    # Initialize Database
    print("Initializing Database...")
    init_db()
    
    # Create Bot Application with post_init hook
    print("Setting up Bot...")
    application = create_bot_application(post_init=post_init)
    
    # Add Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))
    
    # Run Bot
    print("Starting Bot...")
    application.run_polling()

if __name__ == "__main__":
    main()
