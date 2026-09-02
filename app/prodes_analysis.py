"""
Lógica de negócio da ferramenta PRODES: seleção de sensor/cena por data,
leitura de nuvem/cobertura sobre o polígono, regra de "antes"/"depois",
composição em cor natural, cruzamento espacial com a base PRODES e área
geodésica. Ver prompt_ferramenta_prodes_bot.md (raiz do repo) para as regras
de negócio completas — este módulo é a implementação delas.

Deliberadamente não importa de app/environmental.py nem app/gee_connector.py
(além de initialize_gee/find_car_at_coordinate_gee) para não acoplar a
ferramenta jurídica ao módulo de NDVI, que pode mudar por outros motivos.
"""
from __future__ import annotations

import ee
import requests
import time
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta

from app.gee_connector import initialize_gee, find_car_at_coordinate_gee

LEGAL_CONSOLIDATION_MARK = date(2008, 7, 22)  # Lei 12.651/2012, art. 3º, IV

REFLECTANCE_MIN = 0.0
REFLECTANCE_MAX = 0.35
REFLECTANCE_GAMMA = 0.85

MAX_CANDIDATES_PER_COLLECTION = 15  # cota prática de reduceRegion por coleção

# Tabela de coleções, em ordem de preferência (Landsat 7 fica de fora — é
# sempre último recurso, tratado à parte). 'end=None' = ainda vigente.
_COLLECTIONS = [
    {'id': 'COPERNICUS/S2_SR_HARMONIZED', 'start': date(2017, 3, 28), 'end': None,
     'resolution_m': 10, 'label': 'Sentinel-2'},
    {'id': 'LANDSAT/LC09/C02/T1_L2', 'start': date(2021, 10, 31), 'end': None,
     'resolution_m': 30, 'label': 'Landsat 9'},
    {'id': 'LANDSAT/LC08/C02/T1_L2', 'start': date(2013, 4, 11), 'end': None,
     'resolution_m': 30, 'label': 'Landsat 8'},
    {'id': 'LANDSAT/LT05/C02/T1_L2', 'start': date(1984, 3, 1), 'end': date(2012, 5, 5),
     'resolution_m': 30, 'label': 'Landsat 5'},
]

_LANDSAT_LE07 = {
    'id': 'LANDSAT/LE07/C02/T1_L2', 'start': date(1999, 4, 15), 'end': date(2024, 4, 6),
    'resolution_m': 30, 'label': 'Landsat 7 (SLC-off)', 'slc_off_since': date(2003, 5, 31),
}

_BAND_MAPS = {
    'LANDSAT/LT05/C02/T1_L2': {'bands': ['SR_B3', 'SR_B2', 'SR_B1'], 'scale_type': 'landsat_c2'},
    'LANDSAT/LE07/C02/T1_L2': {'bands': ['SR_B3', 'SR_B2', 'SR_B1'], 'scale_type': 'landsat_c2'},
    'LANDSAT/LC08/C02/T1_L2': {'bands': ['SR_B4', 'SR_B3', 'SR_B2'], 'scale_type': 'landsat_c2'},
    'LANDSAT/LC09/C02/T1_L2': {'bands': ['SR_B4', 'SR_B3', 'SR_B2'], 'scale_type': 'landsat_c2'},
    'COPERNICUS/S2_SR_HARMONIZED': {'bands': ['B4', 'B3', 'B2'], 'scale_type': 's2'},
}


# ── Seleção de sensor por data ───────────────────────────────────────────────

def _date_in_window(d: date, row: dict) -> bool:
    if d < row['start']:
        return False
    if row['end'] is not None and d > row['end']:
        return False
    return True


def select_collection_for_date(target_date: date) -> str | None:
    """
    Coleção preferencial para uma data específica (função pura, sem chamada ao GEE):
    Sentinel-2 a partir de 28/03/2017 > Landsat 9 > Landsat 8 (a partir de abr/2013)
    > Landsat 5 (até mai/2012). Landsat 7 só entra se nenhuma outra cobrir a data
    (na prática, o intervalo nov/2011-abr/2013).
    """
    for row in _COLLECTIONS:
        if _date_in_window(target_date, row):
            return row['id']
    if _date_in_window(target_date, _LANDSAT_LE07):
        return _LANDSAT_LE07['id']
    return None


