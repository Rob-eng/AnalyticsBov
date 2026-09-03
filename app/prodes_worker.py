"""
Poller da fila de análises PRODES (tabela prodes_jobs). Chamado a partir de
app/scheduler.py via APScheduler, no mesmo processo que já roda o bot/API —
não há Celery/RQ/Redis neste projeto (ver prompt_ferramenta_prodes_bot.md).

Reivindicação de trabalho via `SELECT ... FOR UPDATE SKIP LOCKED`, robusta
mesmo que a infra passe a rodar mais de um processo no futuro (hoje só há
um processo rodando o scheduler, em produção e dev).
"""
import asyncio
import hashlib
import json
import re
import traceback
import uuid as _uuid
from datetime import datetime, timedelta
from io import BytesIO

from sqlalchemy import text

from app.config import Config

# app.models importa `from app.models import ...` exige DATABASE_URL configurada
# (checado no import do módulo) — mantido como import tardio dentro de cada
# função aqui embaixo, para compute_idempotency_key/compute_backoff_seconds
# serem testáveis sem banco (ver test_prodes_worker.py).

CLAIM_SQL = text("""
    UPDATE prodes_jobs
    SET status='PROCESSING', locked_by=:worker_id, locked_at=now(),
        attempts=attempts+1, updated_at=now()
    WHERE id IN (
        SELECT id FROM prodes_jobs
        WHERE (status='PENDING' AND (next_attempt_at IS NULL OR next_attempt_at <= now()))
           OR (status='PROCESSING' AND locked_at < now() - make_interval(mins => :stale_minutes))
        ORDER BY created_at
        LIMIT :batch_size
        FOR UPDATE SKIP LOCKED
    )
    RETURNING id
""")

BACKOFF_BASE_SECONDS = 30
BACKOFF_CAP_SECONDS = 300


def compute_idempotency_key(location_key: str, apontamento_uuid: str,
                             before_date, after_date, base_version: str) -> str:
    """Mesmos inputs -> mesma chave; qualquer input diferente -> chave diferente."""
    before_str = before_date.isoformat() if before_date else 'auto'
    after_str = after_date.isoformat() if after_date else 'auto'
    raw = f"{location_key}|{apontamento_uuid}|{before_str}|{after_str}|{base_version}"
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def compute_backoff_seconds(attempts: int) -> int:
    """Backoff exponencial (base 30s, dobra por tentativa, cap em 5min)."""
    return min(BACKOFF_BASE_SECONDS * (2 ** max(attempts - 1, 0)), BACKOFF_CAP_SECONDS)


def enqueue_prodes_jobs(user_id: str, chat_id: str, location_lat: float, location_lon: float,
                         location_name: str, cod_imovel: str, geometry_geojson: dict,
                         source_info: dict, chosen_apontamentos: list,
                         forced_before=None, forced_after=None) -> list:
    """
    Cria um ProdesJob por apontamento escolhido (chave de idempotência por
    apontamento+datas+versão da consulta). Compartilhado entre Telegram
    (app/bot.py) e WhatsApp (app/whatsapp/trigger_handler.py) — a fila e o
    worker são os mesmos pras duas plataformas; só o destino final do
    resultado muda (ver _process_single_job / _get_user_platform abaixo).
    Autorização na camada de dados: o job sempre grava o user_id/chat_id do
    próprio request — não há como um usuário enfileirar job em nome de outro.
    Devolve lista de (job_id, class_name). Levanta em caso de erro (o chamador decide a mensagem).
    """
    from app.models import SessionLocal, ProdesJob

    location_key = f"{location_lat:.6f},{location_lon:.6f}"
    # Não há "versão da base" (consulta ao vivo) — usa a data da consulta como
    # componente grosseiro de versão na chave de cache (INPE não atualiza sub-diariamente).
    source_version = source_info['queried_at'].strftime('%Y-%m-%d')
    geometry_json = json.dumps(geometry_geojson)

    session = SessionLocal()
    job_entries = []
    try:
        for ap in chosen_apontamentos:
            idem_key = compute_idempotency_key(
                location_key, ap['uuid'], forced_before, forced_after, source_version
            )
            new_job = ProdesJob(
                user_id=user_id, chat_id=chat_id,
                location_lat=location_lat, location_lon=location_lon, location_name=location_name,
                car_cod_imovel=cod_imovel, car_status='OFFICIAL',
                car_perimeter_geojson=geometry_json,
                source_label=source_info['label'], source_queried_at=source_info['queried_at'],
                apontamento_uuid=ap['uuid'], apontamento_class_name=ap['class_name'],
                apontamento_year=ap['year'], apontamento_image_date=ap['image_date'],
                apontamento_geometry_geojson=json.dumps(ap['geometry']),
                area_total_ha=ap['area_total_ha'], area_intersect_ha=ap['area_intersect_ha'],
                forced_before_date=forced_before, forced_after_date=forced_after,
                status='PENDING', idempotency_key=idem_key,
            )
            session.add(new_job)
            session.flush()
            job_entries.append((new_job.id, ap['class_name']))
        session.commit()
        return job_entries
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _get_user_platform(user_id: str) -> str:
    """'whatsapp' ou 'telegram' (default), pra _process_single_job decidir como entregar o resultado."""
    from app.models import SessionLocal, User
    session = SessionLocal()
    try:
        user = session.query(User).filter_by(chat_id=str(user_id)).first()
        return user.platform if user and user.platform else 'telegram'
    finally:
        session.close()


