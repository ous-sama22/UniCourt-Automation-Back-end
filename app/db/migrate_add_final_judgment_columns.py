# app/db/migrate_add_final_judgment_columns.py
"""
Migration script to add final_judgment_awarded_to_creditor and 
final_judgment_awarded_source_doc_title columns to the cases table.
Also ensures all other required columns exist.
"""
import logging
from sqlalchemy import text
from app.db.session import engine
from app.core.config import load_settings

logger = logging.getLogger(__name__)

def migrate_add_final_judgment_columns():
    """Add the new final judgment columns and any other missing columns to the cases table."""
    
    logger.info("Starting comprehensive database migration...")
    
    # Define all expected columns and their types
    expected_columns = {
        'id': 'INTEGER PRIMARY KEY',
        'case_number': 'VARCHAR UNIQUE NOT NULL',
        'case_name_for_search': 'VARCHAR NOT NULL',
        'input_creditor_name': 'VARCHAR NOT NULL',
        'is_business': 'BOOLEAN NOT NULL',
        'creditor_type': 'VARCHAR NOT NULL',
        'unicourt_case_name_on_page': 'VARCHAR',
        'unicourt_actual_case_number_on_page': 'VARCHAR',
        'case_url_on_unicourt': 'VARCHAR',
        'status': 'VARCHAR DEFAULT "Queued" NOT NULL',
        'last_submitted_at': 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP',
        'original_creditor_name_from_doc': 'VARCHAR',
        'original_creditor_name_source_doc_title': 'VARCHAR',
        'creditor_address_from_doc': 'TEXT',
        'creditor_address_source_doc_title': 'VARCHAR',
        'associated_parties': 'JSON',
        'associated_parties_data': 'JSON',
        'creditor_registration_state_from_doc': 'VARCHAR',
        'creditor_registration_state_source_doc_title': 'VARCHAR',
        'final_judgment_awarded_to_creditor': 'VARCHAR',
        'final_judgment_awarded_source_doc_title': 'VARCHAR',
        'processed_documents_summary': 'JSON'
    }
    
    try:
        with engine.connect() as connection:
            # Check if the cases table exists
            table_exists_result = connection.execute(text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='cases'"
            ))
            table_exists = table_exists_result.fetchone() is not None
            
            if not table_exists:
                logger.info("Cases table doesn't exist. Creating it with all required columns...")
                # Create the full table with all columns
                create_table_sql = """
                CREATE TABLE cases (
                    id INTEGER PRIMARY KEY,
                    case_number VARCHAR UNIQUE NOT NULL,
                    case_name_for_search VARCHAR NOT NULL,
                    input_creditor_name VARCHAR NOT NULL,
                    is_business BOOLEAN NOT NULL,
                    creditor_type VARCHAR NOT NULL,
                    unicourt_case_name_on_page VARCHAR,
                    unicourt_actual_case_number_on_page VARCHAR,
                    case_url_on_unicourt VARCHAR,
                    status VARCHAR DEFAULT 'Queued' NOT NULL,
                    last_submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    original_creditor_name_from_doc VARCHAR,
                    original_creditor_name_source_doc_title VARCHAR,
                    creditor_address_from_doc TEXT,
                    creditor_address_source_doc_title VARCHAR,
                    associated_parties JSON,
                    associated_parties_data JSON,
                    creditor_registration_state_from_doc VARCHAR,
                    creditor_registration_state_source_doc_title VARCHAR,
                    final_judgment_awarded_to_creditor VARCHAR,
                    final_judgment_awarded_source_doc_title VARCHAR,
                    processed_documents_summary JSON
                )
                """
                connection.execute(text(create_table_sql))
                connection.commit()
                logger.info("Cases table created successfully with all columns.")
                return True
            
            # Table exists, check which columns are missing
            cursor = connection.execute(text("PRAGMA table_info(cases)"))
            existing_columns = [row[1] for row in cursor.fetchall()]  # row[1] is column name
            
            missing_columns = []
            for column_name, column_def in expected_columns.items():
                if column_name not in existing_columns:
                    missing_columns.append((column_name, column_def))
            
            if not missing_columns:
                logger.info("All required columns already exist. No migration needed.")
                return True
                
            # Add missing columns
            for column_name, column_def in missing_columns:
                # For ALTER TABLE, we need simpler column definitions
                if column_name == 'id':
                    continue  # Skip ID column for ALTER TABLE
                elif 'DEFAULT' in column_def:
                    # Extract just the type part for ALTER TABLE
                    column_type = column_def.split(' DEFAULT')[0]
                else:
                    column_type = column_def.replace(' NOT NULL', '').replace(' UNIQUE', '')
                
                sql = f"ALTER TABLE cases ADD COLUMN {column_name} {column_type}"
                logger.info(f"Adding column: {column_name} ({column_type})")
                
                try:
                    connection.execute(text(sql))
                    connection.commit()
                except Exception as e:
                    if "duplicate column name" in str(e).lower():
                        logger.info(f"Column {column_name} already exists, skipping.")
                    else:
                        raise e
                
            logger.info(f"Successfully added {len(missing_columns)} missing columns.")
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
