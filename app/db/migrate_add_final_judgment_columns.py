# app/db/migrate_add_final_judgment_columns.py
"""
Migration script to add final_judgment_awarded_to_creditor and 
final_judgment_awarded_source_doc_title columns to the cases table.
"""
import logging
from sqlalchemy import text
from app.db.session import engine
from app.core.config import load_settings

logger = logging.getLogger(__name__)

def migrate_add_final_judgment_columns():
    """Add the new final judgment columns to the cases table if they don't exist."""
    
    logger.info("Starting migration to add final judgment columns...")
    
    try:
        with engine.connect() as connection:
            # Check if columns already exist
            cursor = connection.execute(text("PRAGMA table_info(cases)"))
            columns = [row[1] for row in cursor.fetchall()]  # row[1] is column name
            
            columns_to_add = []
            
            if 'final_judgment_awarded_to_creditor' not in columns:
                columns_to_add.append('final_judgment_awarded_to_creditor')
                
            if 'final_judgment_awarded_source_doc_title' not in columns:
                columns_to_add.append('final_judgment_awarded_source_doc_title')
            
            if not columns_to_add:
                logger.info("Final judgment columns already exist. No migration needed.")
                return True
                
            # Add the columns
            for column_name in columns_to_add:
                if column_name == 'final_judgment_awarded_to_creditor':
                    sql = "ALTER TABLE cases ADD COLUMN final_judgment_awarded_to_creditor VARCHAR"
                elif column_name == 'final_judgment_awarded_source_doc_title':
                    sql = "ALTER TABLE cases ADD COLUMN final_judgment_awarded_source_doc_title VARCHAR"
                
                logger.info(f"Adding column: {column_name}")
                connection.execute(text(sql))
                connection.commit()
                
            logger.info(f"Successfully added columns: {', '.join(columns_to_add)}")
            return True
            
    except Exception as e:
        logger.error(f"Error during migration: {e}")
        return False

if __name__ == "__main__":
    # Load settings
    load_settings()
    
    # Run migration
    success = migrate_add_final_judgment_columns()
    if success:
        print("Migration completed successfully!")
    else:
        print("Migration failed!")
        exit(1)
