# app/api/routers/cases_router.py
import os
import logging
import shutil # For deleting case folders
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks, status
from sqlalchemy.orm import Session

from app.db import crud, models as db_models, session as db_session
from app.models_api import cases as api_models
from app.api.deps import get_db, get_write_api_key, get_read_api_key, get_current_settings
from app.core.config import AppSettings
from app.utils.common import sanitize_filename

logger = logging.getLogger(__name__)
router = APIRouter()


def _db_case_to_response(db_case: db_models.Case) -> api_models.CaseDetailResponse:
    processed_docs_summary_resp = []
    if db_case.processed_documents_summary: # Should be a list of dicts
        for summary_item_db in db_case.processed_documents_summary:
            # Ensure it's a dict before attempting .get, though it should be from JSON
            if isinstance(summary_item_db, dict):
                processed_docs_summary_resp.append(
                    api_models.ProcessedDocumentSummaryItem(
                        document_name=summary_item_db.get("document_name", "N/A"),
                        unicourt_doc_key=summary_item_db.get("unicourt_doc_key"),
                        status=summary_item_db.get("status", "Unknown"),
                        notes=summary_item_db.get("notes", "") # Optional, may not exist
                    )
                )
    
    assoc_parties_resp = []
    if db_case.associated_parties_data: # List of dicts
        for party_data_db in db_case.associated_parties_data:
            if isinstance(party_data_db, dict):
                 assoc_parties_resp.append(
                    api_models.AssociatedPartyData(
                        name=party_data_db.get("name", "Unknown Party"),
                        address=party_data_db.get("address"),
                        source_doc_title=party_data_db.get("source_doc_title")
                    )
                 )

    return api_models.CaseDetailResponse(
        id=db_case.id,
        case_number_for_db_id=db_case.case_number,
        case_name_for_search=db_case.case_name_for_search,
        input_creditor_name=db_case.input_creditor_name,
        is_business=db_case.is_business,
        creditor_type=db_case.creditor_type, # Already string from DB model
        unicourt_case_name_on_page=db_case.unicourt_case_name_on_page,
        unicourt_actual_case_number_on_page=db_case.unicourt_actual_case_number_on_page,
        case_url_on_unicourt=db_case.case_url_on_unicourt,
        status=db_case.status,
        last_submitted_at=db_case.last_submitted_at.isoformat() if db_case.last_submitted_at else None,
        original_creditor_name_from_doc=db_case.original_creditor_name_from_doc,
        original_creditor_name_source_doc_title=db_case.original_creditor_name_source_doc_title,
        creditor_address_from_doc=db_case.creditor_address_from_doc,
        creditor_address_source_doc_title=db_case.creditor_address_source_doc_title,
        associated_parties=db_case.associated_parties or [], # Handle None case
        associated_parties_data=assoc_parties_resp,
        creditor_registration_state_from_doc=db_case.creditor_registration_state_from_doc,
        creditor_registration_state_source_doc_title=db_case.creditor_registration_state_source_doc_title,
        processed_documents_summary=processed_docs_summary_resp
    )


