# app/db/models.py
from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, JSON, ARRAY
from sqlalchemy.sql import func
from app.db.session import Base
import enum

# --- Enums ---
class CaseStatusEnum(str, enum.Enum):
    QUEUED = "Queued"
    PROCESSING = "Processing"
    COMPLETED_SUCCESSFULLY = "Completed_All_Data_Retrieved"
    COMPLETED_MISSING_DATA = "Completed_Missing_Data"
    COMPLETED_WITH_ERRORS = "Completed_With_Errors"
    CASE_NOT_FOUND_ON_UNICOURT = "Case_Not_Found_By_Name_And_Number"
    VOLUNTARY_DISMISSAL_FOUND_SKIPPED = "Voluntary_Dismissal_Found_Skipped"
    NO_FJ_NO_COMPLAINT_PDFS_FOUND = "No_FJ_No_Complaint_PDFs_Found" # For all creditor types
    SESSION_ERROR = "Failed_Initial_Login_Or_Session" # Replaces generic "Failed_Initial_Login_Or_Session"
    WORKER_ERROR = "Generic_Case_Error" # Replaces specific "Worker_Unhandled_Error"

# For in-memory categorization and processed_documents_summary status
class DocumentTypeEnum(str, enum.Enum):
    FINAL_JUDGMENT = "FJ"
    COMPLAINT = "Complaint"
    UNKNOWN = "Unknown"

class DocumentProcessingStatusEnum(str, enum.Enum):
    IDENTIFIED_FOR_PROCESSING = "Identified_For_Processing"
    SKIPPED_REQUIRES_PAYMENT = "Retrieval_Fee"
    ORDERING_COMPLETED = "Ordering_Completed" # Intermediate state after successful ordering, before download
    ORDERING_FAILED = "Ordering_Failed" # Covers explicit per-doc failure or link not appearing post-order
    DOWNLOAD_SUCCESS = "Download_Success" # Intermediate state for docs that go to LLM
    DOWNLOAD_FAILED = "Download_Failed"
    SKIPPED_PROCESSING_NOT_NEEDED = "Skipped_Processing_Not_Needed"
    LLM_PREPARATION_FAILED = "LLM_Failed_To_Turn_Doc_Into_Images" # Failed to prepare doc for LLM processing
    LLM_PROCESSING_ERROR = "LLM_Processing_Error" # Error calling LLM API, response parsing error
    LLM_EXTRACTION_FAILED = "LLM_Required_Infos_Not_Found" # LLM call failed
    LLM_EXTRACTION_SUCCESS = "LLM_Extraction_Success" # LLM call was successful, data found
    GENERIC_PROCESSING_ERROR = "Generic_Processing_Error" # Other errors during this specific doc's handling



# --- Main Case Table ---
class Case(Base):
    __tablename__ = "cases"

    id = Column(Integer, primary_key=True, index=True)
    
    # --- Input Fields from User ---
    case_number = Column(String, unique=True, index=True, nullable=False) # DB key
    case_name_for_search = Column(String, nullable=False)
    input_creditor_name = Column(String, nullable=False)
    is_business = Column(Boolean, nullable=False)
    creditor_type = Column(String, nullable=False)

    # --- Details Fetched from Unicourt (Case Level) ---
    unicourt_case_name_on_page = Column(String, nullable=True)
    unicourt_actual_case_number_on_page = Column(String, nullable=True)
    case_url_on_unicourt = Column(String, nullable=True)
    
    # --- Processing Status & Timestamps ---
    status = Column(String, default=CaseStatusEnum.QUEUED, nullable=False)
    last_submitted_at = Column(DateTime(timezone=True), server_default=func.now())

    # --- Extracted Data by LLM (Stored Directly in Case) ---
    original_creditor_name_from_doc = Column(String, nullable=True)
    original_creditor_name_source_doc_title = Column(String, nullable=True)

    creditor_address_from_doc = Column(Text, nullable=True)
    creditor_address_source_doc_title = Column(String, nullable=True)
    
    # Change from list to JSON - SQLAlchemy doesn't support list type directly
    associated_parties = Column(JSON, nullable=True)  # Stores list<string> of associated parties as JSON
    # Stores: [{"name": "Party Name", "address": "Party Address", "source_doc_title": "Doc Title"}, ...]
    associated_parties_data = Column(JSON, nullable=True)  # Stores party details as JSON array

    creditor_registration_state_from_doc = Column(String, nullable=True)
    creditor_registration_state_source_doc_title = Column(String, nullable=True)

    # Final Judgment Awarded to Creditor (Y/N)
    final_judgment_awarded_to_creditor = Column(String, nullable=True)  # 'Y', 'N', or None if not determined
    final_judgment_awarded_source_doc_title = Column(String, nullable=True)
    final_judgment_awarded_to_creditor_context = Column(Text, nullable=True)  # Context/phrase used to determine the judgment

    # --- Summary of Transient Document Processing ---
    # Stores: [{"document_name": "Doc Title", "unicourt_doc_key": "key_or_null", "status": "DocProcessingStatus"}, ...]
    processed_documents_summary = Column(JSON, nullable=True)


    def __repr__(self):
        return f"<Case(case_number='{self.case_number}', status='{self.status}')>"