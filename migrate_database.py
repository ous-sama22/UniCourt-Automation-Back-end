#!/usr/bin/env python3
"""
Standalone migration script to add final judgment columns to existing database.
Run this script to update your database schema without losing data.

Usage:
    python migrate_database.py
"""
import sys
import os

# Add the app directory to Python path so we can import modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.core.config import load_settings
from app.db.migrate_add_final_judgment_columns import migrate_add_final_judgment_columns
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

def main():
    print("=" * 60)
    print("UniCourt Database Migration - Final Judgment Columns")
    print("=" * 60)
    print()
    
    try:
        # Load application settings
        print("Loading application settings...")
        load_settings()
        print("✓ Settings loaded successfully")
        print()
        
        # Run migration
        print("Starting database migration...")
        success = migrate_add_final_judgment_columns()
        
        if success:
            print("✓ Migration completed successfully!")
            print()
            print("The following columns have been added to your database:")
            print("  - final_judgment_awarded_to_creditor")
            print("  - final_judgment_awarded_source_doc_title")
            print("  - final_judgment_awarded_to_creditor_context")
            print()
            print("Your existing data has been preserved.")
            print("You can now restart your application to use the new features.")
        else:
            print("✗ Migration failed!")
            print("Please check the logs above for error details.")
            return 1
            
    except Exception as e:
        print(f"✗ Error during migration: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