def select_collections_for_window(search_start: date, search_end: date) -> list:
    """Coleções (em ordem de preferência) cuja disponibilidade cruza [search_start, search_end]."""
    ordered = []
    for row in _COLLECTIONS:
        row_end = row['end'] or date(2100, 1, 1)
        if row['start'] <= search_end and row_end >= search_start:
            ordered.append(row['id'])
    le07_end = _LANDSAT_LE07['end']
    if _LANDSAT_LE07['start'] <= search_end and le07_end >= search_start:
        ordered.append(_LANDSAT_LE07['id'])
    return ordered


def is_slc_off_collection(collection_id: str) -> bool:
    return collection_id == _LANDSAT_LE07['id']


# ── Nuvem e cobertura sobre o polígono (funções puras, sem `ee`) ────────────

def decode_qa_pixel_histogram(hist: dict) -> tuple:
    """
    Landsat C2 L2, banda QA_PIXEL. bit0=fill, bit1=nuvem dilatada, bit3=nuvem,
    bit4=sombra. Recebe um histograma {valor: contagem} já materializado (ex.:
    saída de reduceRegion com frequencyHistogram) — não toca `ee`, por design,
    para ser testável sem mock de GEE.
    Retorna (cloud_pct, coverage_pct), ambos 0-100.
    """
    if not hist:
        return (100.0, 0.0)
    total = sum(hist.values())
    if total == 0:
        return (100.0, 0.0)
    fill_count = 0
    cloud_count = 0
    valid_count = 0
    for key, count in hist.items():
        value = int(float(key))
        if value & (1 << 0):  # bit0: fill
            fill_count += count
            continue
        valid_count += count
        is_cloud = bool(value & (1 << 1)) or bool(value & (1 << 3)) or bool(value & (1 << 4))
        if is_cloud:
            cloud_count += count
    coverage_pct = (valid_count / total) * 100.0
    cloud_pct = (cloud_count / valid_count * 100.0) if valid_count > 0 else 100.0
    return (cloud_pct, coverage_pct)


def decode_scl_histogram(hist: dict) -> tuple:
    """
    Sentinel-2, banda SCL. 0=sem dado, 3=sombra, 8/9=nuvem média/alta, 10=cirrus.
    Mesma ideia de decode_qa_pixel_histogram: função pura, testável sem `ee`.
    """
    if not hist:
        return (100.0, 0.0)
    total = sum(hist.values())
    if total == 0:
        return (100.0, 0.0)
    NODATA_CLASSES = {0}
    CLOUD_CLASSES = {3, 8, 9, 10}
    fill_count = 0
    cloud_count = 0
    for key, count in hist.items():
        value = int(float(key))
        if value in NODATA_CLASSES:
            fill_count += count
        elif value in CLOUD_CLASSES:
            cloud_count += count
    valid_count = total - fill_count
    coverage_pct = (valid_count / total) * 100.0
    cloud_pct = (cloud_count / valid_count * 100.0) if valid_count > 0 else 100.0
    return (cloud_pct, coverage_pct)


# ── Reflectância e visualização ──────────────────────────────────────────────

def reflectance_visualize_params(collection_id: str) -> dict:
    """Bandas RGB e tipo de escala de reflectância por coleção, mais o realce fixo da spec."""
    cfg = _BAND_MAPS.get(collection_id)
    if not cfg:
        raise ValueError(f"Coleção não mapeada para visualização: {collection_id}")
    return {
        'bands': cfg['bands'],
        'scale_type': cfg['scale_type'],
        'min': REFLECTANCE_MIN,
        'max': REFLECTANCE_MAX,
        'gamma': REFLECTANCE_GAMMA,
    }


def _to_reflectance_image(image, collection_id: str):
    """Converte a imagem crua (DN) em reflectância de superfície, pronta para visualize()."""
    params = reflectance_visualize_params(collection_id)
    selected = image.select(params['bands'])
    if params['scale_type'] == 'landsat_c2':
        return selected.multiply(0.0000275).add(-0.2)
    return selected.divide(10000)  # Sentinel-2 S2_SR_HARMONIZED


# ── Avaliação de cenas candidatas (chama o GEE) ──────────────────────────────

