"""
Camadas do CAR de um imóvel via serviço oficial (sem captcha).

Fonte: nova Consulta Pública do CAR (consulta.car.gov.br, MGI/SFB, mai/2026).
  - WFS público  https://consulta.car.gov.br/geoserver-download/consulta_publica/wfs
    camadas temáticas nacionais (APP por tipo, reserva legal, vegetação nativa,
    área consolidada, uso restrito, hidrografia, servidão, pousio, perímetro),
    cada feição com `cod_imovel` → filtro CQL traz só o imóvel pedido.
  - API REST     https://consulta.car.gov.br/api
      geoServices/getGeoServerLayerLink  → nomes das camadas de cada tema
      totalizer/getDetailsByCoordinates  → código CAR a partir de lat/lon
São os mesmos serviços que a plataforma expõe para uso em SIG (QGIS etc.).
Os downloads por botão da plataforma (com captcha) NÃO são usados aqui.
"""
import io
import json
import os
import tempfile
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor

import requests

API_URL = "https://consulta.car.gov.br/api"
WFS_URL = "https://consulta.car.gov.br/geoserver-download/consulta_publica/wfs"
HEADERS = {"User-Agent": "Mozilla/5.0 (AnalyticsBov)", "Referer": "https://consulta.car.gov.br/"}
TIMEOUT = 60

# Tema da plataforma → categoria usada por generate_pro_car_map / process_car_zip
THEME_CATEGORY = {
    "imovel_rural": "imovel",
    "reserva_legal": "reserva",
    "app": "app",
    "uso_restrito": "uso_restrito",
    "vegetacao_nativa": "vegetacao",
    "area_consolidada": "consolidada",
    "hidrografia": "agua",
    "servidao_administrativa": "extra_servidao",
    "area_pousio": "extra_pousio",
}

# Fallback se a API de camadas estiver fora (nomes observados em 09/2026)
_FALLBACK_LAYERS = {
    "imovel_rural": ["iru", "ast", "pct"],
    "reserva_legal": ["arl_proposta", "arl_averbada", "arl_aprovada_nao_averbada"],
    "vegetacao_nativa": ["vegetacao_nativa"],
    "area_consolidada": ["area_consolidada"],
    "area_pousio": ["area_pousio"],
    "uso_restrito": ["area_uso_restrito_declividade_25_a_45", "area_uso_restrito_pantaneira"],
    "app": [
        "app_rio_ate_10", "app_escadinha_rio_ate_10", "app_rio_10_a_50", "app_escadinha_rio_10_a_50",
        "app_rio_50_a_200", "app_escadinha_rio_50_a_200", "app_rio_200_a_600", "app_escadinha_rio_200_a_600",
        "app_rio_acima_600", "app_escadinha_rio_acima_600", "app_nascente_olho_dagua",
        "app_escadinha_nascente_olho_dagua", "app_lago_natural", "app_escadinha_lago_natural",
        "app_reservatorio_artificial_decorrente_barramento", "app_vereda", "app_escadinha_vereda",
        "app_manguezal", "app_banhado", "app_restinga", "app_reservatorio_geracao_energia_ate_24_08_2001",
        "app_area_topo_morro", "app_area_altitude_superior_1800", "app_borda_chapada",
        "app_area_declividade_maior_45",
    ],
    "hidrografia": ["rio_ate_10", "rio_10_a_50", "rio_50_a_200", "rio_200_a_600", "rio_acima_600",
                    "nascente_olho_dagua", "lago_natural", "reservatorio_artificial"],
    "servidao_administrativa": ["area_infraestrutura_publica", "area_utilidade_publica",
                                "reservatorio_para_abastecimento_ou_geracao_de_energia"],
}

_layers_cache = {"at": 0, "layers": None}
_LAYERS_TTL = 24 * 3600


def get_theme_layers() -> dict:
    """{tema: [typeName, ...]} — da API da plataforma (cache 24h), com fallback fixo."""
    from urllib.parse import parse_qs, urlparse
    if _layers_cache["layers"] and time.time() - _layers_cache["at"] < _LAYERS_TTL:
        return _layers_cache["layers"]
    try:
        resp = requests.post(
            f"{API_URL}/geoServices/getGeoServerLayerLink", headers=HEADERS, timeout=TIMEOUT,
            json={"uf": "MS", "city": "", "themes": list(THEME_CATEGORY)},
        )
        resp.raise_for_status()
        layers = {}
        for theme in resp.json():
            names = parse_qs(urlparse(theme["linkWfs"]).query)["typeName"][0].split(",")
            layers[theme["code"]] = [n.split(":", 1)[-1] for n in names]
        if layers.get("imovel_rural"):
            _layers_cache.update(at=time.time(), layers=layers)
            return layers
    except Exception as e:
        print(f"[CAR-WFS] Lista de camadas via API indisponível ({e}); usando lista fixa", flush=True)
    return _FALLBACK_LAYERS