@router.post("/submit", response_model=api_models.CaseSubmitResponse, status_code=status.HTTP_202_ACCEPTED)
async def submit_cases_for_processing(
    payload: api_models.CaseSubmitRequest,
    request: Request,
    db: Session = Depends(get_db),
    api_key: str = Depends(get_write_api_key),
    settings: AppSettings = Depends(get_current_settings)
):
    if not request.app.state.service_ready:
         raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service is not ready. Please try again later.")
    if request.app.state.shutting_down:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service is shutting down. New submissions not accepted.")

    newly_submitted_count = 0
    deleted_and_resubmitted_count = 0
    skipped_active_count = 0

    current_queue_case_numbers = [item[1].case_number for item in list(request.app.state.case_processing_queue._queue)]
    async with request.app.state.active_cases_lock:
        current_active_case_numbers = set(request.app.state.actively_processing_cases)

    submitted_in_this_call: set[str] = set()

    for case_detail in payload.cases:
        case_num_for_db = case_detail.case_number_for_db_id.strip()
        if not case_num_for_db:
            logger.warning("Empty case_number_for_db_id received. Skipping.")
            continue
        if case_num_for_db in submitted_in_this_call:
            logger.debug(f"Case {case_num_for_db} submitted multiple times in this payload. Processing first instance.")
            continue
        submitted_in_this_call.add(case_num_for_db)

        if case_num_for_db in current_queue_case_numbers or case_num_for_db in current_active_case_numbers:
            logger.info(f"Case {case_num_for_db} is already in queue or actively processing. Skipping submission.")
            skipped_active_count += 1
            continue

        existing_db_case = crud.get_case_by_case_number(db, case_num_for_db)
        
        if existing_db_case:
            logger.info(f"Case {case_num_for_db} (ID: {existing_db_case.id}) found in DB. Deleting old record and associated files before re-submission.")
            
            # Delete old case-specific temp download folder (now in "temp_case_files")
            sane_case_folder_name = sanitize_filename(case_num_for_db)
            # Path used by case_processor for temporary files
            temp_case_dir_path = os.path.join(settings.CURRENT_DOWNLOAD_LOCATION, "temp_case_files", sane_case_folder_name)
            if os.path.exists(temp_case_dir_path):
                try:
                    shutil.rmtree(temp_case_dir_path)
                    logger.info(f"Deleted old temp files folder for case {case_num_for_db}: {temp_case_dir_path}")
                except Exception as e_rm:
                    logger.error(f"Error deleting old temp files folder {temp_case_dir_path} for case {case_num_for_db}: {e_rm}")
            
            # Delete DB record
            crud.delete_case_by_id(db, existing_db_case.id)
            deleted_and_resubmitted_count += 1
        
        # Create new case record
        db_case = crud.create_case(db, case_detail) # create_case now handles all new fields
        logger.info(f"New case record for {case_num_for_db} (ID: {db_case.id}) created and submitted to queue.")
        newly_submitted_count +=1 # Count as newly submitted even if an old one was deleted

        # Queue item is now (case_id, case_db_object)
        await request.app.state.case_processing_queue.put((db_case.id, db_case))
        current_queue_case_numbers.append(case_num_for_db) # Update local snapshot

    return api_models.CaseSubmitResponse(
        message=f"Processed submission: {newly_submitted_count} case(s) newly added. {deleted_and_resubmitted_count} case(s) replaced (old deleted). {skipped_active_count} case(s) skipped (already active/queued).",
        submitted_cases=newly_submitted_count,
        deleted_and_resubmitted_cases=deleted_and_resubmitted_count,
        already_queued_or_processing=skipped_active_count,
        current_queue_size=request.app.state.case_processing_queue.qsize()
    )


