from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from app.scraper import run_scraping_cycle
from app.bot import broadcast_report
from app.ndvi_alerts import run_ndvi_alert_scan
import asyncio

# Fuso horário do usuário: UTC-4 (sem horário de verão)
USER_TZ = "America/Manaus"

def setup_scheduler(application):
    scheduler = AsyncIOScheduler(timezone=USER_TZ)

    # ── Relatório semanal de cotação (Segunda-feira 08:00 local) ──────────
    async def weekly_report_job():
        print("[Scheduler] Running weekly market report...", flush=True)
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(None, run_scraping_cycle)
        if data:
            await broadcast_report(application, data)
        else:
            print("[Scheduler] No market data collected, skipping broadcast.", flush=True)

    scheduler.add_job(
        weekly_report_job,
        CronTrigger(day_of_week='mon', hour=8, minute=0, timezone=USER_TZ),
        id='weekly_report',
        replace_existing=True,
    )

    # ── Alerta NDVI diário (06:00 local) ─────────────────────────────────
    async def ndvi_alert_job():
        await run_ndvi_alert_scan(application)

    scheduler.add_job(
        ndvi_alert_job,
        CronTrigger(hour=6, minute=0, timezone=USER_TZ),
        id='ndvi_alert_scan',
        replace_existing=True,
    )

    print(f"✓ Scheduler configured (tz={USER_TZ}): weekly_report (Mon 08:00) + ndvi_alert_scan (daily 06:00)", flush=True)
    return scheduler