def score_candidate_scene(image, geom, collection_id: str) -> dict:
    """
    Calcula nuvem/cobertura de UMA cena candidata sobre a geometria do imóvel,
    via reduceRegion (não pela cena inteira). Única função desta seção que
    efetivamente chama `.getInfo()` no GEE — a aritmética fica nas funções
    decode_*_histogram acima, para manter isso testável.
    """
    props = image.toDictionary(['system:index', 'system:time_start']).getInfo()
    system_index = props.get('system:index')
    ts = props.get('system:time_start')
    scene_date = datetime.utcfromtimestamp(ts / 1000).date() if ts else None

    is_s2 = collection_id.startswith('COPERNICUS/S2')
    band = 'SCL' if is_s2 else 'QA_PIXEL'
    scale = 20 if is_s2 else 30

    hist = (
        image.select(band)
        .reduceRegion(
            reducer=ee.Reducer.frequencyHistogram(),
            geometry=geom, scale=scale, maxPixels=1e9, bestEffort=True,
        )
        .get(band)
        .getInfo()
    )
    if is_s2:
        cloud_pct, coverage_pct = decode_scl_histogram(hist or {})
    else:
        cloud_pct, coverage_pct = decode_qa_pixel_histogram(hist or {})

    return {
        'system_index': system_index,
        'date': scene_date,
        'cloud_pct': cloud_pct,
        'coverage_pct': coverage_pct,
        'collection_id': collection_id,
    }


def _dry_season_score(d: date) -> int:
    return 1 if d and 6 <= d.month <= 9 else 0


def _is_better_candidate(a: dict, b: dict, prefer_dry_season: bool) -> bool:
    if a['cloud_pct'] != b['cloud_pct']:
        return a['cloud_pct'] < b['cloud_pct']
    if prefer_dry_season:
        return _dry_season_score(a['date']) > _dry_season_score(b['date'])
    return False


def find_best_scene(geometry_geojson: dict, search_start: date, search_end: date,
                     prefer_dry_season: bool = True) -> dict | None:
    """
    Melhor cena aprovada dentro de [search_start, search_end], nesta ordem de
    critério: cobertura >=99% do imóvel > nuvem <=5% (senão a melhor até 25%,
    marcada) > empate por estiagem regional (jun-set). Tenta as coleções em
    ordem de preferência; se a coleção preferencial já rende uma cena limpa
    (<=5% nuvem), não desce para a próxima.
    """
    if not initialize_gee():
        raise RuntimeError("Falha ao inicializar o Google Earth Engine.")

    geom = ee.Geometry(geometry_geojson)
    collections = select_collections_for_window(search_start, search_end)

    best_clean = None     # cloud_pct <= 5%
    best_relaxed = None   # 5% < cloud_pct <= 25%

    for collection_id in collections:
        ic = (
            ee.ImageCollection(collection_id)
            .filterBounds(geom)
            .filterDate(search_start.isoformat(), (search_end + timedelta(days=1)).isoformat())
        )
        try:
            index_list = ic.aggregate_array('system:index').getInfo()
        except Exception as e:
            print(f"[PRODES] Falha ao listar cenas de {collection_id}: {e}", flush=True)
            continue
        if not index_list:
            continue

        for system_index in index_list[:MAX_CANDIDATES_PER_COLLECTION]:
            try:
                image = ee.Image(f"{collection_id}/{system_index}")
                candidate = score_candidate_scene(image, geom, collection_id)
            except Exception as e:
                print(f"[PRODES] Falha ao avaliar {collection_id}/{system_index}: {e}", flush=True)
                continue

            if candidate['coverage_pct'] < 99.0:
                continue  # descarta cena de órbita/ponto vizinho

            if candidate['cloud_pct'] <= 5.0:
                if best_clean is None or _is_better_candidate(candidate, best_clean, prefer_dry_season):
                    best_clean = candidate
            elif candidate['cloud_pct'] <= 25.0:
                if best_relaxed is None or _is_better_candidate(candidate, best_relaxed, prefer_dry_season):
                    best_relaxed = candidate

        if best_clean is not None:
            break  # coleção preferencial já rendeu cena limpa

    chosen = best_clean or best_relaxed
    if chosen is not None:
        chosen = dict(chosen)
        chosen['high_cloud_warning'] = best_clean is None

    return chosen


