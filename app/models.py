from sqlalchemy import Column, Integer, BigInteger, String, Float, DateTime, Boolean, create_engine, text, ForeignKey
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
