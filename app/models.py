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
    print("Environment variables present:", list(os.environ.keys()))
    raise ValueError("A variável de ambiente DATABASE_URL não está definida. Verifique as configurações no Railway.")

# Fix for SQLAlchemy requiring 'postgresql://' instead of 'postgres://'
db_url = Config.DATABASE_URL
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

engine = create_engine(db_url, pool_pre_ping=True, connect_args={'connect_timeout': 10})
SessionLocal = sessionmaker(bind=engine)

# Secondary engine for CAR spatial data (Supabase)
car_db_url = Config.CAR_DATABASE_URL or db_url # Fallback to main if dual not set
if car_db_url and car_db_url.startswith("postgres://"):
    car_db_url = car_db_url.replace("postgres://", "postgresql://", 1)

print(f"DEBUG: Main DB URL (masked): {db_url.split('@')[-1] if db_url else 'None'}")
print(f"DEBUG: CAR DB URL (masked): {car_db_url.split('@')[-1] if car_db_url else 'None'}")

if car_db_url == db_url:
    print("DEBUG: Using same engine for both databases.")
    car_engine = engine
else:
    print("DEBUG: Creating separate engine for CAR database.")
    
    # Force IPv4 resolution for Supabase
    try:
        import socket
        from urllib.parse import urlparse, urlunparse
        
        parsed = urlparse(car_db_url)
        hostname = parsed.hostname
        
        # Resolve to IPv4 using getaddrinfo to filter for AF_INET
        # This is more robust than gethostbyname in some environments
        addr_info = socket.getaddrinfo(hostname, None, family=socket.AF_INET)
        
        if addr_info:
            # Take the first available IPv4 address
            # addr_info returns list of (family, type, proto, canonname, sockaddr)
            # sockaddr is (address, port) for AF_INET
            ipv4 = addr_info[0][4][0]
            print(f"DEBUG: Resolved {hostname} to {ipv4} (System DNS)")
            
            # Reconstruct URL with IPv4
            new_netloc = parsed.netloc.replace(hostname, ipv4)
            car_db_url_ipv4 = urlunparse(parsed._replace(netloc=new_netloc))
            
            car_engine = create_engine(car_db_url_ipv4, pool_pre_ping=True, connect_args={'connect_timeout': 10})
        else:
            raise ValueError("No IPv4 from System DNS")

    except Exception as e:
        print(f"DEBUG: System DNS failed for IPv4: {e}")
        
        # Fallback: Use Regional Supabase Connection Pooler (Supavisor)
        # This endpoint resolves to IPv4 and supports transaction mode (6543)
        # We replace the project-specific hostname with the regional pooler hostname.
        # User/Pass/DB info remains in the URL and handles routing.
        if "supabase.co" in car_db_url:
            print("DEBUG: Switching to Regional Connection Pooler (Supavisor) for IPv4 support.")
            
            # Extract Project ID
            try:
                parts = hostname.split('.')
                project_id = parts[1] # db.project_id.supabase.co
                print(f"DEBUG: Extracted Project ID: {project_id}")
            except IndexError:
                print(f"DEBUG: Could not extract verified project ID from {hostname}")
                project_id = None

            # Base credentials
            current_user = parsed.username
            current_password = parsed.password
            current_port = 6543 # Transaction Mode
            
            # Prepare Username (Format: user.project_id)
            new_user = current_user
            if project_id and project_id not in current_user:
                new_user = f"{current_user}.{project_id}"
            
            # List of regions to try (Priority: SA -> US East -> US West -> EU)
            regions = [
                'sa-east-1', 
                'us-east-1', 
                'us-west-1', 
                'us-west-2', # Oregon (Likely location based on IP)
                'eu-central-1',
                'ap-southeast-1'
            ]
            connected = False
            
            for region in regions:
                try:
                    target_host = f"aws-0-{region}.pooler.supabase.com"
                    print(f"DEBUG: Testing Region: {region} ({target_host})...")
                    
                    new_netloc = f"{new_user}:{current_password}@{target_host}:{current_port}"
                    candidate_url = urlunparse(parsed._replace(netloc=new_netloc))
                    
                    # Create temporary engine to test connection
                    temp_engine = create_engine(
                        candidate_url, 
                        pool_pre_ping=True, 
                        connect_args={'connect_timeout': 3}
                    )
                    
                    # Force connection attempt
                    with temp_engine.connect() as conn:
                        print(f"✅ SUCCESS! Connected to {region}")
                    
                    # If successful, use this engine
                    car_engine = temp_engine
                    connected = True
                    break
                    
                except Exception as e:
                    # Log as debug/warning instead of error since we expect failures
                    print(f"DEBUG: Skipped {region}: {str(e).split('FATAL')[0].strip()}...", flush=True)
            
            if not connected:
                print("⚠️ All regions failed. Falling back to original URL (likely to fail on IPv6).")
                car_engine = create_engine(car_db_url, pool_pre_ping=True, connect_args={'connect_timeout': 10})

        else:
            # Standard fallback for non-supabase
            car_engine = create_engine(car_db_url, pool_pre_ping=True, connect_args={'connect_timeout': 10})

