# tests/manual_llm_runs/test_llm_real_api_single_doc.py
import pytest
import asyncio
import os
from typing import List, Dict, Optional

from app.core.config import AppSettings
from app.services.llm_processor import LLMProcessor, LLMResponseData

# --- CONFIGURATION: Set these paths to your actual test files ---
BASE_TEST_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "test_data", "llm_docs") # Assumes test_data is at project root

# OpenRouter Configuration
OPENROUTER_API_KEY = "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"
OPENROUTER_LLM_MODEL = "meta-llama/llama-4-maverick"

FILES_TO_TEST = {
    "FJ_PDF": os.path.join(BASE_TEST_DATA_DIR, "final_judgement.pdf"),
    "FJ_TIFF": os.path.join(BASE_TEST_DATA_DIR, "final_judgement.tif"),
    "COMPLAINT_PDF": os.path.join(BASE_TEST_DATA_DIR, "complaint.pdf"),
}

# --- Per-Document Test Configurations (YOU NEED TO DEFINE THESE) ---
# These would be similar to what CaseProcessorService would determine
# before calling the LLM for a specific document.
DOCUMENT_PROCESSING_CONFIGS = {
    "FJ_PDF": {
        "input_creditor_name": "Dorsainville, Develyne", # Main creditor in this doc
        "is_business": False,
        # Parties whose addresses you're hoping to find in *this specific document*
        "target_associated_party_names": [], 
        # What info is *still needed* for the case when this doc is being processed
        "info_to_extract": { 
            "original_creditor_name": True, "creditor_address": True,
            "associated_parties_addresses": True, "reg_state": False
        }
    },
    "FJ_TIFF": { # Assuming similar content for the TIFF version of FJ
        "input_creditor_name": "Dorsainville, Develyne",
        "is_business": False,
        "target_associated_party_names": [],
        "info_to_extract": {
            "original_creditor_name": True, "creditor_address": True,
            "associated_parties_addresses": True, "reg_state": False
        }
    },
    "COMPLAINT_PDF": {
        "input_creditor_name": "Dorsainville, Develyne",
        "is_business": False,
        "target_associated_party_names": [],
        "info_to_extract": {
            "original_creditor_name": True, "creditor_address": True,
            "associated_parties_addresses": True, "reg_state": False # Assuming plaintiff is a business
        }
    },
}


@pytest.fixture(scope="module", autouse=True)
def check_test_files_exist_and_api_key():
    if not os.path.exists(BASE_TEST_DATA_DIR):
        os.makedirs(BASE_TEST_DATA_DIR)
        pytest.skip(f"Test data directory {BASE_TEST_DATA_DIR} was created, but please add your test PDF/TIFF files there.")
    
    for key, path in FILES_TO_TEST.items():
        if not os.path.exists(path):
            pytest.skip(f"Missing test document for {key}: {path}. Please place it in {BASE_TEST_DATA_DIR}")
    
    settings = AppSettings()
    if not OPENROUTER_API_KEY or OPENROUTER_API_KEY == "default_openrouter_api_key_please_configure":
        pytest.skip("OPENROUTER_API_KEY is not configured or is default. Skipping real API tests.")
    if not OPENROUTER_LLM_MODEL or "/" not in OPENROUTER_LLM_MODEL:  # Basic check for model format
        pytest.skip("OPENROUTER_LLM_MODEL is not configured or seems invalid. Skipping real API tests.")
    print(f"Using LLM Model: {OPENROUTER_LLM_MODEL} for real API calls.")
    print(f"API Key starts with: {OPENROUTER_API_KEY[:5]}...")
    print("All required LLM test documents and API configuration seem present.")
    yield


@pytest.mark.parametrize("doc_key", DOCUMENT_PROCESSING_CONFIGS.keys())
@pytest.mark.asyncio
async def test_process_document_with_real_llm_api(doc_key: str):
    """
    Processes a single specified document using the LLMProcessor with real API calls.
    Prints the raw LLM response (if available from notes) and the parsed LLMResponseData.
    """
    settings = AppSettings(
        # For real calls, ensure these are appropriate.
        # LLM_TIMEOUT_SECONDS might need to be generous for large docs.
        # MAX_IMAGES_PER_LLM_CALL might be limited by the chosen model's context window or token limits for images.
    ) 
    llm_processor = LLMProcessor(settings)

    doc_path = FILES_TO_TEST[doc_key]
    config = DOCUMENT_PROCESSING_CONFIGS[doc_key]

    print(f"\n--- Testing Document: {doc_key} ({doc_path}) ---")
    print(f"Input Creditor: {config['input_creditor_name']}, Is Business: {config['is_business']}")
    print(f"Target Associated Parties for Address: {config['target_associated_party_names']}")
    print(f"Info to Extract This Pass: {config['info_to_extract']}")
    print(f"Using LLM Model: {settings.OPENROUTER_LLM_MODEL}")
    print(f"Max images per LLM call: {settings.MAX_IMAGES_PER_LLM_CALL}")


    # The process_document_for_case_info method handles conversion and batched LLM calls
    llm_data: Optional[LLMResponseData]
    processing_notes: str
    
    llm_data, processing_notes = await llm_processor.process_document_for_case_info(
        doc_full_path=doc_path,
        input_creditor_name=config["input_creditor_name"],
        is_business=config["is_business"],
        target_associated_party_names=config["target_associated_party_names"],
        info_to_extract_for_doc=config["info_to_extract"], # Pass the specific needs for this doc
        max_images_per_llm_call=settings.MAX_IMAGES_PER_LLM_CALL,
        max_llm_attempts_per_batch=settings.MAX_LLM_ATTEMPTS_PER_BATCH
    )

    print(f"\n--- Results for: {doc_key} ---")
    print(f"Processing Notes:\n{processing_notes}")
    
    if llm_data is not None:
        print("\nParsed LLMResponseData:")
        try:
            # Pydantic's model_dump_json is good for pretty printing
            print(llm_data.model_dump_json(indent=2))
        except Exception as e:
            print(f"Error dumping LLM data model: {e}")
            print(f"Raw LLM Data object: {llm_data}")
        
        

    else:
        print("\nLLM Processing returned None (Major Error or No Data Extracted from any batch).")
        pytest.fail(f"LLM processing failed for {doc_key}. Notes: {processing_notes}")

    print(f"--- End of Test for: {doc_key} ---\n")

# How to run:
# 1. Place your final_judgement.pdf, final_judgement.tif, complaint.pdf in tests/test_data/llm_docs/
# 2. Configure OPENROUTER_API_KEY and OPENROUTER_LLM_MODEL in your .env or environment.
#    The LLM_MODEL *must* be a vision-capable model from OpenRouter.
# 3. Update the TODO sections in DOCUMENT_PROCESSING_CONFIGS with realistic creditor names,
#    target parties, and business status for YOUR specific test documents.
# 4. Run with pytest:
#    pytest tests/manual_llm_runs/test_llm_real_api_single_doc.py
#    Or to run for a specific document:
#    pytest tests/manual_llm_runs/test_llm_real_api_single_doc.py -k FJ_PDF
#    pytest tests/manual_llm_runs/test_llm_real_api_single_doc.py -k COMPLAINT_PDF