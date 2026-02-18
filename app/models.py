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