def select_before_after_scenes(geometry_geojson: dict, apontamento: dict,
                                forced_before: date | None = None,
                                forced_after: date | None = None) -> dict:
    """
    Regra "antes"/"depois": antes = melhor cena aprovada anterior a
    (image_date - 12 meses), buscando 12 meses pra trás a partir daí; depois =
    melhor cena aprovada posterior a image_date, buscando 12 meses pra frente.
    Aceita override manual de qualquer uma das duas datas.
    """
    image_date = apontamento['image_date']
    warnings = []

    if forced_before:
        before_start = before_end = forced_before
        warnings.append(f"Data 'antes' escolhida manualmente: {forced_before.isoformat()}.")
    else:
        before_end = image_date - relativedelta(months=12)
        before_start = before_end - relativedelta(months=12)

    if forced_after:
        after_start = after_end = forced_after
        warnings.append(f"Data 'depois' escolhida manualmente: {forced_after.isoformat()}.")
    else:
        after_start = image_date
        after_end = after_start + relativedelta(months=12)

    scene_before = find_best_scene(geometry_geojson, before_start, before_end)
    scene_after = find_best_scene(geometry_geojson, after_start, after_end)

    for label, scene in (('antes', scene_before), ('depois', scene_after)):
        if scene and is_slc_off_collection(scene.get('collection_id')):
            warnings.append(
                f"Cena '{label}': Landsat 7 ETM+ em modo SLC-off; as faixas sem dado são "
                "falha conhecida do sensor desde 2003, não ausência de imagem."
            )
        if scene and scene.get('high_cloud_warning'):
            warnings.append(
                f"Cena '{label}': nenhuma candidata com nuvem <=5% sobre o imóvel; usada a "
                f"melhor disponível ({scene['cloud_pct']:.1f}% de nuvem medida)."
            )

    if scene_before and scene_before.get('date') and scene_before['date'] < LEGAL_CONSOLIDATION_MARK:
        warnings.append(
            f"A cena 'antes' ({scene_before['date'].isoformat()}) é anterior a 22/07/2008 — "
            "marco temporal de área rural consolidada da Lei 12.651/2012, art. 3º, IV. "
            "Fato objetivo, sem conclusão jurídica."
        )

    return {'scene_before': scene_before, 'scene_after': scene_after, 'warnings': warnings}


def render_scene_visualization(scene_meta: dict, property_geometry_geojson: dict,
                                dimensions: int = 1600) -> bytes:
    """
    Gera o PNG (bytes) da cena em cor natural, recortada no perímetro do
    imóvel com fundo branco fora dele. Realce fixo (reflectância 0-0.35,
    gamma 0.85), idêntico em qualquer data — nunca por percentil.
    """
    if not initialize_gee():
        raise RuntimeError("Falha ao inicializar o Google Earth Engine.")

    collection_id = scene_meta['collection_id']
    system_index = scene_meta['system_index']
    image = ee.Image(f"{collection_id}/{system_index}")

    refl = _to_reflectance_image(image, collection_id)
    params = reflectance_visualize_params(collection_id)
    visualized = refl.visualize(min=params['min'], max=params['max'], gamma=params['gamma'])

    property_geom = ee.Geometry(property_geometry_geojson)
    region = property_geom.bounds()

    white_bg = ee.Image.constant([255, 255, 255]).rename(visualized.bandNames())
    composed = white_bg.blend(visualized.clip(property_geom))

    url = composed.getThumbURL({'region': region.getInfo(), 'dimensions': dimensions, 'format': 'png'})
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    return resp.content


# ── Cruzamento espacial com a base PRODES (consulta AO VIVO via WFS) ────────
#
# Não há cópia local dos apontamentos (nem Postgres, nem asset GEE) — cada
# /prodes consulta o WFS oficial do TerraBrasilis/INPE na hora, sempre com a
# base mais atual. Testado manualmente: WFS 1.1.0, outputFormat=GeoJSON,
# bbox em EPSG:4674 (mesma ordem lon,lat do resto do projeto), resposta em
# ~0.2s para um bbox do tamanho de um imóvel rural.

