# app/db/crud.py
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.db import models as db_models # refers to db_models now
from app.models_api import cases as api_models # for CaseSubmitDetail type hint
from app.utils import common # common utilities
from typing import Optional, List, Dict, Any
import logging
from datetime import datetime
import json # For handling JSON fields

logger = logging.getLogger(__name__)

def get_case_by_case_number(db: Session, case_number: str) -> Optional[db_models.Case]:
    return db.query(db_models.Case).filter(db_models.Case.case_number == case_number).first()

def create_case(db: Session, case_data: api_models.CaseSubmitDetail) -> db_models.Case:
    db_case = db_models.Case(
        case_number=case_data.case_number_for_db_id.strip(),
        case_name_for_search=case_data.case_name_for_search.strip(),
        input_creditor_name=case_data.input_creditor_name.strip(),
        is_business=case_data.is_business,
        creditor_type=case_data.creditor_type.value, # Store enum value
        status=db_models.CaseStatusEnum.QUEUED,
        last_submitted_at=datetime.utcnow(),
        processed_documents_summary=[] # Initialize as empty list
    )
    db.add(db_case)
    try:
        db.commit()
        db.refresh(db_case)
    except IntegrityError:
        db.rollback()
        logger.warning(f"IntegrityError creating case {case_data.case_number_for_db_id}, likely already exists. Fetching existing.")
        existing_case = get_case_by_case_number(db, case_data.case_number_for_db_id)
        if not existing_case:
             logger.error(f"CRITICAL: IntegrityError for case {case_data.case_number_for_db_id} but could not fetch it.")
             raise
        return existing_case # Should be handled by delete-then-create logic in API layer
    return db_case

def update_case_status(db: Session, case_id: int, status: db_models.CaseStatusEnum) -> Optional[db_models.Case]:
    db_case = db.query(db_models.Case).filter(db_models.Case.id == case_id).first()
    if db_case:
        db_case.status = status
        db.commit()
        db.refresh(db_case)
    return db_case

def update_case_details_from_unicourt_page(
    db: Session, 
    case_id: int, 
    unicourt_case_name: Optional[str] = None, 
    unicourt_case_url: Optional[str] = None,
    unicourt_actual_case_number: Optional[str] = None,
    associated_parties: Optional[List[str]] = None
) -> Optional[db_models.Case]:
    db_case = db.query(db_models.Case).filter(db_models.Case.id == case_id).first()
    if db_case:
        if unicourt_case_name is not None:
            db_case.unicourt_case_name_on_page = unicourt_case_name
        if unicourt_case_url is not None:
            db_case.case_url_on_unicourt = unicourt_case_url
        if unicourt_actual_case_number is not None:
            db_case.unicourt_actual_case_number_on_page = unicourt_actual_case_number
        if associated_parties is not None:
            db_case.associated_parties = associated_parties
        db.commit()
        db.refresh(db_case)
    return db_case

def update_case_extracted_data(
    db: Session,
    case_id: int,
    original_creditor_name: Optional[str] = None,
    original_creditor_name_source_title: Optional[str] = None,
    creditor_address: Optional[str] = None,
    creditor_address_source_title: Optional[str] = None,
    associated_parties_data: Optional[List[Dict[str, str]]] = None, # e.g. [{"name": "...", "address": "...", "source_doc_title": "..."}]
    registration_state: Optional[str] = None,
    registration_state_source_title: Optional[str] = None,
) -> Optional[db_models.Case]:
    db_case = db.query(db_models.Case).filter(db_models.Case.id == case_id).first()
    if db_case:
        if original_creditor_name is not None and not db_case.original_creditor_name_from_doc: # Fill if empty
            db_case.original_creditor_name_from_doc = original_creditor_name
            db_case.original_creditor_name_source_doc_title = original_creditor_name_source_title
        
        if creditor_address is not None and not db_case.creditor_address_from_doc: # Fill if empty
            db_case.creditor_address_from_doc = creditor_address
            db_case.creditor_address_source_doc_title = creditor_address_source_title

        if associated_parties_data: # This usually appends or updates, manage in calling function logic
            # For simplicity, this will overwrite. More complex merging logic if needed should be in case_processor
            db_case.associated_parties_data = associated_parties_data
            
        if registration_state is not None and not db_case.creditor_registration_state_from_doc: # Fill if empty
            db_case.creditor_registration_state_from_doc = registration_state
            db_case.creditor_registration_state_source_doc_title = registration_state_source_title
        
        db.commit()
        db.refresh(db_case)
    return db_case

def update_case_processed_documents_summary(
    db: Session,
    case_id: int,
    doc_summary_item: Dict[str, Any] # {"document_name": "...", "unicourt_doc_key": "...", "status": "..."}
) -> Optional[db_models.Case]:
    db_case = db.query(db_models.Case).filter(db_models.Case.id == case_id).first()
    if db_case:
        current_summary = db_case.processed_documents_summary or []
        
        # Check if item with same name and key already exists to update its status, otherwise append
        found_existing = False
        for i, item in enumerate(current_summary):
            if item.get("document_name") == doc_summary_item.get("document_name") and \
               item.get("unicourt_doc_key") == doc_summary_item.get("unicourt_doc_key"):
                current_summary[i]["status"] = doc_summary_item["status"] # Update status
                found_existing = True
                break
        if not found_existing:
            current_summary.append(doc_summary_item)
            
        db_case.processed_documents_summary = current_summary
        db.commit()
        db.refresh(db_case)
    return db_case


def delete_case_by_id(db: Session, case_id: int) -> bool:
    db_case = db.query(db_models.Case).filter(db_models.Case.id == case_id).first()
    if db_case:
        db.delete(db_case)
        db.commit()
        return True
    return False