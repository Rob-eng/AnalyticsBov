"""
Análises de satélite para a plataforma web (Google Earth Engine, Sentinel-2).

- ndvi_series(): NDVI mensal sobre o perímetro — mediana das cenas do mês com
  nuvens/sombras mascaradas (SCL), média + percentis 25/75 dos pixels (a faixa
  mostra se o pasto está homogêneo ou tem manchas fracas). Um único getInfo.
- ndvi_month_image(): mosaico NDVI de um mês recortado no perímetro (PNG) para
  comparar duas datas lado a lado.
Escala de cores fixa (0 a 0,8) idêntica em qualquer data, para a comparação valer.
"""
from datetime import date

import ee
import requests

from app.gee_connector import initialize_gee

S2 = "COPERNICUS/S2_SR_HARMONIZED"
NDVI_MIN, NDVI_MAX = 0.0, 0.8
NDVI_PALETTE = ["d7191c", "fdae61", "ffffbf", "a6d96a", "1a9641"]
# SCL: 3 sombra de nuvem, 8/9 nuvem média/alta, 10 cirrus, 11 neve
_CLOUDY_SCL = (3, 8, 9, 10, 11)


def _ndvi(img):
    scl = img.select("SCL")
    clear = scl.neq(_CLOUDY_SCL[0])
    for v in _CLOUDY_SCL[1:]:
        clear = clear.And(scl.neq(v))
    return (img.updateMask(clear).normalizedDifference(["B8", "B4"]).rename("NDVI")
            .copyProperties(img, ["system:time_start"]))


def _month_start(months_back: int) -> date:
    today = date.today()
    y, m = today.year, today.month - months_back
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, 1)


def ndvi_series(perimeter_geojson: dict, months: int = 24, scale: int = 20, buffer_m: float = 0) -> list:
    """
    [{month: 'YYYY-MM', mean, p25, p75, images}] do mais antigo ao mais recente (None = sem cena limpa).
    Serve para o perímetro inteiro ou uma zona dele (ponto com buffer, piquete): zonas pequenas usam scale=10.
    """
    if not initialize_gee():
        raise RuntimeError("Google Earth Engine indisponível")
    geom = ee.Geometry(perimeter_geojson)
    if buffer_m:
        geom = geom.buffer(buffer_m)
    start = ee.Date(_month_start(months - 1).isoformat())
    col = (ee.ImageCollection(S2).filterBounds(geom)
           .filterDate(start, ee.Date(date.today().isoformat()).advance(1, "day"))
           .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 60)))
    reducer = ee.Reducer.mean().combine(ee.Reducer.percentile([25, 75]), sharedInputs=True)

    def per_month(i):
        d = start.advance(ee.Number(i), "month")
        monthly = col.filterDate(d, d.advance(1, "month"))
        stats = ee.Dictionary(ee.Algorithms.If(
            monthly.size().gt(0),
            monthly.map(_ndvi).median().reduceRegion(
                reducer=reducer, geometry=geom, scale=scale, maxPixels=1e9, bestEffort=True),
            ee.Dictionary({}),
        ))
        # mês sem cena limpa → dicionário vazio (as chaves NDVI_* simplesmente não aparecem)
        return ee.Feature(None, stats).set({"month": d.format("YYYY-MM"), "images": monthly.size()})

    fc = ee.FeatureCollection(ee.List.sequence(0, months - 1).map(per_month)).getInfo()
    out = []
    for f in fc["features"]:
        p = f["properties"]
        out.append({"month": p["month"], "images": p.get("images", 0),
                    "mean": _r(p.get("NDVI_mean")), "p25": _r(p.get("NDVI_p25")), "p75": _r(p.get("NDVI_p75"))})
    return out


def _r(v):
    return round(v, 4) if isinstance(v, (int, float)) else None


