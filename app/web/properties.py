"""
Propriedades da plataforma web — mesma tabela do bot (favorite_locations).

- cadastro por código CAR, por coordenada ou clicando no mapa (acha o CAR no ponto);
- sincroniza o perímetro e as camadas oficiais do CAR (WFS da Consulta Pública,
  app/car_wfs.py) para o PostGIS: favorite_locations.perimeter + property_car_features;
- quadro de áreas, área sem classificação, ZIP e mapa PNG reaproveitam o mesmo
  código do bot, então web e bot mostram sempre os mesmos números.
"""
import json
from datetime import datetime

from sqlalchemy import text

from app.models import SessionLocal, FavoriteLocation, PropertyCarFeature

CATEGORY_LABELS = {
    "imovel": "Perímetro do imóvel",
    "consolidada": "Área antropizada (consolidada)",
    "vegetacao": "Remanescente nativo",
    "reserva": "Reserva Legal",
    "app": "A.P.P.",
    "uso_restrito": "Uso restrito",
    "agua": "Corpo d'água",
    "extra_servidao": "Servidão administrativa",
    "extra_pousio": "Área de pousio",
    "sem_classificacao": "Sem classificação no CAR",
}


class PropertyError(Exception):
    """Erro com mensagem para o usuário (vira HTTP 4xx na API)."""


def lookup_car_at(lat: float, lon: float) -> list:
    """Imóveis do CAR que contêm o ponto (vários se houver sobreposição) — para o usuário escolher."""
    from app.car_wfs import find_cars_at_point
    return find_cars_at_point(lat, lon)


def sync_car(property_id: int, car_code: str) -> dict:
    """Baixa perímetro + camadas do CAR e grava no PostGIS. Devolve o resumo da propriedade."""
    from app.car_wfs import fetch_car_layers, THEME_CATEGORY

    car_code = car_code.strip().upper()
    layers = fetch_car_layers(car_code)
    if "imovel_rural" not in layers:
        raise PropertyError("Imóvel não encontrado na base pública do CAR. Confira o código.")

    perimeter_feats = [f for feats in layers["imovel_rural"].values() for f in feats]
    first_attrs = (perimeter_feats[0].get("properties") or {}) if perimeter_feats else {}

    db = SessionLocal()
    try:
        db.query(PropertyCarFeature).filter_by(property_id=property_id).delete()
        for theme, by_layer in layers.items():
            category = THEME_CATEGORY.get(theme, f"extra_{theme}")
            for layer_name, feats in by_layer.items():
                for f in feats:
                    db.execute(text(
                        "INSERT INTO property_car_features (property_id, category, layer, geom, attrs) "
                        "SELECT :pid, :cat, :layer, "
                        # corrige geometrias inválidas sem mudar o tipo: polígono continua (multi)polígono
                        "  CASE WHEN ST_Dimension(raw) = 2 THEN ST_Multi(ST_CollectionExtract(ST_MakeValid(raw), 3)) "
                        "       WHEN ST_Dimension(raw) = 1 THEN ST_Multi(ST_CollectionExtract(ST_MakeValid(raw), 2)) "
                        "       ELSE ST_MakeValid(raw) END, CAST(:attrs AS JSONB) "
                        "FROM (SELECT ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326) AS raw) s"
                    ), {"pid": property_id, "cat": category, "layer": layer_name,
                        "g": json.dumps(f["geometry"]), "attrs": json.dumps(f.get("properties") or {}, ensure_ascii=False)})
        # perímetro = união das feições do imóvel; área geodésica
        db.execute(text("""
            UPDATE favorite_locations SET
              car_code = :code,
              perimeter = (SELECT ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_Union(geom)), 3))
                           FROM property_car_features WHERE property_id = :pid AND category = 'imovel'),
              municipio = :mun, uf = :uf, car_synced_at = :now
            WHERE id = :pid
        """), {"code": car_code, "pid": property_id, "mun": first_attrs.get("municipio"),
               "uf": first_attrs.get("uf") or car_code[:2], "now": datetime.utcnow()})
        db.execute(text("""
            UPDATE favorite_locations SET
              area_ha = ST_Area(perimeter::geography) / 10000,
              latitude = ST_Y(ST_PointOnSurface(perimeter)),
              longitude = ST_X(ST_PointOnSurface(perimeter))
            WHERE id = :pid AND perimeter IS NOT NULL
        """), {"pid": property_id})
        db.commit()
    finally:
        db.close()
    return get_property(property_id)


def create_property(chat_id: str, name: str, car_code: str = None, lat: float = None, lon: float = None,
                    organization_id: int = None) -> dict:
    from app.saas.limit_engine import can_perform_action
    ok, msg = can_perform_action(chat_id, "ADD_PROPERTY")
    if not ok:
        raise PropertyError(msg.replace("Patrão, ", ""))
    if not car_code:
        if lat is None or lon is None:
            raise PropertyError("Informe o código do CAR ou a localização da propriedade.")
        found = lookup_car_at(lat, lon)
        car_code = found[0]["car_code"] if found else None

    db = SessionLocal()
    try:
        loc = FavoriteLocation(user_id=str(chat_id), name=name.strip()[:80], latitude=lat, longitude=lon,
                               organization_id=organization_id)
        db.add(loc)
        db.commit()
        pid = loc.id
    finally:
        db.close()
    if car_code:
        try:
            return sync_car(pid, car_code)
        except PropertyError:
            if lat is None:   # sem coordenada nem CAR válido não há o que guardar
                delete_property(pid)
            raise
    return get_property(pid)


