# app/db/init_db.py
import logging
from app.db.session import engine, Base
from app.db.models import Case # Only Case model now

logger = logging.getLogger(__name__)

def run_migrations():
    """Run any pending database migrations."""
    logger.info("Running database migrations...")
    try:
        from app.db.migrate_add_final_judgment_columns import migrate_add_final_judgment_columns
        
        # Run the final judgment columns migration
        success = migrate_add_final_judgment_columns()
        if not success:
            raise Exception("Final judgment columns migration failed")
            
        logger.info("All migrations completed successfully.")
        return True
        
    except Exception as e:
        logger.error(f"Error running migrations: {e}")
        return False

def init_db():
    logger.info("Initializing database...")
    try:
        # First, run migrations to ensure all columns exist
        migrations_success = run_migrations()
        if not migrations_success:
            logger.warning("Migrations failed, attempting to create tables from scratch...")
            # If migrations fail, try to create tables normally
            Base.metadata.create_all(bind=engine)
            logger.info("Database tables created from model definitions.")
        else:
            # Also run create_all as a safety net to ensure any new tables are created
            Base.metadata.create_all(bind=engine)
            logger.info("Database tables verified after migrations.")
            
        logger.info("Database initialization completed successfully.")
        
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        raise

if __name__ == "__main__":
    from app.core.config import load_settings, settings as app_settings # Ensure settings are loaded
    load_settings() 
    logger.info(f"Manual DB Init: Using database at {app_settings.DATABASE_URL}")
    init_db()