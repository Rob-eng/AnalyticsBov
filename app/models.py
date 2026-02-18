from sqlalchemy import Column, Integer, BigInteger, String, Float, DateTime, create_engine, text, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
import pandas as pd
from geoalchemy2 import Geometry
from app.config import Config

Base = declarative_base()

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

class CARProperty(Base):
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

engine = create_engine(db_url)
SessionLocal = sessionmaker(bind=engine)

def init_db():
    # Fix for SQLAlchemy requiring 'postgresql://' instead of 'postgres://'
    db_engine = engine
    
    with db_engine.connect() as conn:
        try:
            # Enable PostGIS extension
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis;"))
            if hasattr(conn, 'commit'):
                conn.commit()
            print("✅ PostGIS extension verified")
        except Exception as e:
            print(f"ℹ️ PostGIS notice: {e}")

    Base.metadata.create_all(db_engine)
    # Forced migration to BIGINT for Telegram IDs
    with db_engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE users ALTER COLUMN chat_id TYPE TEXT USING chat_id::text;"))
            if hasattr(conn, 'commit'):
                conn.commit()
            print("✅ Database migration components verified")
        except Exception as e:
            print(f"ℹ️ Migration notice: {e}")

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