def delete_property(property_id: int):
    db = SessionLocal()
    try:
        db.query(FavoriteLocation).filter_by(id=property_id).delete()
        db.commit()
    finally:
        db.close()


def _row_to_dict(row) -> dict:
    return {
        "id": row.id, "name": row.name, "lat": row.latitude, "lon": row.longitude,
        "car_code": row.car_code, "area_ha": row.area_ha, "municipio": row.municipio, "uf": row.uf,
        "car_synced_at": row.car_synced_at.isoformat() if row.car_synced_at else None,
        "has_perimeter": row.has_perimeter,
    }


def list_properties(chat_id: str) -> list:
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT id, name, latitude, longitude, car_code, area_ha, municipio, uf, car_synced_at,
                   perimeter IS NOT NULL AS has_perimeter
            FROM favorite_locations WHERE user_id = :cid ORDER BY created_at
        """), {"cid": str(chat_id)}).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        db.close()


def list_perimeters(chat_id: str) -> dict:
    """Perímetros (simplificados, ~10 m) de todas as propriedades com CAR — para o mapa geral."""
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT id, name, ST_AsGeoJSON(ST_SimplifyPreserveTopology(perimeter, 0.0001), 6) AS g
            FROM favorite_locations WHERE user_id = :cid AND perimeter IS NOT NULL
        """), {"cid": str(chat_id)}).fetchall()
        return {"type": "FeatureCollection", "features": [
            {"type": "Feature", "id": r.id, "geometry": json.loads(r.g), "properties": {"id": r.id, "name": r.name}}
            for r in rows]}
    finally:
        db.close()


def get_property(property_id: int) -> dict:
    db = SessionLocal()
    try:
        r = db.execute(text("""
            SELECT id, name, latitude, longitude, car_code, area_ha, municipio, uf, car_synced_at,
                   perimeter IS NOT NULL AS has_perimeter,
                   ST_AsGeoJSON(perimeter, 7) AS perimeter_geojson,
                   ST_XMin(perimeter) AS xmin, ST_YMin(perimeter) AS ymin, ST_XMax(perimeter) AS xmax, ST_YMax(perimeter) AS ymax,
                   ndvi_alerts_enabled, rain_alerts_enabled, prodes_alerts_enabled
            FROM favorite_locations WHERE id = :pid
        """), {"pid": property_id}).fetchone()
        if not r:
            raise PropertyError("Propriedade não encontrada.")
        out = _row_to_dict(r)
        out["perimeter"] = json.loads(r.perimeter_geojson) if r.perimeter_geojson else None
        out["bbox"] = [r.xmin, r.ymin, r.xmax, r.ymax] if r.perimeter_geojson else None
        out["alerts"] = {"ndvi": r.ndvi_alerts_enabled is not False, "rain": bool(r.rain_alerts_enabled),
                         "prodes": bool(r.prodes_alerts_enabled)}
        return out
    finally:
        db.close()


def set_alerts(property_id: int, ndvi=None, rain=None, prodes=None) -> dict:
    """Liga/desliga os alertas da propriedade (None = não mexe)."""
    from sqlalchemy.orm.attributes import flag_modified
    db = SessionLocal()
    try:
        loc = db.query(FavoriteLocation).filter_by(id=property_id).first()
        if not loc:
            raise PropertyError("Propriedade não encontrada.")
        if ndvi is not None:
            loc.ndvi_alerts_enabled = ndvi
        if rain is not None:
            loc.rain_alerts_enabled = rain
        if prodes is not None:
            if prodes and loc.perimeter is None:
                raise PropertyError("Vincule o CAR para receber alertas do PRODES.")
            loc.prodes_alerts_enabled = prodes
            state = dict(loc.alert_state or {})
            if prodes and state.get("prodes_uuids") is None:
                # base inicial = última consulta feita na página, se houver (só o que surgir depois vira alerta)
                last = db.execute(text("""
                    SELECT ARRAY(SELECT f->'properties'->>'uuid' FROM jsonb_array_elements(result->'features') f) AS uuids
                    FROM property_analyses WHERE property_id = :pid AND kind = 'prodes_list'
                    ORDER BY created_at DESC LIMIT 1
                """), {"pid": property_id}).fetchone()
                if last:
                    state["prodes_uuids"] = [u for u in last.uuids if u]
                    loc.alert_state = state
                    flag_modified(loc, "alert_state")
        db.commit()
    finally:
        db.close()
    return get_property(property_id)["alerts"]


def owner_of(property_id: int):
    db = SessionLocal()
    try:
        loc = db.query(FavoriteLocation.user_id).filter_by(id=property_id).first()
        return loc[0] if loc else None
    finally:
        db.close()


