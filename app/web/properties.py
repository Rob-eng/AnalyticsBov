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


def get_property(property_id: int) -> dict:
    db = SessionLocal()
    try:
        r = db.execute(text("""
            SELECT id, name, latitude, longitude, car_code, area_ha, municipio, uf, car_synced_at,
                   perimeter IS NOT NULL AS has_perimeter,
                   ST_AsGeoJSON(perimeter, 7) AS perimeter_geojson,
                   ST_XMin(perimeter) AS xmin, ST_YMin(perimeter) AS ymin, ST_XMax(perimeter) AS xmax, ST_YMax(perimeter) AS ymax
            FROM favorite_locations WHERE id = :pid
        """), {"pid": property_id}).fetchone()
        if not r:
            raise PropertyError("Propriedade não encontrada.")
        out = _row_to_dict(r)
        out["perimeter"] = json.loads(r.perimeter_geojson) if r.perimeter_geojson else None
        out["bbox"] = [r.xmin, r.ymin, r.xmax, r.ymax] if r.perimeter_geojson else None
        return out
    finally:
        db.close()


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


def mdt_for(chat_id: str, property_id: int, kind: str = "2d") -> dict:
    """Relevo da propriedade: '2d' = curvas de nível (PNG); '3d' = vídeo 3D com textura Sentinel-2 (MP4)."""
    from app.gee_connector import get_terrain_data
    from app.environmental import generate_terrain_image_2d, generate_terrain_image_3d
    from app.saas.limit_engine import can_perform_action
    from app.models import log_activity
    analysis_kind = f"mdt_{kind}"
    cached = _cached_analysis(property_id, analysis_kind, {}, max_age_hours=24 * 30)
    if cached:
        return _analysis_dict(cached)
    ok, msg = can_perform_action(chat_id, "LOOKUP")
    if not ok:
        raise PropertyError(msg.replace("Patrão, ", ""))
    prop = get_property(property_id)
    if not prop["perimeter"]:
        raise PropertyError("Vincule o CAR desta propriedade para gerar o relevo sobre o perímetro.")
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
    return _analysis_dict(_get_analysis_row(_save_analysis(property_id, chat_id, analysis_kind, {}, result, data, mime, ext)))