def _scrub_credentials(message: str) -> str:
    """Nunca deixar a service account vazar numa mensagem de erro salva/enviada."""
    if not message:
        return ""
    return re.sub(r'"private_key"\s*:\s*"[^"]*"', '"private_key": "[REDACTED]"', message)


# ── Poller ────────────────────────────────────────────────────────────────

async def run_prodes_poll(application):
    """Chamado pelo APScheduler a cada Config.PRODES_POLL_INTERVAL_SECONDS."""
    from app.models import SessionLocal, ProdesJob

    worker_id = f"worker-{_uuid.uuid4().hex[:8]}"
    jobs = []
    session = SessionLocal()
    try:
        result = session.execute(CLAIM_SQL, {
            'worker_id': worker_id,
            'stale_minutes': Config.PRODES_JOB_STALE_MINUTES,
            'batch_size': Config.PRODES_MAX_CONCURRENT_JOBS,
        })
        claimed_ids = [row[0] for row in result.fetchall()]
        session.commit()
        if claimed_ids:
            jobs = session.query(ProdesJob).filter(ProdesJob.id.in_(claimed_ids)).all()
            for j in jobs:
                session.expunge(j)
    except Exception as e:
        print(f"[PRODES WORKER] Falha ao reivindicar jobs: {e}", flush=True)
        session.rollback()
        return
    finally:
        session.close()

    if not jobs:
        return

    print(f"[PRODES WORKER] {worker_id} reivindicou {len(jobs)} job(s): {[j.id for j in jobs]}", flush=True)
    for job in jobs:
        await _process_single_job(job, application)


async def _process_single_job(job, application):
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(None, _run_job_pipeline, job)
    except Exception as e:
        tb = traceback.format_exc()
        print(f"[PRODES WORKER] Job #{job.id} erro no pipeline: {tb}", flush=True)
        _handle_job_error(job, str(e))
        return

    platform = await loop.run_in_executor(None, _get_user_platform, job.user_id)

    try:
        if platform == 'whatsapp':
            # send_whatsapp_* são síncronas (requests.post) — mesmo padrão já usado
            # em app/whatsapp/trigger_handler.py (chamadas diretas dentro de handlers async).
            from app.whatsapp.sender import send_whatsapp_image, send_whatsapp_document
            send_whatsapp_image(job.chat_id, BytesIO(result['map_before_png']),
                                 f"🛰️ Cena ANTES — análise PRODES #{job.id}")
            send_whatsapp_image(job.chat_id, BytesIO(result['map_after_png']),
                                 f"🛰️ Cena DEPOIS — análise PRODES #{job.id}")
            send_whatsapp_document(job.chat_id, BytesIO(result['pdf_bytes']),
                                    filename=f"prodes_relatorio_{job.id}.pdf", caption="📄 Relatório PRODES")
        else:
            await application.bot.send_photo(
                chat_id=job.chat_id, photo=BytesIO(result['map_before_png']),
                caption=f"🛰️ Cena ANTES — análise PRODES #{job.id}",
            )
            await application.bot.send_photo(
                chat_id=job.chat_id, photo=BytesIO(result['map_after_png']),
                caption=f"🛰️ Cena DEPOIS — análise PRODES #{job.id}",
            )
            await application.bot.send_document(
                chat_id=job.chat_id, document=BytesIO(result['pdf_bytes']),
                filename=f"prodes_relatorio_{job.id}.pdf",
                caption="📄 Relatório PRODES",
            )
    except Exception as e:
        print(f"[PRODES WORKER] Job #{job.id} processado, mas falhou ao enviar ao usuário ({platform}): {e}", flush=True)
        from app.notifications import notify_admin
        notify_admin(f"⚠️ Job PRODES #{job.id} processado mas falhou ao enviar ao usuário ({platform}): {e}")

    _mark_job_done(job.id, result)