def get_layers(property_id: int) -> dict:
    """FeatureCollection com as camadas do CAR + 'sem classificação' e o quadro de áreas (ha)."""
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT category, layer, ST_AsGeoJSON(geom, 7) AS g, ST_Area(geom::geography) / 10000 AS ha
            FROM property_car_features WHERE property_id = :pid AND category <> 'imovel'
        """), {"pid": property_id}).fetchall()
        features = [{"type": "Feature", "geometry": json.loads(r.g),
                     "properties": {"category": r.category, "layer": r.layer, "area_ha": round(r.ha, 4)}}
                    for r in rows]
        # áreas por categoria (união → feições sobrepostas não somam duas vezes)
        areas = {r.category: r.ha for r in db.execute(text("""
            SELECT category, ST_Area(ST_Union(geom)::geography) / 10000 AS ha
            FROM property_car_features WHERE property_id = :pid GROUP BY category
        """), {"pid": property_id})}
        # área do imóvel não declarada em nenhum tema
        unc = db.execute(text("""
            WITH p AS (SELECT perimeter FROM favorite_locations WHERE id = :pid),
                 c AS (SELECT ST_Union(geom) AS u FROM property_car_features WHERE property_id = :pid AND category <> 'imovel')
            SELECT ST_AsGeoJSON(d, 7) AS g, ST_Area(d::geography) / 10000 AS ha FROM (
              SELECT ST_CollectionExtract(ST_MakeValid(ST_Difference(p.perimeter, COALESCE(c.u, ST_GeomFromText('POLYGON EMPTY', 4326)))), 3) AS d
              FROM p, c) x
        """), {"pid": property_id}).fetchone()
        total = areas.get("imovel") or 0
        if unc and unc.g and unc.ha and total and unc.ha > total * 0.005:
            features.append({"type": "Feature", "geometry": json.loads(unc.g),
                             "properties": {"category": "sem_classificacao", "layer": "sem_classificacao",
                                            "area_ha": round(unc.ha, 4)}})
            areas["sem_classificacao"] = unc.ha
        order = list(CATEGORY_LABELS)
        table = [{"category": k, "label": CATEGORY_LABELS.get(k, k), "area_ha": round(v, 2)}
                 for k, v in sorted(areas.items(), key=lambda kv: order.index(kv[0]) if kv[0] in order else 99)]
        return {"type": "FeatureCollection", "features": features, "areas": table}
    finally:
        db.close()


def build_zip(property_id: int) -> tuple:
    """(bytes, nome) — ZIP com um shapefile por camada, a partir do cache no PostGIS."""
    from app.car_wfs import build_car_zip, THEME_CATEGORY
    prop = get_property(property_id)
    if not prop["car_code"]:
        raise PropertyError("Vincule o CAR desta propriedade primeiro.")
    category_theme = {v: k for k, v in THEME_CATEGORY.items()}
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT category, layer, ST_AsGeoJSON(geom, 8) AS g, attrs
            FROM property_car_features WHERE property_id = :pid
        """), {"pid": property_id}).fetchall()
    finally:
        db.close()
    layers = {}
    for r in rows:
        theme = category_theme.get(r.category, r.category)
        layers.setdefault(theme, {}).setdefault(r.layer, []).append(
            {"type": "Feature", "geometry": json.loads(r.g), "properties": r.attrs or {}})
    return build_car_zip(layers, prop["car_code"]), f"CAR_{prop['car_code']}.zip"


def build_map_png(property_id: int) -> tuple:
    from app.car_wfs import build_car_map
    prop = get_property(property_id)
    if not prop["car_code"]:
        raise PropertyError("Vincule o CAR desta propriedade primeiro.")
    png, _, err = build_car_map(prop["car_code"], prop["name"])
    if err:
        raise PropertyError(err)
    return png, f"Mapa_CAR_{prop['name'].replace(' ', '_')}.png"


def latest_ndvi(chat_id: str, property_id: int) -> dict:
    """NDVI Sentinel-2 mais recente sobre o perímetro: imagem (data URL) + moldura + média."""
    import base64
    from app.environmental import get_ndvi_analysis
    from app.saas.limit_engine import can_perform_action
    from app.models import log_activity

    ok, msg = can_perform_action(chat_id, "LOOKUP")
    if not ok:
        raise PropertyError(msg.replace("Patrão, ", ""))
    prop = get_property(property_id)
    if not prop["perimeter"]:
        raise PropertyError("Vincule o CAR desta propriedade para calcular o NDVI sobre o perímetro.")
    result = get_ndvi_analysis(prop["perimeter"])
    if not result:
        raise PropertyError("Sem imagem de satélite aproveitável (nuvens) nos últimos 90 dias.")
    bb = result["region_bbox"]
    log_activity(chat_id, "NDVI", platform="web", details=prop["name"])
    return {
        "date": result["date_str"], "mean": result["stats"].get("mean"), "cloud_pct": result.get("cloud_coverage"),
        "image": "data:image/png;base64," + base64.b64encode(result["ndvi_img"].getvalue()).decode(),
        "coordinates": [[bb["min_lon"], bb["max_lat"]], [bb["max_lon"], bb["max_lat"]],
                        [bb["max_lon"], bb["min_lat"]], [bb["min_lon"], bb["min_lat"]]],
    }


# ── Histórico de análises (property_analyses + arquivos no GCS) ──────────────

def _save_analysis(property_id: int, chat_id: str, kind: str, params: dict, result: dict,
                   file_bytes: bytes = None, file_type: str = None, ext: str = "bin") -> int:
    from app.models import PropertyAnalysis
    file_path = None
    if file_bytes:
        try:
            from app import prodes_storage
            file_path = f"web/analyses/{property_id}/{kind}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.{ext}"
            prodes_storage.upload_bytes(file_path, file_bytes, file_type)
        except Exception as e:   # sem GCS: guarda a imagem no próprio registro (base64)
            import base64
            print(f"[WEB] GCS indisponível ({e}); arquivo guardado no banco", flush=True)
            file_path = None
            result = {**result, "file_b64": base64.b64encode(file_bytes).decode()}
    db = SessionLocal()
    try:
        row = PropertyAnalysis(property_id=property_id, kind=kind, params=params, result=result,
                               file_path=file_path, file_type=file_type, created_by=str(chat_id))
        db.add(row)
        db.commit()
        return row.id
    finally:
        db.close()


