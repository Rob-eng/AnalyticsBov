"""
Benfeitorias, pontos de água e anotações no mapa da fazenda.

Pontos: sede, curral, galpão, aguada, bebedouro, cocho, poço/caixa d'água, porteira, anotação.
Linhas: cerca, estrada/carreador, rede de água (comprimento calculado).
Os pontos de água alimentam a "distância até a água" de cada piquete.
"""
import json

from sqlalchemy import text

from app.models import SessionLocal
from app.web.properties import PropertyError

# tipo → (rótulo, geometria)
KINDS = {
    "sede": ("Sede", "Point"),
    "curral": ("Curral", "Point"),
    "galpao": ("Galpão", "Point"),
    "aguada": ("Aguada / represa", "Point"),
    "bebedouro": ("Bebedouro", "Point"),
    "cocho": ("Cocho", "Point"),
    "poco": ("Poço / caixa d'água", "Point"),
    "porteira": ("Porteira", "Point"),
    "nota": ("Anotação", "Point"),
    "cerca": ("Cerca", "LineString"),
    "estrada": ("Estrada / carreador", "LineString"),
    "rede_agua": ("Rede de água", "LineString"),
}
WATER_KINDS = ("aguada", "bebedouro", "poco")
MAX_ITEMS = 500
NEAR_PERIMETER_M = 300   # pode ficar um pouco fora do perímetro (estrada de acesso, porteira na divisa)


def list_improvements(property_id: int) -> dict:
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT id, kind, name, notes, length_m, ST_AsGeoJSON(geom, 7) AS g FROM property_improvements
            WHERE property_id = :pid ORDER BY kind, name, id
        """), {"pid": property_id}).fetchall()
    finally:
        db.close()
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "id": r.id, "geometry": json.loads(r.g),
         "properties": {"id": r.id, "kind": r.kind, "kind_label": KINDS.get(r.kind, (r.kind,))[0], "name": r.name,
                        "notes": r.notes, "length_m": round(r.length_m) if r.length_m else None}}
        for r in rows],
        "kinds": [{"key": k, "label": v[0], "geometry": v[1], "water": k in WATER_KINDS} for k, v in KINDS.items()]}


def _validate(db, property_id: int, kind: str, geometry: dict):
    if kind not in KINDS:
        raise PropertyError("Tipo inválido.")
    expected = KINDS[kind][1]
    if (geometry or {}).get("type") != expected:
        raise PropertyError("Marque um ponto no mapa." if expected == "Point" else "Desenhe a linha no mapa.")
    near = db.execute(text("""
        SELECT ST_DWithin(ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326)::geography, f.perimeter::geography, :m)
        FROM favorite_locations f WHERE f.id = :pid AND f.perimeter IS NOT NULL
    """), {"g": json.dumps(geometry), "pid": property_id, "m": NEAR_PERIMETER_M}).scalar()
    if near is False:
        raise PropertyError("Marque dentro da propriedade (ou bem perto da divisa).")


def create_improvement(chat_id: str, property_id: int, kind: str, geometry: dict, name=None, notes=None) -> dict:
    db = SessionLocal()
    try:
        if db.execute(text("SELECT count(*) FROM property_improvements WHERE property_id = :pid"), {"pid": property_id}).scalar() >= MAX_ITEMS:
            raise PropertyError(f"Limite de {MAX_ITEMS} itens por propriedade.")
        _validate(db, property_id, kind, geometry)
        new_id = db.execute(text("""
            INSERT INTO property_improvements (property_id, kind, name, notes, geom, length_m, created_by, created_at, updated_at)
            SELECT :pid, :k, :n, :notes, g,
                   CASE WHEN GeometryType(g) = 'LINESTRING' THEN ST_Length(g::geography) END,
                   :cid, now() at time zone 'utc', now() at time zone 'utc'
            FROM (SELECT ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326) AS g) x
            RETURNING id
        """), {"pid": property_id, "k": kind, "n": (name or "").strip()[:60] or None,
               "notes": (notes or "").strip()[:500] or None, "g": json.dumps(geometry), "cid": str(chat_id)}).scalar()
        db.commit()
    finally:
        db.close()
    return next(f for f in list_improvements(property_id)["features"] if f["id"] == new_id)


def update_improvement(property_id: int, item_id: int, fields: dict) -> dict:
    db = SessionLocal()
    try:
        row = db.execute(text("SELECT kind FROM property_improvements WHERE id = :id AND property_id = :pid"),
                         {"id": item_id, "pid": property_id}).fetchone()
        if not row:
            raise PropertyError("Item não encontrado.")
        if "name" in fields:
            db.execute(text("UPDATE property_improvements SET name = :n WHERE id = :id"),
                       {"n": (fields["name"] or "").strip()[:60] or None, "id": item_id})
        if "notes" in fields:
            db.execute(text("UPDATE property_improvements SET notes = :n WHERE id = :id"),
                       {"n": (fields["notes"] or "").strip()[:500] or None, "id": item_id})
        if fields.get("geometry"):
            _validate(db, property_id, row.kind, fields["geometry"])
            db.execute(text("""
                UPDATE property_improvements SET geom = g,
                       length_m = CASE WHEN GeometryType(g) = 'LINESTRING' THEN ST_Length(g::geography) END
                FROM (SELECT ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326) AS g) x WHERE id = :id
            """), {"g": json.dumps(fields["geometry"]), "id": item_id})
        db.execute(text("UPDATE property_improvements SET updated_at = now() at time zone 'utc' WHERE id = :id"), {"id": item_id})
        db.commit()
    finally:
        db.close()
    return next(f for f in list_improvements(property_id)["features"] if f["id"] == item_id)


def delete_improvement(property_id: int, item_id: int):
    db = SessionLocal()
    try:
        db.execute(text("DELETE FROM property_improvements WHERE id = :id AND property_id = :pid"), {"id": item_id, "pid": property_id})
        db.commit()
    finally:
        db.close()


def water_distance_by_paddock(db, property_id: int) -> dict:
    """{paddock_id: metros até o ponto de água mais próximo (0 = dentro do piquete)}; vazio se não há água marcada."""
    rows = db.execute(text("""
        SELECT p.id, min(ST_Distance(p.geom::geography, w.geom::geography)) AS m
        FROM property_paddocks p JOIN property_improvements w
          ON w.property_id = p.property_id AND w.kind = ANY(:kinds)
        WHERE p.property_id = :pid GROUP BY p.id
    """), {"pid": property_id, "kinds": list(WATER_KINDS)}).fetchall()
    return {r.id: round(r.m) for r in rows}
