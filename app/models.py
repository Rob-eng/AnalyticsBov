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
            print("DEBUG: Switching to Regional Connection Pooler (aws-0-sa-east-1) for IPv4 support.")
            
            # 1. Extract Project ID from Hostname
            try:
                # db.project_id.supabase.co
                parts = hostname.split('.')
                project_id = parts[1]
                print(f"DEBUG: Extracted Project ID: {project_id}")
            except IndexError:
                print(f"DEBUG: Could not extract verified project ID from {hostname}")
                project_id = None

            # 2. Update Username (Format: user.project_id)
            current_user = parsed.username
            current_password = parsed.password
            current_port = 6543 # Transaction Mode
            
            print(f"DEBUG: Original Username: {current_user}")
            
            new_user = current_user
            if project_id and project_id not in current_user:
                new_user = f"{current_user}.{project_id}"
                print(f"DEBUG: Updated username to {new_user} for pooler routing")
            
            # Rebuild netloc: user:pass@host:port
            # TRYING SA-EAST-1 First (São Paulo)
            target_host = "aws-0-sa-east-1.pooler.supabase.com"
            new_netloc = f"{new_user}:{current_password}@{target_host}:{current_port}"
            
            car_db_url_pooler = urlunparse(parsed._replace(netloc=new_netloc))
            
            # Disable prepared statements for transaction pooler compatibility
            car_engine = create_engine(
                car_db_url_pooler, 
                pool_pre_ping=True, 
                connect_args={'connect_timeout': 10}
            )
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