def _cached_analysis(property_id: int, kind: str, params: dict, max_age_hours: float):
    from datetime import timedelta
    from app.models import PropertyAnalysis
    db = SessionLocal()
    try:
        q = (db.query(PropertyAnalysis)
             .filter(PropertyAnalysis.property_id == property_id, PropertyAnalysis.kind == kind,
                     PropertyAnalysis.created_at >= datetime.utcnow() - timedelta(hours=max_age_hours))
             .order_by(PropertyAnalysis.created_at.desc()))
        for row in q.limit(20):
            if (row.params or {}) == params:
                return row
        return None
    finally:
        db.close()


def _analysis_dict(row) -> dict:
    result = dict(row.result or {})
    has_file = bool(row.file_path or result.pop("file_b64", None))
    return {"id": row.id, "kind": row.kind, "params": row.params, "result": result,
            "file_url": f"/api/v1/properties/{row.property_id}/analyses/{row.id}/file" if has_file else None,
            "created_at": row.created_at.isoformat()}


def ndvi_series_for(chat_id: str, property_id: int, months: int = 24) -> dict:
    from app.web.analytics import ndvi_series
    from app.saas.limit_engine import can_perform_action
    from app.models import log_activity
    params = {"months": months}
    cached = _cached_analysis(property_id, "ndvi_series", params, max_age_hours=24 * 7)
    prop = get_property(property_id)
    if cached and (not prop["car_synced_at"] or cached.created_at.isoformat() > prop["car_synced_at"]):
        return _analysis_dict(cached)
    ok, msg = can_perform_action(chat_id, "LOOKUP")
    if not ok:
        raise PropertyError(msg.replace("Patrão, ", ""))
    if not prop["perimeter"]:
        raise PropertyError("Vincule o CAR desta propriedade para calcular o NDVI sobre o perímetro.")
    series = ndvi_series(prop["perimeter"], months)
    log_activity(chat_id, "NDVI", platform="web", details=f"{prop['name']} (série {months} meses)")
    aid = _save_analysis(property_id, chat_id, "ndvi_series", params, {"series": series})
    return _analysis_dict(_get_analysis_row(aid))


POINT_BUFFER_M = 15   # ~7 pixels Sentinel-2 de 10 m: suaviza ruído de um pixel isolado


def _round_coords(c):
    return [_round_coords(x) for x in c] if isinstance(c, list) else round(c, 5)


def ndvi_zone_for(chat_id: str, property_id: int, geometry: dict, months: int = 24) -> dict:
    """
    NDVI mês a mês de uma zona da propriedade — ponto (com buffer) hoje, piquete desenhado no futuro.
    A zona precisa estar dentro do perímetro.
    """
    from shapely.geometry import shape
    from app.web.analytics import ndvi_series
    from app.saas.limit_engine import can_perform_action
    from app.models import log_activity
    gtype = (geometry or {}).get("type")
    if gtype not in ("Point", "Polygon", "MultiPolygon"):
        raise PropertyError("Envie um ponto ou um polígono.")
    geometry = {"type": gtype, "coordinates": _round_coords(geometry.get("coordinates"))}
    prop = get_property(property_id)
    if not prop["perimeter"]:
        raise PropertyError("Vincule o CAR desta propriedade para calcular o NDVI.")
    try:
        zone = shape(geometry)
        perim = shape(prop["perimeter"])
        if not perim.is_valid:
            perim = perim.buffer(0)
    except Exception:
        raise PropertyError("Geometria inválida.")
    if not zone.intersects(perim):
        raise PropertyError("Escolha um ponto dentro do perímetro da propriedade.")
    buffer_m = POINT_BUFFER_M if gtype == "Point" else 0
    params = {"geometry": geometry, "months": months}
    cached = _cached_analysis(property_id, "ndvi_zone", params, max_age_hours=24 * 7)
    if cached:
        return _analysis_dict(cached)
    ok, msg = can_perform_action(chat_id, "LOOKUP")
    if not ok:
        raise PropertyError(msg.replace("Patrão, ", ""))
    series = ndvi_series(geometry, months, scale=10, buffer_m=buffer_m)
    log_activity(chat_id, "NDVI", platform="web", details=f"{prop['name']} (zona {gtype}, {months} meses)")
    aid = _save_analysis(property_id, chat_id, "ndvi_zone", params, {"series": series, "buffer_m": buffer_m})
    return _analysis_dict(_get_analysis_row(aid))


def ndvi_month_for(chat_id: str, property_id: int, month: str) -> dict:
    import re as _re
    from app.web.analytics import ndvi_month_image
    from app.saas.limit_engine import can_perform_action
    if not _re.fullmatch(r"\d{4}-\d{2}", month or ""):
        raise PropertyError("Mês inválido (use AAAA-MM).")
    current = datetime.utcnow().strftime("%Y-%m")
    if month > current:
        raise PropertyError("Escolha um mês que já passou ou o mês atual.")
    params = {"month": month}
    # mês fechado não muda: cache longo; mês corrente: 1 dia
    cached = _cached_analysis(property_id, "ndvi_month", params, max_age_hours=24 if month == current else 24 * 365)
    if cached:
        return _analysis_dict(cached)
    ok, msg = can_perform_action(chat_id, "LOOKUP")
    if not ok:
        raise PropertyError(msg.replace("Patrão, ", ""))
    prop = get_property(property_id)
    if not prop["perimeter"]:
        raise PropertyError("Vincule o CAR desta propriedade para ver o NDVI sobre o perímetro.")
    out = ndvi_month_image(prop["perimeter"], month)
    if not out.get("png"):
        raise PropertyError("Nenhuma imagem de satélite sem nuvens nesse mês.")
    from app.models import log_activity
    log_activity(chat_id, "NDVI", platform="web", details=f"{prop['name']} ({month})")
    aid = _save_analysis(property_id, chat_id, "ndvi_month", params,
                         {"mean": out["mean"], "images": out["images"], "coordinates": out["coordinates"]},
                         out["png"], "image/png", "png")
    return _analysis_dict(_get_analysis_row(aid))