PRODES_WFS_URL = 'https://terrabrasilis.dpi.inpe.br/geoserver/ows'
# Um imóvel pode estar em qualquer um dos 6 biomas (ou atravessar mais de
# um) — consulta todas as camadas "novo bioma" (harmonizadas, mesmo schema)
# em paralelo, não só uma. O nome do tipo da Amazônia é o único que difere
# (yearly_deforestation_biome, em vez de yearly_deforestation).
PRODES_WFS_LAYERS = {
    'Amazônia': 'prodes-amazon-nb:yearly_deforestation_biome',
    'Caatinga': 'prodes-caatinga-nb:yearly_deforestation',
    'Cerrado': 'prodes-cerrado-nb:yearly_deforestation',
    'Mata Atlântica': 'prodes-mata-atlantica-nb:yearly_deforestation',
    'Pampa': 'prodes-pampa-nb:yearly_deforestation',
    'Pantanal': 'prodes-pantanal-nb:yearly_deforestation',
}
PRODES_SOURCE_LABEL = 'TerraBrasilis/INPE (WFS, camadas de todos os biomas: ' + ', '.join(PRODES_WFS_LAYERS) + ')'
PRODES_WFS_BBOX_PAD_DEG = 0.001  # ~100m de margem de segurança pro filtro por bbox
PRODES_WFS_MAX_RETRIES = 3
PRODES_WFS_RETRY_BACKOFF_SECONDS = 3  # multiplicado pelo nº da tentativa (3s, 6s)


def _parse_flexible_date(value):
    """Datas do WFS chegam como string 'YYYY-MM-DD'; aceita outros formatos defensivamente."""
    if value is None or value == '':
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.utcfromtimestamp(value / 1000).date()
        except (ValueError, OSError, OverflowError):
            return None
    text_value = str(value).strip()
    for fmt in ('%Y-%m-%d', '%Y%m%d', '%d/%m/%Y'):
        try:
            return datetime.strptime(text_value[:10], fmt).date()
        except ValueError:
            continue
    return None


def _query_wfs_layer(typename: str, bbox: str) -> dict:
    """Uma consulta ao WFS, com retry — devolve o GeoJSON bruto ou levanta RuntimeError."""
    params = {
        'service': 'WFS', 'version': '1.1.0', 'request': 'GetFeature',
        'typeName': typename, 'outputFormat': 'application/json', 'bbox': bbox,
    }
    last_error = None
    for attempt in range(1, PRODES_WFS_MAX_RETRIES + 1):
        try:
            # (connect_timeout, read_timeout) — connect curto pra falhar rápido se o
            # servidor estiver inalcançável, read maior pra dar tempo de montar a resposta.
            resp = requests.get(PRODES_WFS_URL, params=params, timeout=(10, 25))
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            last_error = e
            print(f"[PRODES] WFS falhou em {typename} (tentativa {attempt}/{PRODES_WFS_MAX_RETRIES}): {e}", flush=True)
            if attempt < PRODES_WFS_MAX_RETRIES:
                time.sleep(PRODES_WFS_RETRY_BACKOFF_SECONDS * attempt)
    raise RuntimeError(f"{typename}: {last_error}")


