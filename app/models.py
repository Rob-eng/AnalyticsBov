from sqlalchemy import Column, Integer, BigInteger, String, Float, DateTime, Boolean, create_engine, text, ForeignKey, Text, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
import pandas as pd
from geoalchemy2 import Geometry
from app.config import Config

Base = declarative_base()
SpatialBase = declarative_base()

class User(Base):
    __tablename__ = 'users'
    
    chat_id = Column(String, primary_key=True)
    username = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # SaaS & Platform fields
    platform = Column(String, default='telegram')  # 'telegram' ou 'whatsapp'
    plan_type = Column(String, default='FREE')     # 'FREE', 'STARTER', 'PRO', 'ENTERPRISE'
    stripe_subscription_id = Column(String, nullable=True)
    trial_expires_at = Column(DateTime, nullable=True)  # Data de expiração do trial/promo grátis

    
    locations = relationship("FavoriteLocation", backref="user", cascade="all, delete-orphan")

class FavoriteLocation(Base):
    __tablename__ = 'favorite_locations'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(String, ForeignKey('users.chat_id'))
    name = Column(String)
    latitude = Column(Float)
    longitude = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)
    # NDVI alert tracking
    last_ndvi_date = Column(String, nullable=True)        # 'YYYY-MM-DD' of last image sent
    ndvi_alerts_enabled = Column(Boolean, default=True)  # user opt-in/out per property

class PriceHistory(Base):
    __tablename__ = 'price_history'
    
    id = Column(Integer, primary_key=True)
    country = Column(String)
    price = Column(Float)
    date = Column(DateTime, default=datetime.utcnow)

class CdaEvent(Base):
    __tablename__ = 'cda_events'

    id = Column(Integer, primary_key=True)
    event_name = Column(String, nullable=True)
    event_date = Column(DateTime, nullable=True, index=True)
    event_location = Column(String, nullable=True)
    source_url = Column(String, nullable=False, index=True)
    source_page = Column(String, nullable=True)
    collected_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class CdaLotResult(Base):
    __tablename__ = 'cda_lot_results'

    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey('cda_events.id'), nullable=True, index=True)
    source_url = Column(String, nullable=False, index=True)
    source_page = Column(String, nullable=True)

    lot_ref = Column(String, nullable=True)
    race_raw = Column(String, nullable=True, index=True)
    sex_raw = Column(String, nullable=True, index=True)
    era_raw = Column(String, nullable=True, index=True)
    weight_kg = Column(Float, nullable=True)
    arrobas = Column(Float, nullable=True)
    qtde_animals = Column(Integer, nullable=True)       # cabeças vendidas no lote
    scrape_mode = Column(String, default='individual')  # 'individual' ou 'medias'
    closed_price_brl = Column(Float, nullable=True)
    price_per_kg_brl = Column(Float, nullable=True)         # R$/kg vivo (era_raw parsed)
    price_per_arroba_brl = Column(Float, nullable=True)
    currency = Column(String, default='BRL', nullable=False)

    row_raw = Column(Text, nullable=True)
    hash_key = Column(String, nullable=False, unique=True, index=True)

    collected_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    event = relationship("CdaEvent", backref="lots")