def _get_analysis_row(analysis_id: int):
    from app.models import PropertyAnalysis
    db = SessionLocal()
    try:
        return db.query(PropertyAnalysis).filter_by(id=analysis_id).first()
    finally:
        db.close()


def list_analyses(property_id: int, limit: int = 50) -> list:
    from app.models import PropertyAnalysis
    db = SessionLocal()
    try:
        rows = (db.query(PropertyAnalysis).filter_by(property_id=property_id)
                .order_by(PropertyAnalysis.created_at.desc()).limit(limit).all())
        return [_analysis_dict(r) for r in rows]
    finally:
        db.close()


_HISTORY_HIDDEN = ("prodes_antes", "prodes_depois")   # já vêm junto do laudo


def history_for(property_id: int, limit: int = 100) -> list:
    """Histórico leve da propriedade: só os campos do resumo (sem séries nem arquivos em base64)."""
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT id, kind, created_at, file_type, params,
                   (file_path IS NOT NULL OR result ? 'file_b64') AS has_file,
                   result->>'mean' AS mean, result->>'last30_mm' AS last30, result->>'pct_of_normal' AS pct,
                   result->>'elev_min' AS elev_min, result->>'elev_max' AS elev_max, result->>'date' AS img_date,
                   CASE WHEN jsonb_typeof(result->'values') = 'object' THEN (SELECT count(*) FROM jsonb_object_keys(result->'values')) END AS n_values,
                   CASE WHEN jsonb_typeof(result->'features') = 'array' THEN jsonb_array_length(result->'features') END AS n_features
            FROM property_analyses WHERE property_id = :pid AND kind <> ALL(:hidden)
            ORDER BY created_at DESC LIMIT :lim
        """), {"pid": property_id, "hidden": list(_HISTORY_HIDDEN), "lim": limit}).fetchall()
    finally:
        db.close()

    def num(v, nd=2):
        return f"{float(v):.{nd}f}".replace(".", ",") if v not in (None, "") else "—"

    def label(r):
        p = r.params or {}
        if r.kind == "ndvi_month":
            y, m = p.get("month", "-").split("-")
            return f"NDVI de {m}/{y}", f"média {num(r.mean)}"
        if r.kind == "ndvi_series":
            return f"Histórico de NDVI ({p.get('months', 24)} meses)", None
        if r.kind == "ndvi_zone":
            g = p.get("geometry") or {}
            if g.get("type") == "Point":
                lon, lat = g["coordinates"]
                return "NDVI de um ponto", f"{lat:.5f}, {lon:.5f}"
            return "NDVI de uma área", None
        if r.kind == "rain":
            return "Chuva", f"{num(r.last30, 0)} mm em 30 dias" + (f" · {r.pct}% da média" if r.pct else "")
        if r.kind == "mdt_2d":
            return "Curvas de nível", f"{num(r.elev_min, 0)}–{num(r.elev_max, 0)} m"
        if r.kind == "mdt_3d":
            return "Modelo 3D do terreno", f"{num(r.elev_min, 0)}–{num(r.elev_max, 0)} m"
        if r.kind == "prodes_list":
            return "Consulta PRODES", f"{r.n_features or 0} apontamento(s)"
        if r.kind == "paddock_ndvi":
            if p.get("month") == "latest":
                d = (r.img_date or "").split("-")
                return "NDVI dos piquetes", f"imagem de {d[2]}/{d[1]}/{d[0]} · {r.n_values or 0} piquetes" if len(d) == 3 else None
            y, m = p.get("month", "-").split("-")
            return "NDVI dos piquetes", f"{m}/{y} · {r.n_values or 0} piquetes"
        if r.kind == "prodes_laudo":
            return f"Laudo PRODES {p.get('class_name', '')}".strip(), None
        return r.kind, None

    out = []
    for r in rows:
        title, detail = label(r)
        out.append({"id": r.id, "kind": r.kind, "title": title, "detail": detail,
                    "created_at": r.created_at.isoformat(), "file_type": r.file_type,
                    "file_url": f"/api/v1/properties/{property_id}/analyses/{r.id}/file" if r.has_file else None})
    return out


def analysis_file(property_id: int, analysis_id: int) -> tuple:
    """(bytes, mime) do arquivo da análise (GCS ou base64 no registro)."""
    import base64
    row = _get_analysis_row(analysis_id)
    if not row or row.property_id != property_id:
        raise PropertyError("Análise não encontrada.")
    if row.file_path:
        from app import prodes_storage
        data = prodes_storage.download_bytes(row.file_path)
        if data:
            return data, row.file_type
    b64 = (row.result or {}).get("file_b64")
    if b64:
        return base64.b64decode(b64), row.file_type
    raise PropertyError("Arquivo da análise indisponível.")


def rain_for(chat_id: str, property_id: int) -> dict:
    from app.web.analytics import rain_summary
    from app.saas.limit_engine import can_perform_action
    from app.models import log_activity
    cached = _cached_analysis(property_id, "rain", {}, max_age_hours=6)
    if cached:
        return _analysis_dict(cached)
    ok, msg = can_perform_action(chat_id, "LOOKUP")
    if not ok:
        raise PropertyError(msg.replace("Patrão, ", ""))
    prop = get_property(property_id)
    if prop["lat"] is None:
        raise PropertyError("Propriedade sem localização.")
    result = rain_summary(prop["lat"], prop["lon"])
    log_activity(chat_id, "CLIMA", platform="web", details=prop["name"])
    return _analysis_dict(_get_analysis_row(_save_analysis(property_id, chat_id, "rain", {}, result)))


_mdt_jobs = {}   # (property_id, kind) -> {"error": str|None} enquanto o vídeo 3D renderiza


def mdt_for(chat_id: str, property_id: int, kind: str = "2d") -> dict:
    """
    Relevo da propriedade: '2d' = curvas de nível (PNG); '3d' = vídeo 3D com textura Sentinel-2 (MP4).
    O vídeo leva mais que o timeout do proxy do Railway, então o 3D roda numa thread e a
    resposta é {"status": "processing"} até o vídeo aparecer no histórico (o site consulta de novo).
    """
    from app.saas.limit_engine import can_perform_action
    analysis_kind = f"mdt_{kind}"
    cached = _cached_analysis(property_id, analysis_kind, {}, max_age_hours=24 * 30)
    if cached:
        _mdt_jobs.pop((property_id, kind), None)
        return _analysis_dict(cached)
    job = _mdt_jobs.get((property_id, kind))
    if job is not None:
        if job["error"]:
            _mdt_jobs.pop((property_id, kind), None)
            raise PropertyError(job["error"])
        return {"status": "processing"}
    ok, msg = can_perform_action(chat_id, "LOOKUP")
    if not ok:
        raise PropertyError(msg.replace("Patrão, ", ""))
    prop = get_property(property_id)
    if not prop["perimeter"]:
        raise PropertyError("Vincule o CAR desta propriedade para gerar o relevo sobre o perímetro.")
    if kind == "2d":
        return _analysis_dict(_get_analysis_row(_generate_mdt(chat_id, property_id, prop, kind)))

    import threading
    _mdt_jobs[(property_id, kind)] = {"error": None}

    def run():
        try:
            _generate_mdt(chat_id, property_id, prop, kind)
        except PropertyError as e:
            _mdt_jobs[(property_id, kind)] = {"error": str(e)}
        except Exception as e:
            print(f"[WEB MDT] Falha no 3D da propriedade {property_id}: {e}", flush=True)
            _mdt_jobs[(property_id, kind)] = {"error": "Não foi possível gerar o modelo 3D agora."}
    threading.Thread(target=run, daemon=True).start()
    return {"status": "processing"}


def _generate_mdt(chat_id: str, property_id: int, prop: dict, kind: str) -> int:
    from app.gee_connector import get_terrain_data
    from app.environmental import generate_terrain_image_2d, generate_terrain_image_3d
    from app.models import log_activity
    analysis_kind = f"mdt_{kind}"
    terrain = get_terrain_data(prop["perimeter"])
    if not terrain:
        raise PropertyError("Não foi possível obter os dados de elevação agora.")
    center = (prop["lat"], prop["lon"])
    gen = generate_terrain_image_2d if kind == "2d" else generate_terrain_image_3d
    out = gen(terrain, prop["perimeter"], "OFFICIAL", prop["name"], center)
    if not out:
        raise PropertyError("Não foi possível gerar o relevo.")
    data = out.getvalue() if hasattr(out, "getvalue") else out
    log_activity(chat_id, "MDT", platform="web", details=f"{prop['name']} ({kind})")
    result = {"elev_min": terrain.get("elev_min"), "elev_max": terrain.get("elev_max"), "source": terrain.get("source")}
    mime, ext = ("image/png", "png") if kind == "2d" else ("video/mp4", "mp4")
    return _save_analysis(property_id, chat_id, analysis_kind, {}, result, data, mime, ext)


# ── PRODES na web (mesma fila e laudo do bot; origin='web') ──────────────────

def prodes_list_for(chat_id: str, property_id: int, refresh: bool = False) -> dict:
    """Apontamentos PRODES/INPE que cruzam o perímetro (consulta ao vivo; cache de 1 dia)."""
    from app.prodes_analysis import find_intersecting_apontamentos, PRODES_SOURCE_LABEL
    cached = None if refresh else _cached_analysis(property_id, "prodes_list", {}, max_age_hours=24)
    if cached:
        return _analysis_dict(cached)
    prop = get_property(property_id)
    if not prop["perimeter"]:
        raise PropertyError("Vincule o CAR desta propriedade para consultar o PRODES.")
    try:
        aps = find_intersecting_apontamentos(prop["perimeter"])
    except RuntimeError as e:
        print(f"[WEB PRODES] Falha na consulta: {e}", flush=True)
        raise PropertyError("O servidor do INPE (TerraBrasilis) não está respondendo agora. Tente novamente mais tarde.")
    features = [{"type": "Feature", "geometry": a["geometry"], "properties": {
        "uuid": a["uuid"], "class_name": a["class_name"], "year": a["year"],
        "image_date": a["image_date"].isoformat() if a.get("image_date") else None,
        "area_total_ha": round(a["area_total_ha"] or 0, 2), "area_intersect_ha": round(a["area_intersect_ha"] or 0, 2),
        "biome": a.get("biome"),
    }} for a in aps]
    result = {"type": "FeatureCollection", "features": features, "source_label": PRODES_SOURCE_LABEL,
              "queried_at": datetime.utcnow().isoformat()}
    return _analysis_dict(_get_analysis_row(_save_analysis(property_id, chat_id, "prodes_list", {}, result)))


def prodes_report_for(chat_id: str, property_id: int, uuids: list) -> list:
    """Enfileira o laudo (PDF + mapas antes/depois) dos apontamentos escolhidos."""
    from app.prodes_worker import enqueue_prodes_jobs
    from app.saas.limit_engine import can_perform_action
    if not uuids:
        raise PropertyError("Escolha ao menos um apontamento.")
    if len(uuids) > 10:
        raise PropertyError("Escolha no máximo 10 apontamentos por vez.")
    ok, msg = can_perform_action(chat_id, "LOOKUP")
    if not ok:
        raise PropertyError(msg.replace("Patrão, ", ""))
    listing = prodes_list_for(chat_id, property_id)
    chosen = []
    for f in listing["result"]["features"]:
        p = f["properties"]
        if p["uuid"] in uuids:
            from datetime import date as _date
            chosen.append({**p, "geometry": f["geometry"],
                           "image_date": _date.fromisoformat(p["image_date"]) if p["image_date"] else None})
    if not chosen:
        raise PropertyError("Apontamento não encontrado — atualize a lista.")
    prop = get_property(property_id)
    source_info = {"label": listing["result"]["source_label"],
                   "queried_at": datetime.fromisoformat(listing["result"]["queried_at"])}
    entries = enqueue_prodes_jobs(chat_id, chat_id, prop["lat"], prop["lon"], prop["name"], prop["car_code"],
                                  prop["perimeter"], source_info, chosen, origin="web", location_id=property_id)
    return [{"job_id": jid, "class_name": cls} for jid, cls in entries]


def prodes_jobs_for(property_id: int) -> list:
    from app.models import ProdesJob
    db = SessionLocal()
    try:
        rows = (db.query(ProdesJob).filter_by(location_id=property_id)
                .order_by(ProdesJob.created_at.desc()).limit(30).all())
        return [{
            "id": j.id, "status": j.status, "class_name": j.apontamento_class_name, "year": j.apontamento_year,
            "uuid": j.apontamento_uuid, "area_intersect_ha": j.area_intersect_ha,
            "created_at": j.created_at.isoformat() if j.created_at else None,
            "finished_at": j.finished_at.isoformat() if j.finished_at else None,
            "error": (j.last_error or "")[:200] if j.status == "ERROR" else None,
            "files": {k: f"/api/v1/properties/{property_id}/prodes/jobs/{j.id}/{k}"
                      for k, path in (("pdf", j.result_pdf_path), ("antes", j.result_png_before_path),
                                      ("depois", j.result_png_after_path)) if path},
        } for j in rows]
    finally:
        db.close()


def prodes_job_file(property_id: int, job_id: int, which: str) -> tuple:
    from app.models import ProdesJob
    from app import prodes_storage
    db = SessionLocal()
    try:
        j = db.query(ProdesJob).filter_by(id=job_id, location_id=property_id).first()
    finally:
        db.close()
    if not j:
        raise PropertyError("Laudo não encontrado.")
    path, mime, ext = {"pdf": (j.result_pdf_path, "application/pdf", "pdf"),
                       "antes": (j.result_png_before_path, "image/png", "png"),
                       "depois": (j.result_png_after_path, "image/png", "png")}.get(which, (None, None, None))
    if path and path.startswith("analysis:"):   # sem GCS: arquivo guardado no histórico da propriedade
        data = analysis_file(property_id, int(path.split(":", 1)[1]))[0]
    else:
        data = prodes_storage.download_bytes(path) if path else None
    if not data:
        raise PropertyError("Arquivo do laudo indisponível.")
    name = (f"Laudo_PRODES_{j.apontamento_class_name}.pdf" if which == "pdf"
            else f"PRODES_{j.apontamento_class_name}_{which}.{ext}")
    return data, mime, name


# ── Piquetes (desenhados na web; NDVI por piquete) ───────────────────────────

MAX_PADDOCKS = 200
MIN_PADDOCK_HA = 0.05


def list_paddocks(property_id: int) -> dict:
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT id, name, area_ha, ST_AsGeoJSON(geom, 7) AS g FROM property_paddocks
            WHERE property_id = :pid ORDER BY name, id
        """), {"pid": property_id}).fetchall()
    finally:
        db.close()
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "id": r.id, "geometry": json.loads(r.g),
         "properties": {"id": r.id, "name": r.name, "area_ha": round(r.area_ha or 0, 2)}} for r in rows]}


