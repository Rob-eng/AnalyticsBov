from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from app.scraper import run_scraping_cycle
from app.bot import broadcast_report
from app.ndvi_alerts import run_ndvi_alert_scan
import asyncio

def setup_scheduler(application):
    scheduler = AsyncIOScheduler(timezone="America/Sao_Paulo")

    # ── Weekly market report (Monday 06:30 BRT) ───────────────────────────
    async def weekly_report_job():
        print("Running weekly market report...", flush=True)
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(None, run_scraping_cycle)
        if data:
            await broadcast_report(application, data)
        else:
            print("No market data collected, skipping broadcast.", flush=True)

    scheduler.add_job(
        weekly_report_job,
        CronTrigger(day_of_week='mon', hour=10, minute=30, timezone="America/Sao_Paulo"),
        id='weekly_report',
        replace_existing=True,
    )

    # ── NDVI alert scan every 12 hours ───────────────────────────────────
    async def ndvi_alert_job():
        await run_ndvi_alert_scan(application)

    scheduler.add_job(
        ndvi_alert_job,
        IntervalTrigger(hours=12),
        id='ndvi_alert_scan',
        replace_existing=True,
        # Small initial delay so GEE is not hit at the same second as startup
        next_run_time=None,  # will compute first run 12h from now
    )

    print("✓ Scheduler configured: weekly_report + ndvi_alert_scan (12h)", flush=True)
    return scheduler
