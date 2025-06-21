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
        # First, create tables if they don't exist
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created/verified successfully.")
        
        # Then run any pending migrations
        migrations_success = run_migrations()
        if not migrations_success:
            raise Exception("Database migrations failed")
            
        logger.info("Database initialization completed successfully.")
        
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        raise

if __name__ == "__main__":
    from app.core.config import load_settings, settings as app_settings # Ensure settings are loaded
    load_settings() 
    logger.info(f"Manual DB Init: Using database at {app_settings.DATABASE_URL}")
    init_db()