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
    closed_price_brl = Column(Float, nullable=True)
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

    avg_cda_price_per_arroba_brl = Column(Float, nullable=True)
    avg_cda_closed_price_brl = Column(Float, nullable=True)
    lots_count = Column(Integer, nullable=False, default=0)

    scot_country = Column(String, nullable=True, index=True)
    scot_price_usd = Column(Float, nullable=True)
    cda_to_scot_ratio = Column(Float, nullable=True)

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
    except Exception as e:
        print(f"⚠️ Main DB Note: {e}")
    
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
            conn.execute(text("ALTER TABLE activity_logs ADD COLUMN IF NOT EXISTS trigger_type VARCHAR DEFAULT 'USER_REQUEST';"))
            
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


def get_cda_latest_summary(top_n_races: int = 8) -> dict:
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

        if last_event and last_event.event_date:
            event_date = last_event.event_date
            # Pega todos os lotes deste evento
            lots = (
                session.query(CdaLotResult)
                .filter(CdaLotResult.event_id == last_event.id)
                .all()
            )

            if lots:
                # Agrupa por raça e calcula médias
                from collections import defaultdict
                race_data = defaultdict(lambda: {'prices': [], 'lots': 0})
                for lot in lots:
                    key = (lot.race_raw or 'Não informado').strip()
                    if lot.price_per_arroba_brl:
                        race_data[key]['prices'].append(lot.price_per_arroba_brl)
                    race_data[key]['lots'] += 1

                rows = []
                for race, data in race_data.items():
                    if data['prices']:
                        avg_price = sum(data['prices']) / len(data['prices'])
                        rows.append({
                            'race': race,
                            'avg_price_arroba': avg_price,
                            'lots_count': data['lots'],
                        })

                rows.sort(key=lambda x: x['avg_price_arroba'], reverse=True)
                rows = rows[:top_n_races]

                return {
                    'event_name': last_event.event_name or 'Leilão CDA',
                    'event_date': event_date,
                    'event_location': last_event.event_location or '',
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
    """
    Formata o dicionário retornado por get_cda_latest_summary() como texto rico.
    for_whatsapp=True → usa *negrito* do WA em vez de Markdown do Telegram.
    """
    if not summary or not summary.get('rows'):
        return (
            "⚠️ Ainda não há dados do Leilão Correa da Costa disponíveis.\n"
            "Os dados são coletados automaticamente às 05h30 todos os dias."
        )

    bold = lambda s: f"*{s}*" if for_whatsapp else f"*{s}*"

    event_name = summary.get('event_name') or 'Leilão CDA'
    event_date = summary.get('event_date')
    location   = summary.get('event_location') or ''

    date_str = event_date.strftime('%d/%m/%Y') if event_date else 'data não informada'
    loc_str  = f" — {location}" if location else ''

    header = (
        f"🐂 {bold(event_name)}{loc_str}\n"
        f"📅 Data: {date_str}\n"
        f"{'─' * 28}\n"
    )

    # Ícones para ranking
    medals = ['🥇', '🥈', '🥉', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣']

    lines = []
    for i, row in enumerate(summary['rows']):
        medal  = medals[i] if i < len(medals) else '▪️'
        race   = (row.get('race') or 'Outros').title()
        price  = row.get('avg_price_arroba', 0)
        lots   = row.get('lots_count', 0)
        ratio  = row.get('ratio')
        scot   = row.get('scot_price_usd')

        line = f"{medal} {bold(race)}: R$ {price:,.2f}/@"
        if lots:
            line += f"  ({lots} lotes)"
        if ratio:
            pct = ratio * 100
            emoji = '🟢' if pct >= 95 else '🟡' if pct >= 85 else '🔴'
            line += f"\n   {emoji} {pct:.1f}% do benchmark Scot"
            if scot:
                line += f" (US$ {scot:.2f}/cab.)"
        lines.append(line)

    footer = (
        f"\n{'─' * 28}\n"
        f"_Fonte: Correa da Costa Agropecuária_\n"
        f"_Gráfico: Agro Analytics Bot_"
    )
    if for_whatsapp:
        footer = (
            f"\n{'─' * 28}\n"
            f"Fonte: Correa da Costa Agropecuária\n"
            f"Agro Analytics Bot"
        )

    return header + '\n'.join(lines) + footer