def find_car_by_coordinate(lat: float, lon: float):
    """Detalhes do imóvel no ponto: {codeProperty, nameCity, idState, haRegisteredArea, ...} ou None."""
    try:
        resp = requests.get(f"{API_URL}/totalizer/getDetailsByCoordinates",
                            params={"lat": lat, "lng": lon}, headers=HEADERS, timeout=TIMEOUT)
        if resp.ok and resp.text.strip():
            data = resp.json()
            return data if data.get("codeProperty") else None
    except Exception as e:
        print(f"[CAR-WFS] Consulta por coordenada falhou: {e}", flush=True)
    return None


def _get_features(type_name: str, car_code: str) -> list:
    params = {
        "service": "WFS", "version": "2.0.0", "request": "GetFeature",
        "typeNames": f"consulta_publica:{type_name}", "outputFormat": "application/json",
        "srsName": "EPSG:4674", "cql_filter": f"cod_imovel='{car_code}'",
    }
    for attempt in (1, 2):
        try:
            resp = requests.get(WFS_URL, params=params, headers=HEADERS, timeout=TIMEOUT)
            resp.raise_for_status()
            return resp.json().get("features", [])
        except Exception:
            if attempt == 2:
                raise
            time.sleep(1)


def fetch_car_layers(car_code: str) -> dict:
    """{tema: {typeName: [features]}} só com as camadas que têm feições do imóvel."""
    car_code = car_code.strip().upper()
    jobs = [(theme, tn) for theme, names in get_theme_layers().items() for tn in names]
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda j: (j[0], j[1], _get_features(j[1], car_code)), jobs))
    layers = {}
    for theme, tn, feats in results:
        if feats:
            layers.setdefault(theme, {})[tn] = feats
    n = sum(len(v) for v in layers.values())
    print(f"[CAR-WFS] {car_code}: {n} camadas com dados de {len(jobs)} consultadas ({time.time()-t0:.1f}s)", flush=True)
    return layers


def layers_to_gdfs(layers: dict, car_code: str) -> dict:
    """Converte para o formato de process_car_zip: {'imovel': gdf, 'reserva': gdf, ...} em EPSG:4326."""
    import geopandas as gpd
    import pandas as pd

    gdfs = {}
    for theme, by_layer in layers.items():
        cat = THEME_CATEGORY.get(theme, f"extra_{theme}")
        frames = []
        for tn, feats in by_layer.items():
            gdf = gpd.GeoDataFrame.from_features(feats, crs="EPSG:4674")
            gdf["camada"] = tn
            frames.append(gdf)
        gdf = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs="EPSG:4674").to_crs(epsg=4326)
        # Algumas geometrias do WFS têm defeitos topológicos (auto-interseção) que
        # quebram o cálculo de áreas do mapa — make_valid corrige sem mudar a forma.
        gdf["geometry"] = gdf.geometry.make_valid()
        # Colunas que generate_pro_car_map lê (padrão do shapefile do SICAR)
        gdf["COD_IMOVEL"] = car_code
        gdf["COD_IMOVEL_MAP"] = car_code
        gdfs[cat] = gdf
    return gdfs