# ── Pipeline síncrono (roda em thread pool) ─────────────────────────────────

def _run_job_pipeline(job) -> dict:
    from app import prodes_analysis, prodes_maps, prodes_pdf, prodes_storage

    # Não há tabela de "base PRODES" a reconsultar — os apontamentos vêm do
    # WFS ao vivo (ver find_intersecting_apontamentos); source_label/
    # source_queried_at já foram gravados no job no momento da listagem.
    source_info = {'label': job.source_label, 'queried_at': job.source_queried_at}

    apontamento_dict = {
        'class_name': job.apontamento_class_name,
        'year': job.apontamento_year,
        'image_date': job.apontamento_image_date,
        'uuid': job.apontamento_uuid,
    }
    apontamento_geometry = json.loads(job.apontamento_geometry_geojson)
    property_geometry = json.loads(job.car_perimeter_geojson)

    cache_prefix = f"prodes/{job.idempotency_key}"
    cached_pdf = prodes_storage.download_bytes(f"{cache_prefix}/report.pdf")
    cached_before = prodes_storage.download_bytes(f"{cache_prefix}/before.png")
    cached_after = prodes_storage.download_bytes(f"{cache_prefix}/after.png")
    if cached_pdf and cached_before and cached_after:
        print(f"[PRODES WORKER] Job #{job.id}: cache hit no GCS ({cache_prefix}).", flush=True)
        return {
            'pdf_bytes': cached_pdf, 'map_before_png': cached_before, 'map_after_png': cached_after,
            'pdf_path': f"{cache_prefix}/report.pdf",
            'png_before_path': f"{cache_prefix}/before.png",
            'png_after_path': f"{cache_prefix}/after.png",
        }

    scenes = prodes_analysis.select_before_after_scenes(
        property_geometry, apontamento_dict, job.forced_before_date, job.forced_after_date,
    )
    scene_before, scene_after = scenes['scene_before'], scenes['scene_after']
    if not scene_before or not scene_after:
        missing = 'antes' if not scene_before else 'depois'
        raise RuntimeError(
            f"Não foi possível encontrar cena aprovada ('{missing}') dentro dos "
            "critérios de nuvem/cobertura sobre o imóvel."
        )

    footer_notes = prodes_analysis.build_footer_notes(scenes, source_info)

    before_png = prodes_analysis.render_scene_visualization(scene_before, property_geometry)
    after_png = prodes_analysis.render_scene_visualization(scene_after, property_geometry)

    # Áreas já vêm calculadas (WFS + shapely) no momento em que o usuário viu
    # a lista (job.area_total_ha/area_intersect_ha, gravadas por
    # find_intersecting_apontamentos) — não recalcula aqui, para o relatório
    # bater exatamente com o que foi mostrado.
    area_total_ha = job.area_total_ha or 0.0
    area_intersect_ha = job.area_intersect_ha or 0.0

    map_before_bytes = prodes_maps.compose_prodes_map(
        before_png, property_geometry, apontamento_geometry, scene_before,
        area_total_ha, area_intersect_ha, source_info, 'antes', footer_notes,
    ).getvalue()
    map_after_bytes = prodes_maps.compose_prodes_map(
        after_png, property_geometry, apontamento_geometry, scene_after,
        area_total_ha, area_intersect_ha, source_info, 'depois', footer_notes,
    ).getvalue()

    property_info = {
        'cod_imovel': job.car_cod_imovel,
        'municipio': job.location_name,
        'uf': None,
        'area_ha': None,
    }
    apontamento_for_pdf = {
        'class_name': apontamento_dict['class_name'],
        'year': apontamento_dict['year'],
        'area_total_ha': area_total_ha,
        'area_intersect_ha': area_intersect_ha,
    }
    pdf_bytes = prodes_pdf.build_prodes_report(
        job, apontamento_for_pdf, property_info, scene_before, scene_after,
        map_before_bytes, map_after_bytes, source_info, footer_notes,
    )

    png_before_path = f"{cache_prefix}/before.png"
    png_after_path = f"{cache_prefix}/after.png"
    pdf_path = f"{cache_prefix}/report.pdf"
    try:
        prodes_storage.upload_bytes(png_before_path, map_before_bytes, 'image/png')
        prodes_storage.upload_bytes(png_after_path, map_after_bytes, 'image/png')
        prodes_storage.upload_bytes(pdf_path, pdf_bytes, 'application/pdf')
    except RuntimeError as e:
        print(f"[PRODES WORKER] Storage indisponível (job #{job.id} segue sem cache): {e}", flush=True)
        png_before_path = png_after_path = pdf_path = None

    return {
        'pdf_bytes': pdf_bytes, 'map_before_png': map_before_bytes, 'map_after_png': map_after_bytes,
        'pdf_path': pdf_path, 'png_before_path': png_before_path, 'png_after_path': png_after_path,
    }