def _clip_to_perimeter(db, property_id: int, geometry: dict):
    """Polígono recortado no perímetro (maior parte, se o recorte dividir) → (WKT, área ha)."""
    if (geometry or {}).get("type") != "Polygon":
        raise PropertyError("Desenhe o piquete como um polígono.")
    r = db.execute(text("""
        WITH d AS (SELECT ST_MakeValid(ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326)) AS g),
             c AS (SELECT ST_CollectionExtract(ST_MakeValid(ST_Intersection(d.g, f.perimeter)), 3) AS g
                   FROM d, favorite_locations f WHERE f.id = :pid),
             parts AS (SELECT (ST_Dump(c.g)).geom AS g FROM c)
        SELECT ST_AsText(g) AS wkt, ST_Area(g::geography) / 10000 AS ha FROM parts
        ORDER BY ST_Area(g::geography) DESC LIMIT 1
    """), {"g": json.dumps(geometry), "pid": property_id}).fetchone()
    if not r or not r.wkt:
        raise PropertyError("O piquete precisa ficar dentro do perímetro da propriedade.")
    if r.ha < MIN_PADDOCK_HA:
        raise PropertyError("Piquete muito pequeno (mínimo 0,05 ha).")
    return r.wkt, r.ha


def create_paddock(chat_id: str, property_id: int, name: str, geometry: dict) -> dict:
    prop = get_property(property_id)
    if not prop["perimeter"]:
        raise PropertyError("Vincule o CAR desta propriedade para desenhar piquetes.")
    db = SessionLocal()
    try:
        n = db.execute(text("SELECT count(*) FROM property_paddocks WHERE property_id = :pid"), {"pid": property_id}).scalar()
        if n >= MAX_PADDOCKS:
            raise PropertyError(f"Limite de {MAX_PADDOCKS} piquetes por propriedade.")
        wkt, ha = _clip_to_perimeter(db, property_id, geometry)
        new_id = db.execute(text("""
            INSERT INTO property_paddocks (property_id, name, geom, area_ha, created_by, created_at, updated_at)
            VALUES (:pid, :name, ST_GeomFromText(:wkt, 4326), :ha, :cid, now() at time zone 'utc', now() at time zone 'utc')
            RETURNING id
        """), {"pid": property_id, "name": name.strip()[:60], "wkt": wkt, "ha": ha, "cid": str(chat_id)}).scalar()
        db.commit()
    finally:
        db.close()
    return next(f for f in list_paddocks(property_id)["features"] if f["id"] == new_id)


