from sqlalchemy import Column, Integer, String, Float, DateTime, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
from app.config import Config

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    
    chat_id = Column(Integer, primary_key=True)
    username = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

class PriceHistory(Base):
    __tablename__ = 'price_history'
    
    id = Column(Integer, primary_key=True)
    country = Column(String)
    price = Column(Float)
    date = Column(DateTime, default=datetime.utcnow)

engine = create_engine(Config.DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

def init_db():
    Base.metadata.create_all(engine)
