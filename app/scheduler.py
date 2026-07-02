from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from app.scraper import run_scraping_cycle
from app.scraper_cda import run_cda_daily_cycle
from app.cda_analytics import build_cda_scot_comparisons
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
        try:
            await run_ndvi_alert_scan(application)
        except Exception as e:
            import traceback
            print(f"[Scheduler] ❌ NDVI alert scan FAILED: {traceback.format_exc()}", flush=True)
            try:
                from app.notifications import notify_admin
                notify_admin(f"❌ *Falha no scan de alertas NDVI*\n\nErro: `{e}`")
            except Exception:
                pass

    scheduler.add_job(
        ndvi_alert_job,
        CronTrigger(hour=6, minute=0, timezone=USER_TZ),
        id='ndvi_alert_scan',
        replace_existing=True,
    )

    # ── Coleta diária Correa da Costa (05:30 local) ──────────────────────
    async def cda_daily_job():
        print("[Scheduler] Running Correa da Costa daily ingestion...", flush=True)
        loop = asyncio.get_running_loop()
        try:
            summary = await loop.run_in_executor(None, run_cda_daily_cycle)
            print(f"[Scheduler] CDA ingestion done: {summary}", flush=True)
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            print(f"[Scheduler] ❌ CDA ingestion FAILED: {tb}", flush=True)
            try:
                from app.notifications import notify_admin
                notify_admin(
                    "❌ *Falha na ingestão diária CDA (Correa da Costa)*\n\n"
                    f"Erro: `{e}`\n\nVeja os logs do Railway para o traceback completo."
                )
            except Exception:
                pass
            return  # não tenta o passo de comparação se a ingestão falhou

        print("[Scheduler] Building CDA vs Scot comparisons...", flush=True)
        try:
            await loop.run_in_executor(None, build_cda_scot_comparisons)
        except Exception as e:
            import traceback
            print(f"[Scheduler] ❌ CDA comparisons FAILED: {traceback.format_exc()}", flush=True)
            try:
                from app.notifications import notify_admin
                notify_admin(f"⚠️ Ingestão CDA OK, mas falha ao montar comparações Scot: `{e}`")
            except Exception:
                pass

    scheduler.add_job(
        cda_daily_job,
        CronTrigger(hour=5, minute=30, timezone=USER_TZ),
        id='cda_daily_ingest',
        replace_existing=True,
    )

    # ── Health probes a cada 30 minutos ──────────────────────────────────
    async def health_probe_job():
        try:
            from app.health_probe import run_all_probes
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, run_all_probes)
        except Exception as e:
            import traceback
            print(f"[Scheduler] ❌ Health probe FAILED: {traceback.format_exc()}", flush=True)

    scheduler.add_job(
        health_probe_job,
        IntervalTrigger(minutes=30),
        id='health_probes',
        replace_existing=True,
    )

    print(
        f"✓ Scheduler configured (tz={USER_TZ}): "
        "weekly_report (Mon 08:00) + ndvi_alert_scan (daily 06:00) "
        "+ cda_daily_ingest (daily 05:30) + health_probes (every 30min)",
        flush=True
    )
    return scheduler