# ── Atualização de estado do job ────────────────────────────────────────────

def _mark_job_done(job_id: int, result: dict):
    from app.models import SessionLocal, ProdesJob

    session = SessionLocal()
    try:
        row = session.query(ProdesJob).get(job_id)
        if not row:
            return
        row.status = 'DONE'
        row.result_pdf_path = result.get('pdf_path')
        row.result_png_before_path = result.get('png_before_path')
        row.result_png_after_path = result.get('png_after_path')
        row.locked_by = None
        row.locked_at = None
        row.finished_at = datetime.utcnow()
        row.updated_at = datetime.utcnow()
        session.commit()
    finally:
        session.close()


def _handle_job_error(job, error_message: str):
    """Esgotou tentativas -> ERROR + notifica usuário/admin. Senão -> PENDING com backoff."""
    from app.models import SessionLocal, ProdesJob

    session = SessionLocal()
    try:
        row = session.query(ProdesJob).get(job.id)
        if not row:
            return
        safe_message = _scrub_credentials(error_message)[:2000]
        row.last_error = safe_message
        row.locked_by = None
        row.locked_at = None
        row.updated_at = datetime.utcnow()
        if row.attempts >= row.max_attempts:
            row.status = 'ERROR'
            row.finished_at = datetime.utcnow()
            session.commit()
            from app.notifications import notify_admin
            notify_admin(f"❌ Job PRODES #{job.id} esgotou {row.attempts} tentativas.\nErro: {safe_message}")
            _notify_user_failure(job)
        else:
            row.status = 'PENDING'
            row.next_attempt_at = datetime.utcnow() + timedelta(seconds=compute_backoff_seconds(row.attempts))
            session.commit()
    finally:
        session.close()


def _notify_user_failure(job):
    """Push simples via HTTP direto (mesmo padrão de app/notifications.notify_admin) —
    evita depender de um Application vivo neste contexto síncrono."""
    message = (
        f"❌ Não foi possível concluir a análise PRODES (job #{job.id}) após várias tentativas. "
        "Tente novamente mais tarde."
    )
    platform = _get_user_platform(job.user_id)
    if platform == 'whatsapp':
        try:
            from app.whatsapp.sender import send_whatsapp_text
            send_whatsapp_text(job.chat_id, message)
        except Exception as e:
            print(f"[PRODES WORKER] Falha ao notificar usuário WhatsApp do job #{job.id}: {e}", flush=True)
        return

    import requests
    if not Config.TELEGRAM_TOKEN:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{Config.TELEGRAM_TOKEN}/sendMessage",
            json={'chat_id': job.chat_id, 'text': message},
            timeout=10,
        )
    except Exception as e:
        print(f"[PRODES WORKER] Falha ao notificar usuário do job #{job.id}: {e}", flush=True)
