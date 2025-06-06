# app/models_api/cases.py
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from app.db.models import CaseStatusEnum, CreditorTypeEnum # For consistency

class CaseSubmitDetail(BaseModel):
    case_number_for_db_id: str = Field(..., min_length=1, description="The case number to be used as the primary key in the database.")
    case_name_for_search: str = Field(..., min_length=1, description="The case name to primarily use for searching on Unicourt.")
    input_creditor_name: str = Field(..., min_length=1, description="Name of the creditor for LLM focus and party identification.")
    is_business: bool = Field(..., description="Indicates if the creditor is a business entity.")
    creditor_type: CreditorTypeEnum = Field(..., description="Type of the creditor (Plaintiff or Defendant).")

class CaseSubmitRequest(BaseModel):
    cases: List[CaseSubmitDetail] = Field(..., min_items=1)

class CaseSubmitResponse(BaseModel):
    message: str
    submitted_cases: int
    deleted_and_resubmitted_cases: int
    already_queued_or_processing: int
    current_queue_size: int

# --- Response Models for Getters ---

class ProcessedDocumentSummaryItem(BaseModel):
    document_name: str
    unicourt_doc_key: Optional[str] = None
    status: str # From DocumentProcessingStatusEnum
    notes: Optional[str] = None # General message about processing status

class AssociatedPartyData(BaseModel):
    name: str
    address: Optional[str] = None
    source_doc_title: Optional[str] = None


class CaseDetailResponse(BaseModel):
    id: int
    case_number_for_db_id: str # User-provided, DB key
    case_name_for_search: str
    input_creditor_name: str
    is_business: bool
    creditor_type: str # String representation of CreditorTypeEnum
    
    unicourt_case_name_on_page: Optional[str] = None
    unicourt_actual_case_number_on_page: Optional[str] = None
    case_url_on_unicourt: Optional[str] = None
    
    status: str # String representation of CaseStatusEnum
    last_submitted_at: Optional[str] = None 

    original_creditor_name_from_doc: Optional[str] = None
    original_creditor_name_source_doc_title: Optional[str] = None
    creditor_address_from_doc: Optional[str] = None
    creditor_address_source_doc_title: Optional[str] = None
    associated_parties: List[str] = []
    associated_parties_data: List[AssociatedPartyData] = []
    creditor_registration_state_from_doc: Optional[str] = None
    creditor_registration_state_source_doc_title: Optional[str] = None
    processed_documents_summary: List[ProcessedDocumentSummaryItem] = []

    class Config:
        from_attributes = True


class CaseStatusResponseItem(BaseModel):
    case_number_for_db_id: str
    status: str 
    message: Optional[str] = None # General message about status (e.g., "In queue", "Processing")
    data: Optional[CaseDetailResponse] = None # Full data if available

class BatchCaseRequest(BaseModel):
    case_numbers_for_db_id: List[str] = Field(..., min_items=1, max_items=100) 

class BatchCaseDetailsResponse(BaseModel):
    results: Dict[str, Optional[CaseDetailResponse]] 
    errors: Dict[str, str] = {} 

class BatchCaseStatusResponse(BaseModel):
    results: Dict[str, Optional[CaseStatusResponseItem]] 
    errors: Dict[str, str] = {}
