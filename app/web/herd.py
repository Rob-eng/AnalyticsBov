"""
Rebanho por lote, rotação de pastejo (manual) e lotação por piquete.

- Lote: categoria, cabeças e peso médio (vazio = peso padrão da categoria).
  UA = cabeças × peso / 450 kg.
- Rotação: "lote entrou no piquete" fecha a ocupação anterior do lote e abre
  a nova; o estado do piquete (em uso / em descanso / pronto) sai das
  ocupações. Com a telemetria, as mesmas ocupações passam a ser criadas
  automaticamente (source='telemetria').
- Lotação: UA/ha sobre a área de PASTO do piquete (contorno − recortes de mata).
"""
from datetime import date

from sqlalchemy import text

from app.models import SessionLocal
from app.web.properties import PropertyError

UA_KG = 450
# (rótulo, peso padrão em kg) — convenção usual; cada lote pode informar o peso real
CATEGORIES = {
    "vaca": ("Vaca", 450),
    "touro": ("Touro", 700),
    "boi": ("Boi", 480),
    "novilho": ("Novilho / garrote", 330),
    "novilha": ("Novilha", 300),
    "bezerro": ("Bezerro(a)", 180),
}
REST_MIN_DAYS, REST_MAX_DAYS = 26, 35   # janela de descanso recomendada antes da reentrada
# lotação × NDVI (NDVI da última imagem já calculada para os piquetes)
NDVI_PRESSURE = 0.45    # lote dentro e NDVI abaixo disto → pasto sob pressão
NDVI_SLOW = 0.40        # em descanso e NDVI abaixo disto → rebrota lenta
NDVI_SURPLUS = 0.60     # descanso além da janela e NDVI acima disto → pasto sobrando


def _ua(category: str, heads: int, weight) -> float:
    w = weight or CATEGORIES.get(category, ("", UA_KG))[1]
    return round(heads * w / UA_KG, 2)


def _lot_dict(r) -> dict:
    default_w = CATEGORIES.get(r.category, ("", UA_KG))[1]
    return {
        "id": r.id, "name": r.name, "category": r.category,
        "category_label": CATEGORIES.get(r.category, (r.category,))[0],
        "head_count": r.head_count, "avg_weight_kg": r.avg_weight_kg, "default_weight_kg": default_w,
        "ua": _ua(r.category, r.head_count, r.avg_weight_kg), "notes": r.notes,
        "paddock_id": r.current_paddock_id, "paddock_name": getattr(r, "paddock_name", None),
        "since": r.since.isoformat() if getattr(r, "since", None) else None,
    }


def _check_lot_fields(category, head_count, avg_weight_kg):
    if category is not None and category not in CATEGORIES:
        raise PropertyError("Categoria inválida.")
    if head_count is not None and not (1 <= head_count <= 100000):
        raise PropertyError("Informe o número de cabeças (1 a 100.000).")
    if avg_weight_kg is not None and not (20 <= avg_weight_kg <= 1500):
        raise PropertyError("Peso médio fora do esperado (20 a 1.500 kg).")


# ── Lotes ─────────────────────────────────────────────────────────────────────