def update_paddock(property_id: int, paddock_id: int, name: str = None, geometry: dict = None) -> dict:
    db = SessionLocal()
    try:
        if not db.execute(text("SELECT 1 FROM property_paddocks WHERE id = :id AND property_id = :pid"),
                          {"id": paddock_id, "pid": property_id}).fetchone():
            raise PropertyError("Piquete não encontrado.")
        if name is not None:
            db.execute(text("UPDATE property_paddocks SET name = :n, updated_at = now() at time zone 'utc' WHERE id = :id"),
                       {"n": name.strip()[:60], "id": paddock_id})
        if geometry is not None:
            wkt, ha = _clip_to_perimeter(db, property_id, geometry)
            db.execute(text("""UPDATE property_paddocks SET geom = ST_GeomFromText(:wkt, 4326), area_ha = :ha,
                               updated_at = now() at time zone 'utc' WHERE id = :id"""), {"wkt": wkt, "ha": ha, "id": paddock_id})
        db.commit()
    finally:
        db.close()
    return next(f for f in list_paddocks(property_id)["features"] if f["id"] == paddock_id)


def delete_paddock(property_id: int, paddock_id: int):
    db = SessionLocal()
    try:
        db.execute(text("DELETE FROM property_paddocks WHERE id = :id AND property_id = :pid"), {"id": paddock_id, "pid": property_id})
        db.commit()
    finally:
        db.close()