def find_intersecting_apontamentos(geometry_geojson: dict) -> list:
    """
    Apontamentos do PRODES/INPE que INTERSECTAM (não apenas contêm) o
    perímetro, consultados AO VIVO via WFS do TerraBrasilis — sem cópia
    local. Consulta as camadas de TODOS os biomas em paralelo (um imóvel
    pode estar em qualquer um, ou atravessar mais de um — não dá pra supor
    o bioma pela UF), filtra por bbox no servidor e faz a interseção exata
    em Python (shapely), já que o filtro por bbox pode incluir falsos
    positivos que só tocam a caixa delimitadora, não o polígono de fato.
    """
    import concurrent.futures
    from shapely.geometry import shape, mapping

    def _make_valid(geom):
        """Geometria de fonte governamental frequentemente vem com autointerseções
        leves (side location conflict no GEOS) — buffer(0) é o saneamento padrão."""
        if geom is not None and not geom.is_valid:
            geom = geom.buffer(0)
        return geom

    property_shape = _make_valid(shape(geometry_geojson))
    minx, miny, maxx, maxy = property_shape.bounds
    pad = PRODES_WFS_BBOX_PAD_DEG
    bbox = f"{minx - pad},{miny - pad},{maxx + pad},{maxy + pad},EPSG:4674"

    results_by_biome = {}
    errors = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(PRODES_WFS_LAYERS)) as executor:
        future_to_biome = {
            executor.submit(_query_wfs_layer, typename, bbox): biome
            for biome, typename in PRODES_WFS_LAYERS.items()
        }
        for future in concurrent.futures.as_completed(future_to_biome):
            biome = future_to_biome[future]
            try:
                results_by_biome[biome] = future.result()
            except Exception as e:
                errors.append(str(e))

    if not results_by_biome:
        raise RuntimeError(f"Falha ao consultar o WFS do TerraBrasilis/INPE em todos os biomas: {'; '.join(errors)}")
    if errors:
        print(f"[PRODES] Aviso: falha ao consultar {len(errors)}/{len(PRODES_WFS_LAYERS)} biomas "
              f"(seguindo com os demais): {'; '.join(errors)}", flush=True)

    apontamentos = []
    for biome, data in results_by_biome.items():
        for feat in data.get('features', []):
            geom = feat.get('geometry')
            if not geom:
                continue
            apon_shape = _make_valid(shape(geom))
            if apon_shape is None or apon_shape.is_empty or not apon_shape.intersects(property_shape):
                continue  # falso positivo do filtro por bbox (ou geometria irrecuperável)

            props = feat.get('properties', {})
            try:
                intersection = apon_shape.intersection(property_shape)
            except Exception as e:
                print(f"[PRODES] Falha ao calcular interseção do apontamento "
                      f"{props.get('uuid')}: {e} — pulando.", flush=True)
                continue
            # Usa a geometria já saneada (apon_shape), não o GeoJSON bruto, pra
            # área total bater com a mesma geometria usada na interseção.
            area_total_ha = geodesic_area_ha(mapping(apon_shape))
            area_intersect_ha = geodesic_area_ha(mapping(intersection)) if not intersection.is_empty else 0.0

            apontamentos.append({
                'uuid': props.get('uuid'),
                'class_name': props.get('class_name'),
                'main_class': props.get('main_class'),
                'year': int(props['year']) if props.get('year') not in (None, '') else None,
                'image_date': _parse_flexible_date(props.get('image_date')),
                'satellite': props.get('satellite'),
                'sensor': props.get('sensor'),
                'path_row': props.get('path_row'),
                'state': props.get('state'),
                'source': props.get('source'),
                'area_km_inpe': float(props['area_km']) if props.get('area_km') not in (None, '') else None,
                'area_total_ha': area_total_ha,
                'area_intersect_ha': area_intersect_ha,
                'geometry': geom,
                'biome': biome,
            })

    apontamentos.sort(key=lambda a: (-(a['year'] or 0), -(a['area_intersect_ha'] or 0)))
    return apontamentos


def geodesic_area_ha(geometry_geojson: dict) -> float:
    """Área geodésica sobre o elipsoide GRS80 (SIRGAS2000), em hectares."""
    from pyproj import Geod
    from shapely.geometry import shape
    geod = Geod(ellps="GRS80")
    geom = shape(geometry_geojson)
    area_m2, _ = geod.geometry_area_perimeter(geom)
    return abs(area_m2) / 10000.0


def fetch_car_perimeter_full(lat: float, lon: float) -> dict:
    """
    Como fetch_car_perimeter (app/environmental.py), mas devolve o dict
    completo do CAR (município/UF/área), sem alterar a assinatura usada por
    /ambiental. A ferramenta PRODES exige status 'OFFICIAL' — sem fallback de
    área estimada, que não tem valor probatório.
    """
    prop = find_car_at_coordinate_gee(lat, lon)
    if not prop or not prop.get('cod_imovel'):
        return {
            'status': 'FALLBACK', 'geometry': None, 'cod_imovel': None,
            'municipio': None, 'uf': None, 'area_ha': None,
        }
    return {
        'status': 'OFFICIAL',
        'geometry': prop.get('geometry'),
        'cod_imovel': prop.get('cod_imovel'),
        'municipio': prop.get('municipio'),
        'uf': prop.get('uf'),
        'area_ha': prop.get('area'),
    }


def build_footer_notes(scenes_result: dict, source_info: dict) -> list:
    """
    Única fonte das notas de rodapé (mapas e PDF chamam esta função, para
    nunca divergir no texto legal/técnico). source_info: {'label', 'queried_at'}.
    """
    notes = list(scenes_result.get('warnings', []))
    label = (source_info or {}).get('label') or PRODES_SOURCE_LABEL
    queried_at = (source_info or {}).get('queried_at')
    queried_str = queried_at.strftime('%d/%m/%Y %H:%M UTC') if queried_at else 'data não registrada'
    notes.append(f"Base PRODES/INPE: {label}, consultada ao vivo em {queried_str}.")
    notes.append(
        "Trabalho realizado em EPSG:4674 (SIRGAS 2000). O Google Earth Engine opera em "
        "WGS 84; a diferença é submétrica e irrelevante para esta análise."
    )
    return notes
