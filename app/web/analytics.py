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


def ndvi_series(perimeter_geojson: dict, months: int = 24) -> list:
    """[{month: 'YYYY-MM', mean, p25, p75, images}] do mais antigo ao mais recente (None = sem cena limpa)."""
    if not initialize_gee():
        raise RuntimeError("Google Earth Engine indisponível")
    geom = ee.Geometry(perimeter_geojson)
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
                reducer=reducer, geometry=geom, scale=20, maxPixels=1e9, bestEffort=True),
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