def build_car_zip(layers: dict, car_code: str) -> bytes:
    """ZIP com um shapefile por camada (pastas por tema) + LEIA-ME com a procedência."""
    import geopandas as gpd

    buf = io.BytesIO()
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for theme, by_layer in layers.items():
            for tn, feats in by_layer.items():
                gdf = gpd.GeoDataFrame.from_features(feats, crs="EPSG:4674")
                # shapefile não aceita listas/dicts nem nomes de coluna > 10 caracteres
                for col in gdf.columns:
                    if col != "geometry" and gdf[col].map(lambda v: isinstance(v, (list, dict))).any():
                        gdf[col] = gdf[col].map(lambda v: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v)
                base = os.path.join(tmp, theme)
                os.makedirs(base, exist_ok=True)
                path = os.path.join(base, f"{tn}.shp")
                gdf.to_file(path, encoding="utf-8")
                for f in os.listdir(base):
                    if f.startswith(tn + "."):
                        zf.write(os.path.join(base, f), arcname=f"{theme}/{f}")
        zf.writestr("LEIA-ME.txt", (
            f"Camadas do CAR do imóvel {car_code}\n"
            f"Fonte: Consulta Pública do CAR (consulta.car.gov.br) — serviço WFS consulta_publica\n"
            f"Sistema de referência: SIRGAS 2000 (EPSG:4674)\n"
            f"Gerado em: {time.strftime('%d/%m/%Y %H:%M UTC', time.gmtime())}\n"
        ))
    return buf.getvalue()


def get_car_package(car_code: str, property_name: str = None):
    """(gdfs, zip_bytes, erro) — erro preenchido se o imóvel não for encontrado."""
    car_code = car_code.strip().upper()
    layers = fetch_car_layers(car_code)
    if "imovel_rural" not in layers:
        return None, None, "Imóvel não encontrado na base pública do CAR (verifique o código)."
    gdfs = layers_to_gdfs(layers, car_code)
    if property_name:
        gdfs["imovel"]["NOM_IMOVEL"] = property_name
    return gdfs, build_car_zip(layers, car_code), None


# ── Mapa ambiental pronto para o bot (Telegram e WhatsApp) ────────────────────

def resolve_car_code(lat: float, lon: float):
    """Código CAR no ponto: base do GEE (mesma do NDVI/PRODES) e, se não achar, API da Consulta Pública."""
    try:
        from app.gee_connector import find_car_at_coordinate_gee
        prop = find_car_at_coordinate_gee(lat, lon)
        if prop and prop.get("cod_imovel"):
            return prop["cod_imovel"]
    except Exception as e:
        print(f"[CAR-WFS] GEE indisponível para achar o CAR: {e}", flush=True)
    found = find_car_by_coordinate(lat, lon)
    return found["codeProperty"] if found else None


def build_car_map(car_code: str, property_name: str = None):
    """
    (map_png_bytes, zip_bytes, erro). Camadas oficiais do imóvel + fundo de
    satélite (GEE) + generate_pro_car_map. Sem fundo de satélite o mapa sai igual.
    """
    import json as _json
    from app.charts import generate_pro_car_map

    gdfs, zip_bytes, error = get_car_package(car_code, property_name)
    if error:
        return None, None, error

    bg_bytes = bg_extent = reg_bg_bytes = reg_bg_extent = None
    try:
        from app.gee_connector import get_satellite_thumbnail
        geom = _json.loads(gdfs["imovel"].dissolve().to_json())["features"][0]["geometry"]
    except Exception as e:
        print(f"[CAR-WFS] Geometria para satélite indisponível: {e}", flush=True)
        geom = None

    def _fetch_thumb(dimensions, padding_m):
        # Uma tentativa por imagem: o mosaico regional pode levar >30 s para
        # renderizar no GEE e não deve derrubar a imagem principal junto.
        try:
            thumb = get_satellite_thumbnail(geom, dimensions, padding_m, return_bounds=True)
            if thumb:
                resp = requests.get(thumb[0], timeout=120)
                if resp.ok:
                    return resp.content, thumb[1]
        except Exception as e:
            print(f"[CAR-WFS] Satélite (padding {padding_m} m) indisponível: {e}", flush=True)
        return None, None

    if geom:
        bg_bytes, bg_extent = _fetch_thumb(1024, 1500)
        reg_bg_bytes, reg_bg_extent = _fetch_thumb(800, 10000)

    map_out = generate_pro_car_map(gdfs, bg_bytes, bg_extent, reg_bg_bytes, reg_bg_extent)
    map_bytes = map_out.getvalue() if hasattr(map_out, "getvalue") else map_out
    return map_bytes, zip_bytes, None


def car_map_caption(car_code: str, property_name: str = None) -> str:
    name = f"*{property_name}*\n" if property_name else ""
    return (
        f"🗺️ *Mapa ambiental do imóvel*\n{name}"
        f"📍 CAR `{car_code}`\n\n"
        "Camadas oficiais da Consulta Pública do CAR: perímetro, APP, reserva legal, "
        "vegetação nativa, área consolidada e hidrografia."
    )
