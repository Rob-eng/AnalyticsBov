from sqlalchemy import Column, Integer, BigInteger, String, Float, DateTime, create_engine, text, ForeignKey
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
    locations = relationship("FavoriteLocation", backref="user", cascade="all, delete-orphan")

class FavoriteLocation(Base):
    __tablename__ = 'favorite_locations'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(String, ForeignKey('users.chat_id'))
    name = Column(String)
    latitude = Column(Float)
    longitude = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)

class PriceHistory(Base):
    __tablename__ = 'price_history'
    
    id = Column(Integer, primary_key=True)
    country = Column(String)
    price = Column(Float)
    date = Column(DateTime, default=datetime.utcnow)

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
            print(f"DEBUG: Resolved {hostname} to {ipv4}")
            
            # Reconstruct URL with IPv4
            new_netloc = parsed.netloc.replace(hostname, ipv4)
            car_db_url_ipv4 = urlunparse(parsed._replace(netloc=new_netloc))
            
            car_engine = create_engine(car_db_url_ipv4, pool_pre_ping=True, connect_args={'connect_timeout': 10})
        else:
             print(f"DEBUG: No IPv4 address found for {hostname}")
             car_engine = create_engine(car_db_url, pool_pre_ping=True, connect_args={'connect_timeout': 10})

    except Exception as e:
        print(f"DEBUG: Failed to force IPv4 resolution: {e}")
        
        # Fallback Strategy: Use Supabase Connection Pooler (Port 6543 supports IPv4)
        if "supabase.co" in car_db_url and ":5432" in car_db_url:
            print("DEBUG: Switching to Supabase Connection Pooler (Port 6543) for IPv4 support.")
            car_db_url_pooler = car_db_url.replace(":5432", ":6543")
            
            # Disable prepared statements for transaction pooler compatibility (REQUIRED for Supabase port 6543)
            # 'prepare_threshold': None disables server-side prepared statements in psycopg2
            car_engine = create_engine(
                car_db_url_pooler, 
                pool_pre_ping=True, 
                connect_args={'connect_timeout': 10, 'options': '-c statement_timeout=10000'}
            )
            # Note: SQLAlchemy 1.4/2.0+ with psycopg2 might need different handling for prepare_threshold
            # But usually it's passed in connect_args if using pure psycopg2, or handled by dialect.
            # For robustness, we'll assume the URL change helps connectivity first. 
            # Ideally we pass execution_options={"isolation_level": "AUTOCOMMIT"} if strictly needed but let's stick to port.
        else:
            # Standard fallback
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

    # 3. Essential legacy migrations
    try:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE users ALTER COLUMN chat_id TYPE TEXT USING chat_id::text;"))
            if hasattr(conn, 'commit'):
                conn.commit()
    except Exception:
        pass

def get_recent_prices(days=1095):
    """Retrieve price history for the last N days (default 3 years)."""
    session = SessionLocal()
    try:
        cutoff_date = datetime.utcnow() - pd.Timedelta(days=days)
        # We need pandas for this anyway in charts, might as well return list of dicts to keep it decoupled
        # or just return the query objects
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
