#!/usr/bin/env python3
"""
Database rebuild script for cases where migration fails.
This will backup existing data and recreate the table with the correct structure.
"""
import sys
import os
import json
from datetime import datetime

# Add the app directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))

from app.core.config import load_settings
from app.db.session import engine
from app.db.models import Case
from app.db.session import Base
from sqlalchemy import text
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def backup_existing_data():
    """Backup existing data from the cases table."""
    logger.info("Backing up existing data...")
    
    try:
        with engine.connect() as connection:
            # Check if table exists and has data
            try:
                result = connection.execute(text("SELECT * FROM cases"))
                rows = result.fetchall()
                columns = result.keys()
                
                if not rows:
                    logger.info("No existing data to backup.")
                    return []
                
                # Convert to list of dictionaries
                backup_data = []
                for row in rows:
                    row_dict = {}
                    for i, col in enumerate(columns):
                        value = row[i]
                        # Handle JSON fields
                        if col in ['associated_parties', 'associated_parties_data', 'processed_documents_summary'] and value:
                            try:
                                # Try to parse as JSON if it's a string
                                if isinstance(value, str):
                                    value = json.loads(value)
                            except:
                                pass  # Keep as is if not valid JSON
                        row_dict[col] = value
                    backup_data.append(row_dict)
                
                # Save backup to file
                backup_filename = f"cases_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
                with open(backup_filename, 'w') as f:
                    json.dump(backup_data, f, indent=2, default=str)
                
                logger.info(f"Backed up {len(backup_data)} records to {backup_filename}")
                return backup_data
                
            except Exception as e:
                if "no such table" in str(e).lower():
                    logger.info("Cases table doesn't exist yet. No backup needed.")
                    return []
                else:
                    raise e
                    
    except Exception as e:
        logger.error(f"Error backing up data: {e}")
        raise

def recreate_table():
    """Drop and recreate the cases table with correct structure."""
    logger.info("Recreating cases table...")
    
    try:
        with engine.connect() as connection:
            # Drop table if it exists
            connection.execute(text("DROP TABLE IF EXISTS cases"))
            connection.commit()
            logger.info("Dropped existing cases table.")
            
            # Create new table with correct structure
            Base.metadata.create_all(bind=engine)
            logger.info("Created new cases table with correct structure.")
            
    except Exception as e:
        logger.error(f"Error recreating table: {e}")
        raise

def restore_data(backup_data):
    """Restore data to the new table structure."""
    if not backup_data:
        logger.info("No data to restore.")
        return
    
    logger.info(f"Restoring {len(backup_data)} records...")
    
    try:
        from app.db.session import SessionLocal
        from app.db.models import Case
        
        db = SessionLocal()
        
        restored_count = 0
        error_count = 0
        
        for row_data in backup_data:
            try:
                # Create new Case object with available fields
                case_kwargs = {}
                
                # Map old field names to new ones if needed
                field_mapping = {
                    'case_number': 'case_number',
                    'case_name_for_search': 'case_name_for_search', 
                    'input_creditor_name': 'input_creditor_name',
                    'is_business': 'is_business',
                    'creditor_type': 'creditor_type',
                }
                
                # Required fields with defaults
                required_defaults = {
                    'case_number': f"MIGRATED_{restored_count}",
                    'case_name_for_search': 'Migrated Case',
                    'input_creditor_name': 'Unknown Creditor',
                    'is_business': False,
                    'creditor_type': 'Unknown'
                }
                
                # Set required fields
                for req_field, default_value in required_defaults.items():
                    if req_field in row_data and row_data[req_field] is not None:
                        case_kwargs[req_field] = row_data[req_field]
                    else:
                        case_kwargs[req_field] = default_value
                        logger.warning(f"Using default value for missing required field {req_field}")
                
                # Set optional fields
                optional_fields = [
                    'unicourt_case_name_on_page', 'unicourt_actual_case_number_on_page',
                    'case_url_on_unicourt', 'status', 'last_submitted_at',
                    'original_creditor_name_from_doc', 'original_creditor_name_source_doc_title',
                    'creditor_address_from_doc', 'creditor_address_source_doc_title',
                    'associated_parties', 'associated_parties_data',
                    'creditor_registration_state_from_doc', 'creditor_registration_state_source_doc_title',
                    'final_judgment_awarded_to_creditor', 'final_judgment_awarded_source_doc_title',
                    'final_judgment_awarded_to_creditor_context',
                    'processed_documents_summary'
                ]
                
                for field in optional_fields:
                    if field in row_data and row_data[field] is not None:
                        case_kwargs[field] = row_data[field]
                
                # Create and save the case
                case = Case(**case_kwargs)
                db.add(case)
                restored_count += 1
                
            except Exception as e:
                logger.error(f"Error restoring record {restored_count}: {e}")
                error_count += 1
                continue
        
        # Commit all changes
        db.commit()
        db.close()
        
        logger.info(f"Restored {restored_count} records successfully. {error_count} errors.")
        
    except Exception as e:
        logger.error(f"Error restoring data: {e}")
        raise

def main():
    print("=" * 60)
    print("UniCourt Database Rebuild Script")
    print("=" * 60)
    print()
    print("WARNING: This will recreate the cases table!")
    print("Make sure you have a backup of your database before proceeding.")
    print()
    
    response = input("Do you want to continue? (yes/no): ").strip().lower()
    if response not in ['yes', 'y']:
        print("Operation cancelled.")
        return 0
    
    try:
        # Load settings
        load_settings()
        
        # Backup existing data
        backup_data = backup_existing_data()
        
        # Recreate table
        recreate_table()
        
        # Restore data
        restore_data(backup_data)
        
        print()
        print("✓ Database rebuild completed successfully!")
        print("Your application should now work correctly.")
        
        return 0
        
    except Exception as e:
        print(f"✗ Error during rebuild: {e}")
        return 1

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