def paddocks_ndvi_for(chat_id: str, property_id: int, month: str) -> dict:
    """
    NDVI médio de cada piquete: no mês (mediana das cenas) ou, com month='latest', na imagem
    mais recente sem nuvens. Um único reduceRegions no Earth Engine.
    """
    import hashlib
    import re as _re
    from app.web.analytics import ndvi_month_zones, ndvi_latest_zones
    from app.saas.limit_engine import can_perform_action
    from app.models import log_activity
    latest = month == "latest"
    if not latest and not _re.fullmatch(r"\d{4}-\d{2}", month or ""):
        raise PropertyError("Mês inválido (use AAAA-MM ou latest).")
    db = SessionLocal()
    try:
        rows = db.execute(text("""SELECT id, ST_AsGeoJSON(geom, 7) AS g, updated_at FROM property_paddocks
                                  WHERE property_id = :pid ORDER BY id"""), {"pid": property_id}).fetchall()
    finally:
        db.close()
    if not rows:
        raise PropertyError("Desenhe ao menos um piquete.")
    # a assinatura muda quando um piquete é criado, editado ou excluído → cache invalida sozinho
    sig = hashlib.md5("|".join(f"{r.id}:{r.updated_at}" for r in rows).encode()).hexdigest()[:12]
    current = datetime.utcnow().strftime("%Y-%m")
    params = {"month": month, "sig": sig}
    max_age = 12 if latest else 24 if month == current else 24 * 365
    cached = _cached_analysis(property_id, "paddock_ndvi", params, max_age_hours=max_age)
    if cached:
        return _analysis_dict(cached)
    ok, msg = can_perform_action(chat_id, "LOOKUP")
    if not ok:
        raise PropertyError(msg.replace("Patrão, ", ""))
    zones = [(r.id, json.loads(r.g)) for r in rows]
    out = ndvi_latest_zones(zones) if latest else ndvi_month_zones(zones, month)
    if out["images"] == 0:
        raise PropertyError("Nenhuma imagem sem nuvens sobre os piquetes nos últimos 90 dias." if latest
                            else "Nenhuma imagem de satélite sem nuvens nesse mês.")
    log_activity(chat_id, "NDVI", platform="web", details=f"piquetes ({len(rows)}) {month}")
    aid = _save_analysis(property_id, chat_id, "paddock_ndvi", params, out)
    return _analysis_dict(_get_analysis_row(aid))