class CdaMarketComparison(Base):
    __tablename__ = 'cda_market_comparisons'

    id = Column(Integer, primary_key=True)
    reference_date = Column(DateTime, nullable=False, index=True)
    race_norm = Column(String, nullable=True, index=True)
    sex_norm = Column(String, nullable=True, index=True)
    era_norm = Column(String, nullable=True, index=True)

    avg_cda_price_per_kg_brl = Column(Float, nullable=True)    # R$/kg vivo (métrica principal)
    avg_cda_price_per_arroba_brl = Column(Float, nullable=True) # mantido para compat.
    avg_cda_closed_price_brl = Column(Float, nullable=True)
    lots_count = Column(Integer, nullable=False, default=0)

    scot_country = Column(String, nullable=True, index=True)
    scot_price_usd = Column(Float, nullable=True)   # US$/@ carcaça
    usd_brl_rate = Column(Float, nullable=True)     # câmbio na data
    cda_to_scot_ratio = Column(Float, nullable=True) # CDA R$/@ ÷ Scot R$/@ (adimensional)

    hash_key = Column(String, nullable=False, unique=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class CARCaptchaSession(Base):
    """
    Armazena o estado de uma tentativa de download do SICAR que 
    precisa de intervenção humana para o Captcha.
    """
    __tablename__ = 'car_captcha_sessions'
    
    chat_id = Column(String, primary_key=True)
    car_code = Column(String)
    imovel_id = Column(String)
    cookies_json = Column(String) # JSON de cookies da requests.Session
    created_at = Column(DateTime, default=datetime.utcnow)

class ActivityLog(Base):
    __tablename__ = 'activity_logs'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(String, ForeignKey('users.chat_id'))
    action = Column(String) # 'NDVI', 'CLIMA', 'MDT', 'CAR_SEARCH', 'ZIP_UPLOAD', etc.
    platform = Column(String) # 'whatsapp', 'telegram'
    trigger_type = Column(String, default='USER_REQUEST') # 'USER_REQUEST' ou 'AUTO_ALERT'
    details = Column(String, nullable=True) # Ex: 'CAR: MT-xxx'
    status = Column(String, default='SUCCESS') # 'SUCCESS', 'ERROR'
    error_message = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Feedback(Base):
    __tablename__ = 'feedbacks'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(String, ForeignKey('users.chat_id'))
    message = Column(String)
    status = Column(String, default='NEW') # 'NEW', 'READ', 'IMPLEMENTED'
    created_at = Column(DateTime, default=datetime.utcnow)

class CARProperty(SpatialBase):
    __tablename__ = 'car_properties'
    
    id = Column(BigInteger, primary_key=True)
    cod_imovel = Column(String(100), unique=True, index=True)
    uf = Column(String(2), index=True)
    municipio = Column(String(100))
    # SRID 4674 is SIRGAS 2000 (Geodetic), common in Brazil and compatible with WGS84
    geometry = Column(Geometry('MULTIPOLYGON', srid=4674))

import os
if not Config.DATABASE_URL:
    raise ValueError("A variável de ambiente DATABASE_URL não está definida. Verifique as configurações no Railway.")

# Fix for SQLAlchemy requiring 'postgresql://' instead of 'postgres://'
db_url = Config.DATABASE_URL
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

engine = create_engine(db_url, pool_pre_ping=True, connect_args={'connect_timeout': 10})
SessionLocal = sessionmaker(bind=engine)

# Secondary engine for CAR spatial data (Supabase)
# Railway tem problemas com IPv6 para o Supabase.
# Solução: usar o Transaction Pooler (porta 6543) que resolve via IPv4.
car_db_url = Config.CAR_DATABASE_URL or db_url 
if car_db_url and car_db_url.startswith("postgres://"):
    car_db_url = car_db_url.replace("postgres://", "postgresql://", 1)

# 🔧 AUTO-FIX: Se a URL do Supabase usa porta 5432 (direta), tenta usar o pooler (6543)
# O pooler usa IPv4 e não sofre do erro "Network is unreachable" no Railway/IPv6.
car_db_url_pooler = None
if car_db_url and 'supabase.co' in car_db_url and ':5432' in car_db_url:
    car_db_url_pooler = car_db_url.replace(':5432', ':6543').replace(
        'db.', ''  # Pooler URL remove o prefixo 'db.'
    )
    # O pooler do Supabase usa o formato: 
    # postgresql://user:pass@PROJECT_REF.pooler.supabase.com:6543/postgres
    # Tentamos construir a URL automaticamente
    import re
    match = re.search(r'db\.([a-z]+\.supabase\.co)', car_db_url)
    if match:
        pooler_host = match.group(1).replace('.supabase.co', '.pooler.supabase.com')
        car_db_url_pooler = re.sub(
            r'@db\.[a-z]+\.supabase\.co:\d+',
            f'@{pooler_host}:6543',
            car_db_url
        )
        print(f"🔧 [CAR DB] Pooler URL gerada: ...@{pooler_host}:6543/...")

# Tenta a conexão direta primeiro, se falhar, usa o pooler
try:
    car_engine = create_engine(car_db_url, pool_pre_ping=True, connect_args={'connect_timeout': 5})
    with car_engine.connect() as test_conn:
        test_conn.execute(text("SELECT 1"))
    print("✅ [CAR DB] Conexão direta com Supabase OK.")
except Exception as e:
    print(f"⚠️ [CAR DB] Conexão direta falhou: {e}")
    if car_db_url_pooler:
        print(f"🔄 [CAR DB] Tentando via Transaction Pooler (IPv4)...")
        try:
            car_engine = create_engine(car_db_url_pooler, pool_pre_ping=True, connect_args={'connect_timeout': 10})
            with car_engine.connect() as test_conn:
                test_conn.execute(text("SELECT 1"))
            print("✅ [CAR DB] Conexão via Pooler OK!")
        except Exception as e2:
            print(f"❌ [CAR DB] Pooler também falhou: {e2}")
            car_engine = create_engine(car_db_url, pool_pre_ping=True, connect_args={'connect_timeout': 10})
    else:
        car_engine = create_engine(car_db_url, pool_pre_ping=True, connect_args={'connect_timeout': 10})

CarSessionLocal = sessionmaker(bind=car_engine)

def init_db():
    """Initialize database connections and perform essential migrations."""
    try:
        Base.metadata.create_all(engine)
        print("✅ [DB] Base.metadata.create_all executado (tabelas verificadas/criadas).", flush=True)
    except Exception as e:
        import traceback
        # IMPORTANTE: se create_all falhar (ex.: FK/coluna incompatível em qualquer
        # tabela do Base, incluindo CdaEvent/CdaLotResult), as tabelas que ainda não
        # existem podem nunca ser criadas — e o erro ficava mascarado como um simples
        # aviso. Logamos o traceback completo para não perder esse sinal de novo.
        print(f"⚠️ Main DB Note: {e}\n{traceback.format_exc()}", flush=True)
    
    try:
        with car_engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis;"))
            if hasattr(conn, 'commit'):
                conn.commit()
    except Exception as e:
        print(f"⚠️ CAR DB Note: {e}")

    try:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE users ALTER COLUMN chat_id TYPE TEXT USING chat_id::text;"))
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS platform VARCHAR DEFAULT 'telegram';"))
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS plan_type VARCHAR DEFAULT 'FREE';"))
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS stripe_subscription_id VARCHAR;"))
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS trial_expires_at TIMESTAMP;"))
            conn.execute(text("ALTER TABLE activity_logs ADD COLUMN IF NOT EXISTS trigger_type VARCHAR DEFAULT 'USER_REQUEST';"))
            conn.execute(text("ALTER TABLE cda_lot_results ADD COLUMN IF NOT EXISTS qtde_animals INTEGER;"))
            conn.execute(text("ALTER TABLE cda_lot_results ADD COLUMN IF NOT EXISTS scrape_mode VARCHAR DEFAULT 'individual';"))
            conn.execute(text("ALTER TABLE cda_lot_results ADD COLUMN IF NOT EXISTS price_per_kg_brl FLOAT;"))
            conn.execute(text("ALTER TABLE cda_market_comparisons ADD COLUMN IF NOT EXISTS avg_cda_price_per_kg_brl FLOAT;"))
            conn.execute(text("ALTER TABLE cda_market_comparisons ADD COLUMN IF NOT EXISTS usd_brl_rate FLOAT;"))
            # Backfill price_per_kg_brl de era_raw ("R$ 9,10" → 9.10) para dados existentes
            conn.execute(text("""
                UPDATE cda_lot_results
                SET price_per_kg_brl = NULLIF(
                    REGEXP_REPLACE(
                        REPLACE(REPLACE(REPLACE(era_raw, 'R$', ''), ' ', ''), '.', ''),
                        ',', '.', 'g'
                    ), ''
                )::FLOAT
                WHERE era_raw ~ 'R\\$\\s*[0-9]+,[0-9]+'
                  AND (price_per_kg_brl IS NULL OR price_per_kg_brl < 1.0)
            """))
            # Limpa valores fora da faixa realista 5-100 R$/kg (reprodutores, muares, etc.)
            conn.execute(text("""
                UPDATE cda_lot_results
                SET price_per_kg_brl = NULL
                WHERE price_per_kg_brl IS NOT NULL
                  AND (price_per_kg_brl <= 5.0 OR price_per_kg_brl >= 100.0)
            """))
            
            # Promoção automática do Administrador para PRO
            admin_id = str(Config.ADMIN_CHAT_ID)
            conn.execute(text(f"UPDATE users SET plan_type = 'PRO' WHERE chat_id = '{admin_id}'"))
            # Tentativa para WhatsApp (Robson)
            conn.execute(text(f"UPDATE users SET plan_type = 'PRO' WHERE chat_id = '556784013193'"))
            
            # FIX: Garantir que usuários com chat_id numérico longo (telefone) tenham platform='whatsapp'
            # Telefones brasileiros com DDI: 55 + DDD(2) + número(8-9) = 12-13 dígitos
            result = conn.execute(text(
                "UPDATE users SET platform = 'whatsapp' "
                "WHERE platform IS NULL OR (platform = 'telegram' AND LENGTH(chat_id) >= 11 AND chat_id ~ '^[0-9]+$')"
            ))
            print(f"✅ [Migration] Fixed WhatsApp platform for users with phone-number chat_ids", flush=True)
            
            if hasattr(conn, 'commit'):
                conn.commit()
    except Exception as e:
        print(f"⚠️ Migration note: {e}")

    try:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE favorite_locations ADD COLUMN IF NOT EXISTS last_ndvi_date TEXT"))
            conn.execute(text("ALTER TABLE favorite_locations ADD COLUMN IF NOT EXISTS ndvi_alerts_enabled BOOLEAN DEFAULT TRUE"))
            if hasattr(conn, 'commit'):
                conn.commit()
    except Exception as e:
        print(f"⚠️ NDVI migration note: {e}")

def log_activity(chat_id, action, platform='whatsapp', details=None, status='SUCCESS', error_message=None, trigger_type='USER_REQUEST', username=None):
    """Auxiliar para registrar ações dos usuários (Analytics)."""
    session = SessionLocal()
    try:
        chat_id_str = str(chat_id)
        user = session.query(User).filter_by(chat_id=chat_id_str).first()
        if not user:
            user = User(chat_id=chat_id_str, platform=platform, username=username)
            session.add(user)
            session.flush()
        else:
            if username and user.username != username:
                user.username = username
            if platform and user.platform != platform:
                user.platform = platform
            # Force PRO for specifically identified admin phone
            if chat_id_str == '556784013193':
                user.plan_type = 'PRO'
            session.flush()
        
        new_log = ActivityLog(
            user_id=chat_id_str,
            action=action,
            platform=platform,
            trigger_type=trigger_type,
            details=details,
            status=status,
            error_message=error_message
        )
        session.add(new_log)
        session.commit()
    except Exception as e:
        print(f"❌ Error logging activity: {e}")
        session.rollback()
    finally:
        session.close()

def get_recent_prices(days=1095):
    session = SessionLocal()
    try:
        cutoff_date = datetime.utcnow() - pd.Timedelta(days=days)
        records = session.query(PriceHistory).filter(PriceHistory.date >= cutoff_date).order_by(PriceHistory.date).all()
        return [{'country': r.country, 'price': r.price, 'date': r.date} for r in records]
    finally:
        session.close()


def get_cda_comparisons(start_date=None, end_date=None, limit=500):
    session = SessionLocal()
    try:
        query = session.query(CdaMarketComparison)
        if start_date is not None:
            query = query.filter(CdaMarketComparison.reference_date >= start_date)
        if end_date is not None:
            query = query.filter(CdaMarketComparison.reference_date <= end_date)
        rows = (
            query.order_by(CdaMarketComparison.reference_date.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "reference_date": r.reference_date,
                "race_norm": r.race_norm,
                "sex_norm": r.sex_norm,
                "era_norm": r.era_norm,
                "avg_cda_price_per_arroba_brl": r.avg_cda_price_per_arroba_brl,
                "avg_cda_closed_price_brl": r.avg_cda_closed_price_brl,
                "lots_count": r.lots_count,
                "scot_country": r.scot_country,
                "scot_price_usd": r.scot_price_usd,
                "cda_to_scot_ratio": r.cda_to_scot_ratio,
            }
            for r in rows
        ]
    finally:
        session.close()


def get_cda_latest_summary(top_n_races: int = 12) -> dict:
    """
    Retorna um dicionário com:
      - 'text': texto formatado com os últimos preços por raça
      - 'event_date': data do último leilão encontrado
      - 'rows': lista bruta de dicts com os dados

    Busca o leilão mais recente na tabela cda_events e agrega
    os preços médios por raça/sexo/era dos lotes desse evento.
    Se não houver dados de evento, usa a última semana de cda_market_comparisons.
    """
    session = SessionLocal()
    try:
        # ── Estratégia 1: usar o último evento real de cda_events ──────────
        last_event = (
            session.query(CdaEvent)
            .filter(CdaEvent.event_date.isnot(None))
            .order_by(CdaEvent.event_date.desc())
            .first()
        )
        if not last_event:
            last_event = (
                session.query(CdaEvent)
                .order_by(CdaEvent.collected_at.desc())
                .first()
            )

        if last_event:
            event_date = last_event.event_date or last_event.collected_at
            # Agrega TODOS os eventos do mesmo dia (ex: leilão principal + reprodutores)
            from datetime import timedelta as _td0
            day_start = event_date.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end   = day_start + _td0(days=1)
            same_day_events = (
                session.query(CdaEvent)
                .filter(
                    func.coalesce(CdaEvent.event_date, CdaEvent.collected_at) >= day_start,
                    func.coalesce(CdaEvent.event_date, CdaEvent.collected_at) <  day_end,
                )
                .all()
            )
            event_ids = [e.id for e in same_day_events]

            # Lotes de todos os eventos do dia
            lots = (
                session.query(CdaLotResult)
                .filter(CdaLotResult.event_id.in_(event_ids))
                .all()
            )

            # Metadado: evento com mais lotes = leilão principal (não o de reprodutores)
            _lot_count = {}
            for _l in lots:
                _lot_count[_l.event_id] = _lot_count.get(_l.event_id, 0) + 1
            last_event = max(same_day_events, key=lambda e: _lot_count.get(e.id, 0))

            if lots:
                # Agrupa por raça e calcula médias, totais de cabeças e volume
                from collections import defaultdict
                import re as _re
                # R$/kg é a métrica primária — direto do scraper (era_raw = tds[7] "R$/kg vivo")
                # Para @ quando necessário: animais de abate (VACA, TOUROS) = peso/30 (rend. carcaça ~50%)
                #                          animais jovens = peso/15 (peso vivo)
                race_data = defaultdict(lambda: {'kg_prices': [], 'lots': 0, 'heads': 0, 'volume': 0.0})
                total_heads = 0
                total_volume = 0.0

                def _parse_kg_price(lot) -> float | None:
                    """R$/kg vivo — usa era_raw (col R$/kg do site) ou calcula de closed/weight."""
                    if lot.era_raw:
                        try:
                            kg_txt = _re.sub(r"[^0-9,.]", "", lot.era_raw)
                            if "," in kg_txt:
                                kg_txt = kg_txt.replace(".", "").replace(",", ".")
                            v = float(kg_txt)
                            if 5.0 < v < 100.0:
                                return round(v, 2)
                        except (ValueError, TypeError):
                            pass
                    if lot.closed_price_brl and lot.weight_kg and lot.weight_kg > 0:
                        v = lot.closed_price_brl / lot.weight_kg
                        if 5.0 < v < 100.0:
                            return round(v, 2)
                    return None

                seen_hashes: set = set()
                for lot in lots:
                    key = (lot.race_raw or 'Não informado').strip()
                    if lot.hash_key in seen_hashes:
                        continue
                    seen_hashes.add(lot.hash_key)
                    kg_price = _parse_kg_price(lot)
                    if kg_price:
                        race_data[key]['kg_prices'].append(kg_price)
                    race_data[key]['lots'] += 1
                    qty = lot.qtde_animals or 0
                    if qty:
                        race_data[key]['heads'] += qty
                        total_heads += qty
                    if lot.closed_price_brl:
                        lot_value = lot.closed_price_brl * (qty if qty else 1)
                        race_data[key]['volume'] += lot_value
                        total_volume += lot_value

                # Busca dados Scot para a data do evento (±3 dias) para enriquecer rows
                from datetime import timedelta as _td
                comparisons = (
                    session.query(CdaMarketComparison)
                    .filter(
                        CdaMarketComparison.reference_date >= event_date - _td(days=3),
                        CdaMarketComparison.reference_date <= event_date + _td(days=3),
                    )
                    .all()
                )
                def _nl(v):
                    if not v: return None
                    t = _re.sub(r"\s+", " ", str(v)).strip().lower()
                    for c, r in [("ç","c"),("ã","a"),("á","a"),("â","a"),("é","e"),
                                 ("ê","e"),("í","i"),("ó","o"),("ô","o"),("õ","o"),("ú","u")]:
                        t = t.replace(c, r)
                    return t or None
                scot_map = {}
                for c in comparisons:
                    rk = _nl(c.race_norm)
                    if rk and c.scot_price_usd and rk not in scot_map:
                        scot_map[rk] = {'scot_price_usd': c.scot_price_usd, 'ratio': c.cda_to_scot_ratio}

                rows = []
                for race, data in race_data.items():
                    kp = data['kg_prices']
                    if not kp:
                        continue
                    avg_kg = sum(kp) / len(kp)
                    scot_info = scot_map.get(_nl(race), {})
                    rows.append({
                        'race': race,
                        'avg_price_kg': avg_kg,
                        'lots_count': data['lots'],
                        'heads_count': data['heads'],
                        'scot_price_usd': scot_info.get('scot_price_usd'),
                        'ratio': scot_info.get('ratio'),
                    })

                # Ordena por lotes desc → dentro do mesmo nº de lotes, por preço/kg
                rows.sort(key=lambda x: (x['lots_count'], x['avg_price_kg']), reverse=True)
                rows = rows[:top_n_races]

                return {
                    'event_name': last_event.event_name or 'Leilão CDA',
                    'event_date': event_date,
                    'event_location': last_event.event_location or '',
                    'event_url': last_event.source_url,
                    'total_heads': total_heads if total_heads > 0 else None,
                    'total_volume_brl': total_volume if total_volume > 0 else None,
                    'has_recent_data': (datetime.utcnow() - event_date).days <= 3,
                    'rows': rows,
                    'source': 'event',
                }

        # ── Estratégia 2: fallback para cda_market_comparisons ────────────
        from datetime import timedelta
        cutoff = datetime.utcnow() - timedelta(days=90)
        comparisons = (
            session.query(CdaMarketComparison)
            .filter(CdaMarketComparison.reference_date >= cutoff)
            .order_by(CdaMarketComparison.reference_date.desc())
            .limit(100)
            .all()
        )

        if not comparisons:
            return {'event_name': None, 'event_date': None, 'rows': [], 'source': 'empty'}

        # Data mais recente nos comparativos
        latest_date = comparisons[0].reference_date

        # Filtrar apenas registros do mesmo dia mais recente
        same_day = [c for c in comparisons
                    if c.reference_date and
                    abs((c.reference_date - latest_date).days) <= 3]

        rows = []
        for c in same_day:
            if c.avg_cda_price_per_arroba_brl:
                rows.append({
                    'race': c.race_norm or 'Outros',
                    'avg_price_arroba': c.avg_cda_price_per_arroba_brl,
                    'lots_count': c.lots_count or 0,
                    'scot_price_usd': c.scot_price_usd,
                    'ratio': c.cda_to_scot_ratio,
                })

        rows.sort(key=lambda x: x['avg_price_arroba'], reverse=True)
        rows = rows[:top_n_races]

        return {
            'event_name': 'Leilão CDA',
            'event_date': latest_date,
            'event_location': '',
            'rows': rows,
            'source': 'comparison',
        }

    finally:
        session.close()


def format_cda_summary_text(summary: dict, for_whatsapp: bool = False) -> str:
    """Texto do evento: nome, data, stats e link — enviado após o card de preços."""
    if not summary or not summary.get('rows'):
        return (
            "⚠️ Ainda não há dados do Leilão Correa da Costa disponíveis.\n"
            "Os dados são coletados automaticamente às 05h30 todos os dias."
        )

    def _brl(v, dec=0):
        s = f"{v:,.{dec}f}"
        return s.replace(",", "X").replace(".", ",").replace("X", ".")

    bold = lambda s: f"*{s}*"

    event_name   = summary.get('event_name') or 'Leilão CDA'
    event_date   = summary.get('event_date')
    location     = summary.get('event_location') or ''
    event_url    = summary.get('event_url') or ''
    total_heads  = summary.get('total_heads')
    total_volume = summary.get('total_volume_brl')

    date_str = event_date.strftime('%d/%m/%Y') if event_date else 'data não informada'
    loc_str  = f" — {location}" if location else ''

    # Linha de stats: média/animal | cabeças | volume total
    stats_parts = []
    if total_heads and total_volume:
        media = total_volume / total_heads
        stats_parts.append(f"R$ {_brl(media, 0)}/animal")
    if total_heads:
        stats_parts.append(f"🐄 {int(total_heads):,} cabeças".replace(",", "."))
    if total_volume:
        stats_parts.append(f"💰 R$ {_brl(total_volume, 0)}")
    stats_line = (" | ".join(stats_parts) + "\n") if stats_parts else ""

    if for_whatsapp:
        footer = (
            f"\nFonte: Correa da Costa Agropecuária\n"
            + (f"{event_url}\n" if event_url else "")
            + "Agro Analytics Bot"
        )
    else:
        footer = (
            f"\n_Fonte: Correa da Costa Agropecuária_\n"
            + (f"{event_url}\n" if event_url else "")
            + "_Agro Analytics Bot_"
        )

    return (
        f"🐂 {bold(event_name)}{loc_str}\n"
        f"📅 Data: {date_str}\n"
        f"{stats_line}"
        f"{footer}"
    )


def format_cda_chart_legend(summary: dict) -> str:
    """Legenda do gráfico histórico — enviada após a imagem do gráfico."""
    event_date = summary.get('event_date') if summary else None
    date_str = event_date.strftime('%d/%m/%Y') if event_date else '—'
    return (
        f"📈 Último leilão: {date_str}\n\n"
        f"• Linhas = preço médio R$/kg vivo por categoria\n"
        f"• Tracejado azul = Scot Brasil (US$/cab., eixo direito)\n"
        f"• Barras = lotes negociados/semana"
    )

