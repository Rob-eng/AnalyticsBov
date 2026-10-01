"""
Checagem funcional das ferramentas do bot (roda o caminho real, com casos fixos).

Diferente dos health probes (app/health_probe.py, a cada 30 min, só "o serviço
responde?"), aqui cada ferramenta é executada de ponta a ponta e a SAÍDA é
conferida — pega quebras como cena de satélite sem pixels, Yandex mudando de
PNG para JPEG ou Scot devolvendo página vazia.

Resultados vão para health_check_results com prefixo "Ferramenta: ".
Rodar:  python -m app.qa.tool_checks        (ou POST /admin/qa/tools)
"""
import os
import time

# Casos de referência (imóveis reais já validados manualmente)
REF_LAT, REF_LON = -20.1417, -55.2013          # Faz Santa Fé, Aquidauana/MS
REF_CAR = "MS-5001102-F4C226D613B14507A3417DE2438AC122"
REF_PRODES_MIN = 20                              # 23 apontamentos em 09/2026


def _ok(msg):
    return {"status": "ok", "message": msg}


def _fail(msg):
    return {"status": "error", "message": msg}


def _file_ok(path, min_bytes=10_000):
    return bool(path) and os.path.exists(path) and os.path.getsize(path) >= min_bytes


def _buf_size(buf):
    return len(buf.getvalue()) if hasattr(buf, "getvalue") else len(buf or b"")


# ── Checagens ─────────────────────────────────────────────────────────────────

def check_cotacao():
    from app.scraper import fetch_data
    from app.models import get_recent_prices
    from app.charts import generate_chart
    data = fetch_data()
    countries = {d["country"] for d in data}
    if len(countries) < 7:
        return _fail(f"Scot devolveu só {len(countries)} países")
    path = generate_chart(get_recent_prices() or data)
    if not _file_ok(path):
        return _fail("gráfico de cotação não gerado")
    return _ok(f"{len(countries)} países, gráfico {os.path.getsize(path)//1024} KB")


def check_mercado_futuro():
    from app.scraper import get_futures_table
    from app.charts import generate_future_table
    from app.futures_projection import build_bot_projection
    table = get_futures_table()
    if not table or len(table.get("rows", [])) < 4:
        return _fail("tabela do mercado futuro vazia (Scot e B3)")
    if not _file_ok(generate_future_table(table)):
        return _fail("imagem da tabela não gerada")
    path, caption = build_bot_projection("MS")
    if not _file_ok(path) or "Curva projetada" not in caption:
        return _fail("curva projetada não gerada")
    return _ok(f"tabela {len(table['rows'])} vencimentos ({table.get('source')}), curva OK")


def check_datagro():
    from app.scraper_datagro import fetch_datagro_livestock
    recs = fetch_datagro_livestock()
    boi = [r for r in recs if r["category"] == "boi"]
    if len(boi) < 9:
        return _fail(f"só {len(boi)} praças do Indicador do Boi")
    bad = [r for r in boi if not 150 < r["value"] < 800]
    if bad:
        return _fail(f"valor fora da faixa: {bad[0]['region']} {bad[0]['value']}")
    return _ok(f"{len(recs)} cotações, boi em {len(boi)} praças ({max(r['ref_date'] for r in boi)})")


def check_ndvi():
    from app.environmental import fetch_car_perimeter, get_ndvi_analysis
    geometry, status, cod = fetch_car_perimeter(REF_LAT, REF_LON)
    if status != "OFFICIAL":
        return _fail(f"perímetro CAR não encontrado (status {status})")
    result = get_ndvi_analysis(geometry)
    if not result:
        return _fail("sem cena Sentinel-2 aproveitável")
    mean = (result.get("stats") or {}).get("mean")
    if mean is None or not 0 <= mean <= 1:
        return _fail(f"NDVI médio inválido: {mean}")
    return _ok(f"NDVI {mean:.2f} ({cod})")


def check_clima():
    from app.gee_connector import get_precipitation_heatmap
    from app.weather import generate_weather_map_with_title
    heat = get_precipitation_heatmap(REF_LAT, REF_LON)
    if not heat or _buf_size(heat.get("buffer")) < 10_000:
        return _fail("mapa de calor de chuva não gerado")
    sat = generate_weather_map_with_title(REF_LAT, REF_LON, "QA")
    if not sat or _buf_size(sat) < 10_000:
        return _fail("mapa de satélite (Yandex) não gerado")
    return _ok("mapa de calor e mapa de satélite OK")


def check_cda():
    from app.charts import generate_cda_price_chart
    path = generate_cda_price_chart(days=365)
    if not _file_ok(path):
        return _fail("gráfico CDA não gerado")
    return _ok(f"gráfico CDA {os.path.getsize(path)//1024} KB")


def check_prodes():
    from app.prodes_analysis import fetch_car_perimeter_full, find_intersecting_apontamentos
    car = fetch_car_perimeter_full(REF_LAT, REF_LON)
    if car.get("status") != "OFFICIAL" or car.get("cod_imovel") != REF_CAR:
        return _fail(f"CAR de referência não encontrado ({car.get('status')}, {car.get('cod_imovel')})")
    aps = find_intersecting_apontamentos(car["geometry"])
    if len(aps) < REF_PRODES_MIN:
        return _fail(f"só {len(aps)} apontamentos PRODES (esperado ≥ {REF_PRODES_MIN})")
    return _ok(f"{len(aps)} apontamentos PRODES no imóvel de referência")


CHECKS = {
    "Cotação (Scot)": check_cotacao,
    "Mercado Futuro": check_mercado_futuro,
    "DATAGRO": check_datagro,
    "NDVI": check_ndvi,
    "Clima": check_clima,
    "Leilão CDA": check_cda,
    "PRODES": check_prodes,
}


def run_tool_checks(save_to_db: bool = True, notify: bool = True) -> dict:
    results = {}
    for name, fn in CHECKS.items():
        t0 = time.time()
        try:
            r = fn()
        except Exception as e:
            r = _fail(f"{type(e).__name__}: {str(e)[:180]}")
        r["latency_ms"] = round((time.time() - t0) * 1000)
        results[f"Ferramenta: {name}"] = r
        print(f"[QA] {name}: {r['status']} ({r['latency_ms']}ms) — {r['message']}", flush=True)

    if save_to_db:
        from app.health_probe import _persist
        _persist(results)

    failed = {k: v for k, v in results.items() if v["status"] != "ok"}
    if notify and failed:
        from app.notifications import notify_admin
        lines = [f"❌ {k.replace('Ferramenta: ', '')}: {v['message']}" for k, v in failed.items()]
        notify_admin(f"*QA das ferramentas: {len(failed)}/{len(results)} com falha*\n\n" + "\n".join(lines))
    return results


if __name__ == "__main__":
    run_tool_checks(save_to_db=False, notify=False)
