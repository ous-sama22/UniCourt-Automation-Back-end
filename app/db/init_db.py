# app/db/init_db.py
import logging
from app.db.session import engine, Base
from app.db.models import Case # Only Case model now

logger = logging.getLogger(__name__)

def init_db():
    logger.info("Initializing database...")
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created/verified successfully (if they didn't exist or schema matched).")
    except Exception as e:
        logger.error(f"Error creating database tables: {e}")
        raise

if __name__ == "__main__":
    from app.core.config import load_settings, settings as app_settings # Ensure settings are loaded
    load_settings() 
    logger.info(f"Manual DB Init: Using database at {app_settings.DATABASE_URL}")
    init_db()