def _get_case_status_or_data_internal(
    case_number_for_db_id: str,
    db: Session,
    request: Request 
) -> api_models.CaseStatusResponseItem:
    
    db_case = crud.get_case_by_case_number(db, case_number_for_db_id)

    if db_case:
        if db_case.status == db_models.CaseStatusEnum.QUEUED:
             current_queue_case_numbers = [item[1].case_number for item in list(request.app.state.case_processing_queue._queue)]
             if case_number_for_db_id in current_queue_case_numbers:
                 return api_models.CaseStatusResponseItem(case_number_for_db_id=case_number_for_db_id, status="Queued", message="Case is in the processing queue.")
        
        if db_case.status == db_models.CaseStatusEnum.PROCESSING:
            if case_number_for_db_id in request.app.state.actively_processing_cases:
                return api_models.CaseStatusResponseItem(case_number_for_db_id=case_number_for_db_id, status="Processing", message="Case is actively being processed by a worker.")
        
        # For other statuses, or if not actively in queue/processing, return DB state
        return api_models.CaseStatusResponseItem(
            case_number_for_db_id=case_number_for_db_id,
            status=db_case.status, # Directly use the enum string value
            message=f"Current status from database.", # Generic message
            data=_db_case_to_response(db_case)
        )
    else: 
        # Check queue/active even if not in DB (e.g. race condition on submit)
        current_queue_case_numbers = [item[1].case_number for item in list(request.app.state.case_processing_queue._queue)]
        if case_number_for_db_id in current_queue_case_numbers:
            return api_models.CaseStatusResponseItem(case_number_for_db_id=case_number_for_db_id, status="Queued", message="Case is in processing queue (DB entry may be pending full processing).")
        if case_number_for_db_id in request.app.state.actively_processing_cases:
            return api_models.CaseStatusResponseItem(case_number_for_db_id=case_number_for_db_id, status="Processing", message="Case is actively processing (DB entry may be pending full processing).")

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Case {case_number_for_db_id} not found.")


@router.post("/batch-status", response_model=api_models.BatchCaseStatusResponse)
async def get_batch_case_statuses(
    payload: api_models.BatchCaseRequest,
    request: Request, 
    db: Session = Depends(get_db),
    api_key: str = Depends(get_read_api_key)
):
    response_results: Dict[str, Optional[api_models.CaseStatusResponseItem]] = {}
    response_errors: Dict[str, str] = {}

    for case_num_raw in payload.case_numbers_for_db_id:
        case_num = case_num_raw.strip()
        if not case_num: continue
        try:
            status_item = _get_case_status_or_data_internal(case_num, db, request)
            response_results[case_num] = status_item
        except HTTPException as e:
            response_errors[case_num] = str(e.detail)
            response_results[case_num] = None 
        except Exception as e_unhandled:
            logger.error(f"Batch status: Unexpected error for case {case_num}: {e_unhandled}", exc_info=True)
            response_errors[case_num] = "Unexpected server error."
            response_results[case_num] = None
            
    return api_models.BatchCaseStatusResponse(results=response_results, errors=response_errors)


@router.post("/batch-details", response_model=api_models.BatchCaseDetailsResponse)
async def get_batch_case_details(
    payload: api_models.BatchCaseRequest,
    db: Session = Depends(get_db),
    api_key: str = Depends(get_read_api_key)
):
    response_results: Dict[str, Optional[api_models.CaseDetailResponse]] = {}
    response_errors: Dict[str, str] = {}

    for case_num_raw in payload.case_numbers_for_db_id:
        case_num = case_num_raw.strip()
        if not case_num: continue
        
        db_case = crud.get_case_by_case_number(db, case_num)
        if db_case:
            try:
                response_results[case_num] = _db_case_to_response(db_case)
            except Exception as e_conv:
                logger.error(f"Batch details: Error converting DB case {case_num} to response: {e_conv}", exc_info=True)
                response_errors[case_num] = "Error formatting case details."
                response_results[case_num] = None
        else:
            response_errors[case_num] = "Case not found in database."
            response_results[case_num] = None 

    return api_models.BatchCaseDetailsResponse(results=response_results, errors=response_errors)


@router.get("", response_model=List[api_models.CaseDetailResponse])
async def get_all_cases(
    db: Session = Depends(get_db),
    api_key: str = Depends(get_read_api_key)
):
    """Get all cases from the database."""
    db_cases = crud.get_all_cases(db)
    return [_db_case_to_response(case) for case in db_cases]


@router.get("/{case_number_for_db_id}/status", response_model=api_models.CaseStatusResponseItem)
async def get_case_status_and_data(
    case_number_for_db_id: str,
    request: Request,
    db: Session = Depends(get_db),
    api_key: str = Depends(get_read_api_key)
):
    return _get_case_status_or_data_internal(case_number_for_db_id, db, request)