def ndvi_month_image(perimeter_geojson: dict, month: str) -> dict:
    """Mosaico NDVI do mês (YYYY-MM) recortado no perímetro: {png: bytes, coordinates, mean, images}."""
    if not initialize_gee():
        raise RuntimeError("Google Earth Engine indisponível")
    geom = ee.Geometry(perimeter_geojson)
    y, m = (int(x) for x in month.split("-"))
    d0 = ee.Date(date(y, m, 1).isoformat())
    monthly = (ee.ImageCollection(S2).filterBounds(geom).filterDate(d0, d0.advance(1, "month"))
               .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 60)))
    n = monthly.size().getInfo()
    if n == 0:
        return {"png": None, "images": 0}
    ndvi = monthly.map(_ndvi).median().clip(geom)
    mean = ndvi.reduceRegion(ee.Reducer.mean(), geom, 20, maxPixels=1e9, bestEffort=True).get("NDVI").getInfo()
    region = geom.bounds()
    coords = region.coordinates().getInfo()[0]
    xs, ys = [c[0] for c in coords], [c[1] for c in coords]
    url = ndvi.visualize(min=NDVI_MIN, max=NDVI_MAX, palette=NDVI_PALETTE).getThumbURL(
        {"region": region, "dimensions": 1024, "format": "png"})
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    return {"png": resp.content, "images": n, "mean": _r(mean),
            "coordinates": [[x0, y1], [x1, y1], [x1, y0], [x0, y0]]}


# ── Chuva (Open-Meteo: previsão + últimos 90 dias + normal de 10 anos) ───────

def rain_summary(lat: float, lon: float) -> dict:
    """
    Previsão de 7 dias, chuva diária dos últimos 90 dias (agregada por semana)
    e o acumulado dos últimos 30 dias contra a média do mesmo período nos
    10 anos anteriores (ERA5, archive-api).
    """
    from datetime import timedelta
    tz = "America/Sao_Paulo"
    fc = requests.get("https://api.open-meteo.com/v1/forecast", timeout=30, params={
        "latitude": lat, "longitude": lon, "timezone": tz, "past_days": 90, "forecast_days": 7,
        "daily": "precipitation_sum,precipitation_probability_max",
    })
    fc.raise_for_status()
    d = fc.json()["daily"]
    today = date.today().isoformat()
    days = [{"date": t, "mm": round(mm or 0, 1), "prob": p} for t, mm, p in
            zip(d["time"], d["precipitation_sum"], d["precipitation_probability_max"])]
    past = [x for x in days if x["date"] < today]
    forecast = [x for x in days if x["date"] >= today][:7]

    weeks = []   # semanas fechadas, da mais antiga à mais recente
    for i in range(len(past) % 7, len(past), 7):
        chunk = past[i:i + 7]
        weeks.append({"start": chunk[0]["date"], "end": chunk[-1]["date"], "mm": round(sum(x["mm"] for x in chunk), 1)})

    last30 = round(sum(x["mm"] for x in past[-30:]), 1)
    # normal: mesma janela de 30 dias (dia/mês) nos 10 anos anteriores
    end = date.today() - timedelta(days=1)
    start30 = end - timedelta(days=29)
    arch = requests.get("https://archive-api.open-meteo.com/v1/archive", timeout=60, params={
        "latitude": lat, "longitude": lon, "timezone": tz, "daily": "precipitation_sum",
        "start_date": date(end.year - 10, 1, 1).isoformat(), "end_date": date(end.year - 1, 12, 31).isoformat(),
    })
    normal = None
    if arch.ok:
        a = arch.json()["daily"]
        by_day = dict(zip(a["time"], a["precipitation_sum"]))
        totals = []
        for yb in range(1, 11):
            s, e = start30.replace(year=start30.year - yb), end.replace(year=end.year - yb)
            vals = [by_day.get((s + timedelta(days=k)).isoformat()) for k in range((e - s).days + 1)]
            if vals and all(v is not None for v in vals):
                totals.append(sum(vals))
        normal = round(sum(totals) / len(totals), 1) if totals else None
    return {
        "forecast": forecast, "weeks": weeks,
        "last30_mm": last30, "normal30_mm": normal,
        "pct_of_normal": round(last30 / normal * 100) if normal else None,
        "next7_mm": round(sum(x["mm"] for x in forecast), 1),
    }