def herd_for(property_id: int) -> dict:
    """Lotes + resumo (cabeças, UA, UA/ha) + categorias disponíveis."""
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT l.*, p.name AS paddock_name, o.entered_on AS since
            FROM property_lots l
            LEFT JOIN property_paddocks p ON p.id = l.current_paddock_id
            LEFT JOIN paddock_occupations o ON o.lot_id = l.id AND o.left_on IS NULL
            WHERE l.property_id = :pid ORDER BY l.name, l.id
        """), {"pid": property_id}).fetchall()
        areas = db.execute(text("""
            SELECT (SELECT sum(COALESCE(pasture_ha, area_ha)) FROM property_paddocks WHERE property_id = :pid) AS pasture,
                   (SELECT area_ha FROM favorite_locations WHERE id = :pid) AS total
        """), {"pid": property_id}).fetchone()
    finally:
        db.close()
    lots = [_lot_dict(r) for r in rows]
    ua = round(sum(l["ua"] for l in lots), 2)
    base_ha, base = (areas.pasture, "pasto dos piquetes") if areas.pasture else (areas.total, "área do imóvel")
    return {
        "lots": lots,
        "summary": {"heads": sum(l["head_count"] for l in lots), "ua": ua,
                    "ua_ha": round(ua / base_ha, 2) if base_ha else None, "area_ha": round(base_ha or 0, 2), "area_base": base},
        "categories": [{"key": k, "label": v[0], "default_weight_kg": v[1]} for k, v in CATEGORIES.items()],
    }


def create_lot(chat_id: str, property_id: int, name: str, category: str, head_count: int, avg_weight_kg=None, notes=None) -> dict:
    _check_lot_fields(category, head_count, avg_weight_kg)
    db = SessionLocal()
    try:
        if db.execute(text("SELECT count(*) FROM property_lots WHERE property_id = :pid"), {"pid": property_id}).scalar() >= 200:
            raise PropertyError("Limite de 200 lotes por propriedade.")
        db.execute(text("""
            INSERT INTO property_lots (property_id, name, category, head_count, avg_weight_kg, notes, created_by, created_at, updated_at)
            VALUES (:pid, :n, :c, :h, :w, :notes, :cid, now() at time zone 'utc', now() at time zone 'utc')
        """), {"pid": property_id, "n": name.strip()[:60], "c": category, "h": head_count, "w": avg_weight_kg,
               "notes": (notes or "").strip()[:500] or None, "cid": str(chat_id)})
        db.commit()
    finally:
        db.close()
    return herd_for(property_id)


def update_lot(property_id: int, lot_id: int, fields: dict) -> dict:
    """Edita o lote. Mudar cabeças/peso de um lote ocupando um piquete atualiza a foto da ocupação aberta."""
    _check_lot_fields(fields.get("category"), fields.get("head_count"), fields.get("avg_weight_kg"))
    allowed = {k: v for k, v in fields.items() if k in ("name", "category", "head_count", "avg_weight_kg", "notes")}
    if "name" in allowed:
        allowed["name"] = (allowed["name"] or "").strip()[:60] or None
        if not allowed["name"]:
            raise PropertyError("Informe o nome do lote.")
    db = SessionLocal()
    try:
        lot = db.execute(text("SELECT * FROM property_lots WHERE id = :id AND property_id = :pid"),
                         {"id": lot_id, "pid": property_id}).fetchone()
        if not lot:
            raise PropertyError("Lote não encontrado.")
        if allowed:
            sets = ", ".join(f"{k} = :{k}" for k in allowed)
            db.execute(text(f"UPDATE property_lots SET {sets}, updated_at = now() at time zone 'utc' WHERE id = :id"),
                       {**allowed, "id": lot_id})
        new = db.execute(text("SELECT category, head_count, avg_weight_kg FROM property_lots WHERE id = :id"), {"id": lot_id}).fetchone()
        db.execute(text("UPDATE paddock_occupations SET head_count = :h, ua = :ua WHERE lot_id = :id AND left_on IS NULL"),
                   {"h": new.head_count, "ua": _ua(new.category, new.head_count, new.avg_weight_kg), "id": lot_id})
        db.commit()
    finally:
        db.close()
    return herd_for(property_id)


def delete_lot(property_id: int, lot_id: int):
    db = SessionLocal()
    try:
        db.execute(text("DELETE FROM property_lots WHERE id = :id AND property_id = :pid"), {"id": lot_id, "pid": property_id})
        db.commit()
    finally:
        db.close()


# ── Rotação (entrada/saída de lote em piquete) ───────────────────────────────

def move_lot(chat_id: str, property_id: int, lot_id: int, paddock_id, on: date) -> dict:
    """Lote entra no piquete `paddock_id` (ou sai de todos, se None) na data `on`."""
    if on > date.today():
        raise PropertyError("A data não pode ser no futuro.")
    db = SessionLocal()
    try:
        lot = db.execute(text("SELECT * FROM property_lots WHERE id = :id AND property_id = :pid"),
                         {"id": lot_id, "pid": property_id}).fetchone()
        if not lot:
            raise PropertyError("Lote não encontrado.")
        if paddock_id is not None:
            if not db.execute(text("SELECT 1 FROM property_paddocks WHERE id = :id AND property_id = :pid"),
                              {"id": paddock_id, "pid": property_id}).fetchone():
                raise PropertyError("Piquete não encontrado.")
            if paddock_id == lot.current_paddock_id:
                raise PropertyError("O lote já está neste piquete.")
        last = db.execute(text("SELECT max(GREATEST(entered_on, COALESCE(left_on, entered_on))) FROM paddock_occupations WHERE lot_id = :id"),
                          {"id": lot_id}).scalar()
        if last and on < last:
            raise PropertyError(f"A data precisa ser igual ou posterior à última movimentação do lote ({last.strftime('%d/%m/%Y')}).")
        db.execute(text("UPDATE paddock_occupations SET left_on = :d WHERE lot_id = :id AND left_on IS NULL"), {"d": on, "id": lot_id})
        if paddock_id is not None:
            db.execute(text("""
                INSERT INTO paddock_occupations (property_id, paddock_id, lot_id, entered_on, head_count, ua, source, created_by, created_at)
                VALUES (:pid, :pk, :lot, :d, :h, :ua, 'manual', :cid, now() at time zone 'utc')
            """), {"pid": property_id, "pk": paddock_id, "lot": lot_id, "d": on, "h": lot.head_count,
                   "ua": _ua(lot.category, lot.head_count, lot.avg_weight_kg), "cid": str(chat_id)})
        db.execute(text("UPDATE property_lots SET current_paddock_id = :pk, updated_at = now() at time zone 'utc' WHERE id = :id"),
                   {"pk": paddock_id, "id": lot_id})
        db.commit()
    finally:
        db.close()
    return herd_for(property_id)


def grazing_for(property_id: int) -> dict:
    """
    Estado de cada piquete: em uso (lotes, UA, UA/ha, dias de ocupação) ou em descanso
    (dias de descanso e situação frente à janela de 26–35 dias), + ocupações recentes.
    """
    today = date.today()
    db = SessionLocal()
    try:
        paddocks = db.execute(text("""
            SELECT id, name, COALESCE(pasture_ha, area_ha) AS pasture_ha FROM property_paddocks
            WHERE property_id = :pid ORDER BY name, id
        """), {"pid": property_id}).fetchall()
        last_ndvi = db.execute(text("""
            SELECT result FROM property_analyses
            WHERE property_id = :pid AND kind = 'paddock_ndvi' AND params->>'month' = 'latest'
            ORDER BY created_at DESC LIMIT 1
        """), {"pid": property_id}).fetchone()
        occ = db.execute(text("""
            SELECT o.id, o.paddock_id, o.lot_id, l.name AS lot_name, o.entered_on, o.left_on, o.head_count, o.ua, o.source
            FROM paddock_occupations o JOIN property_lots l ON l.id = o.lot_id
            WHERE o.property_id = :pid ORDER BY o.entered_on DESC, o.id DESC
        """), {"pid": property_id}).fetchall()
    finally:
        db.close()
    ndvi_vals = (last_ndvi.result or {}).get("values", {}) if last_ndvi else {}
    ndvi_date = (last_ndvi.result or {}).get("date") if last_ndvi else None
    out = []
    for p in paddocks:
        mine = [o for o in occ if o.paddock_id == p.id]
        open_ = [o for o in mine if o.left_on is None]
        item = {"id": p.id, "name": p.name, "pasture_ha": round(p.pasture_ha or 0, 2)}
        if open_:
            ua = sum(o.ua for o in open_)
            since = min(o.entered_on for o in open_)
            item.update(status="em_uso", lots=[{"id": o.lot_id, "name": o.lot_name, "heads": o.head_count, "ua": o.ua} for o in open_],
                        ua=round(ua, 2), ua_ha=round(ua / p.pasture_ha, 2) if p.pasture_ha else None,
                        days=(today - since).days, since=since.isoformat())
        elif mine:
            left = max(o.left_on for o in mine)
            rest = (today - left).days
            status = "descanso" if rest < REST_MIN_DAYS else "pronto" if rest <= REST_MAX_DAYS else "descanso_longo"
            item.update(status=status, days=rest, since=left.isoformat())
        else:
            item.update(status="sem_registro")
        nd = ndvi_vals.get(str(p.id))
        item["ndvi"] = nd
        st = item["status"]
        flag = None
        if nd is not None:
            nds = f"{nd:.2f}".replace(".", ",")
            if st == "em_uso" and nd < NDVI_PRESSURE:
                flag = {"level": "alerta", "text": f"Pasto sob pressão: NDVI {nds} com o lote dentro"}
            elif st in ("descanso", "pronto", "descanso_longo") and nd < NDVI_SLOW:
                flag = {"level": "atencao", "text": f"Rebrota lenta: NDVI {nds} em descanso"}
            elif st == "descanso_longo" and nd >= NDVI_SURPLUS:
                flag = {"level": "info", "text": f"Pasto sobrando: {item['days']} dias de descanso e NDVI {nds}"}
        item["flag"] = flag
        item["history"] = [{"lot": o.lot_name, "entered_on": o.entered_on.isoformat(),
                            "left_on": o.left_on.isoformat() if o.left_on else None,
                            "days": ((o.left_on or today) - o.entered_on).days, "heads": o.head_count, "ua": o.ua,
                            "source": o.source} for o in mine[:10]]
        out.append(item)
    return {"paddocks": out, "rest_window": [REST_MIN_DAYS, REST_MAX_DAYS], "today": today.isoformat(),
            "ndvi_date": ndvi_date,
            "thresholds": {"pressure": NDVI_PRESSURE, "slow": NDVI_SLOW, "surplus": NDVI_SURPLUS}}