CarSessionLocal = sessionmaker(bind=car_engine)

def init_db():
    """Initialize database connections and perform essential migrations."""
    # 1. Initialize Main DB (Railway - Users/Prices)
    try:
        # Standard tables creation
        Base.metadata.create_all(engine)
    except Exception as e:
        print(f"⚠️ Main DB Note: {e}")
    
    # 2. Check CAR DB connection and enable PostGIS
    try:
        with car_engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis;"))
            if hasattr(conn, 'commit'):
                conn.commit()
    except Exception as e:
        print(f"⚠️ CAR DB Note: {e}")

    # 3. Essential migrations (idempotent)
    try:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE users ALTER COLUMN chat_id TYPE TEXT USING chat_id::text;"))
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS platform VARCHAR DEFAULT 'telegram';"))
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS plan_type VARCHAR DEFAULT 'FREE';"))
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS stripe_subscription_id VARCHAR;"))
            
            conn.execute(text("ALTER TABLE activity_logs ADD COLUMN IF NOT EXISTS trigger_type VARCHAR DEFAULT 'USER_REQUEST';"))
            
            if hasattr(conn, 'commit'):
                conn.commit()
    except Exception as e:
        print(f"⚠️ Migration note: {e}")

    # 4. NDVI alert columns (safe ADD IF NOT EXISTS)
    try:
        with engine.connect() as conn:
            conn.execute(text(
                "ALTER TABLE favorite_locations "
                "ADD COLUMN IF NOT EXISTS last_ndvi_date TEXT"
            ))
            conn.execute(text(
                "ALTER TABLE favorite_locations "
                "ADD COLUMN IF NOT EXISTS ndvi_alerts_enabled BOOLEAN DEFAULT TRUE"
            ))
            if hasattr(conn, 'commit'):
                conn.commit()
        print("✓ NDVI alert columns ensured.")
    except Exception as e:
        print(f"⚠️ NDVI column migration note: {e}")

def log_activity(chat_id, action, platform='whatsapp', details=None, status='SUCCESS', error_message=None, trigger_type='USER_REQUEST', username=None):
    """Auxiliar para registrar ações dos usuários (Analytics)."""
    session = SessionLocal()
    try:
        # 1. Garante que o User existe e atualiza o Nome se enviado
        user = session.query(User).filter_by(chat_id=chat_id).first()
        if not user:
            user = User(chat_id=chat_id, platform=platform, username=username)
            session.add(user)
            session.flush()
        elif username and not user.username:
            user.username = username # Sincroniza o nome se estiver vazio
            session.flush()
        
        # 2. Registra o Log
        new_log = ActivityLog(
            user_id=chat_id,
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
    """Retrieve price history for the last N days (default 3 years)."""
    session = SessionLocal()
    try:
        cutoff_date = datetime.utcnow() - pd.Timedelta(days=days)
        records = session.query(PriceHistory).filter(PriceHistory.date >= cutoff_date).order_by(PriceHistory.date).all()
        return [
            {'country': r.country, 'price': r.price, 'date': r.date}
            for r in records
        ]
    except Exception as e:
        print(f"Error fetching history: {e}")
        return []
    finally:
        session.close()
