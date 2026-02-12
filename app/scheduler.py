from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from app.scraper import run_scraping_cycle
from app.bot import broadcast_report
import asyncio

def setup_scheduler(application):
    scheduler = AsyncIOScheduler(timezone="America/Sao_Paulo")
    
    async def scheduled_job():
        print("Running scheduled job...")
        # Run synchronous scraping in a separate thread to avoid blocking the event loop
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(None, run_scraping_cycle)
        
        if data:
            await broadcast_report(application, data)
        else:
            print("No data collected, skipping broadcast.")

    # Schedule: Monday at 06:30 BRT
    scheduler.add_job(
        scheduled_job,
        CronTrigger(day_of_week='mon', hour=6, minute=30),

        id='weekly_report',
        replace_existing=True
    )
    
    return scheduler
