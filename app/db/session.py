# app/db/session.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.core.config import settings # settings should be loaded by now
import logging

logger = logging.getLogger(__name__)

# This will use the DATABASE_URL property from the loaded settings
SQLALCHEMY_DATABASE_URL = settings.DATABASE_URL
logger.info(f"Database URL for SQLAlchemy: {SQLALCHEMY_DATABASE_URL}")


engine = create_engine(
    SQLALCHEMY_DATABASE_URL, 
    connect_args={"check_same_thread": False} # Needed for SQLite with FastAPI
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()