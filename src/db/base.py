from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from .models import Base
from src.config import settings

engine = create_engine(settings.dsn, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

def init_db():
    Base.metadata.create_all(engine)
