# app/services/case_processor.py
import os
import asyncio
import logging
import shutil # For deleting folders
from typing import Tuple, Optional, Dict, Any, Set, List
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from playwright.async_api import Page

from app.core.config import AppSettings
from app.db import crud, models as db_models
from app.services.unicourt_handler import UnicourtHandler, TransientDocumentInfo
from app.services.llm_processor import LLMProcessor, LLMResponseData
from app.utils import common, playwright_utils

logger = logging.getLogger(__name__)

class CaseProcessorService:
    def __init__(self, db: Session, settings: AppSettings, unicourt_handler: UnicourtHandler, llm_processor: LLMProcessor):
        self.db = db
        self.settings = settings
        self.unicourt_handler = unicourt_handler
        self.llm_processor = llm_processor

    async def _process_single_document_with_llm(
        self,
        trans_doc_info: TransientDocumentInfo,
        case_db_obj: db_models.Case,
        # Case-level tracking of what's found so far
        found_original_creditor_name_for_case: bool,
        found_creditor_address_for_case: bool,
        found_reg_state_for_case: bool, 
        found_party_addresses_for_case: Dict[str, bool], 
        target_associated_party_names_for_case: List[str]
    ) -> Tuple[Optional[LLMResponseData], str, bool, bool, bool, Dict[str,bool]]:
        
        llm_api_notes = "LLM processing not attempted for document."
        llm_data: Optional[LLMResponseData] = None

        if not trans_doc_info.temp_local_path or not os.path.exists(trans_doc_info.temp_local_path):
            logger.error(f"[{case_db_obj.case_number}] LLM: File missing for '{trans_doc_info.original_title}' at '{trans_doc_info.temp_local_path}'.")
            return None, "File missing for LLM.", found_original_creditor_name_for_case, found_creditor_address_for_case, found_reg_state_for_case, found_party_addresses_for_case

        # Determine what info is still needed for this LLM call based on overall case needs
        info_to_extract_for_this_doc_pass: Dict[str, bool] = {
            "original_creditor_name": not found_original_creditor_name_for_case,
            "creditor_address": not found_creditor_address_for_case,
            # Only ask for associated party addresses if the global setting is true
            # AND if there are parties whose addresses haven't been found yet.
            "associated_parties_addresses": self.settings.EXTRACT_ASSOCIATED_PARTY_ADDRESSES and \
                                            any(not found_party_addresses_for_case.get(name, False) for name in target_associated_party_names_for_case),
            "reg_state": case_db_obj.is_business and not found_reg_state_for_case
        }
        
        current_target_party_names_for_llm_pass = [
            name for name in target_associated_party_names_for_case 
            if self.settings.EXTRACT_ASSOCIATED_PARTY_ADDRESSES and not found_party_addresses_for_case.get(name, False)
        ] if info_to_extract_for_this_doc_pass.get("associated_parties_addresses") else []


        if not any(info_to_extract_for_this_doc_pass.values()):
            llm_api_notes = "All required case-level info already found before processing this doc with LLM."
            logger.info(f"[{case_db_obj.case_number}] LLM: Skipping LLM for '{trans_doc_info.original_title}', {llm_api_notes}")
            # Return an empty LLMResponseData to signify no new data, but not an error.
            # The found flags remain unchanged as this doc didn't contribute new info.
            return LLMResponseData(), llm_api_notes, found_original_creditor_name_for_case, found_creditor_address_for_case, found_reg_state_for_case, found_party_addresses_for_case

        # Call the (renamed) method in LLMProcessor
        llm_data, llm_api_notes = await self.llm_processor.process_document_for_case_info(
            doc_full_path=trans_doc_info.temp_local_path,
            input_creditor_name=case_db_obj.input_creditor_name,
            is_business=case_db_obj.is_business,
            target_associated_party_names=current_target_party_names_for_llm_pass, # Pass only those still needed
            info_to_extract_for_doc=info_to_extract_for_this_doc_pass, # What to look for in this doc
            max_images_per_llm_call=self.settings.MAX_IMAGES_PER_LLM_CALL, # Add to AppSettings
            max_llm_attempts_per_batch=self.settings.MAX_LLM_ATTEMPTS_PER_BATCH # Add to AppSettings
        )

        # Update case_db_obj and found_flags based on llm_data
        # This part remains largely the same, it merges new info from llm_data
        # into the case object and updates the overall found_..._for_case flags
        if llm_data: # llm_data can be an empty LLMResponseData if nothing was found by LLM
            db_changed = False
            if llm_data.original_creditor_name and not case_db_obj.original_creditor_name_from_doc:
                case_db_obj.original_creditor_name_from_doc = llm_data.original_creditor_name
                case_db_obj.original_creditor_name_source_doc_title = trans_doc_info.original_title
                found_original_creditor_name_for_case = True # Update case-level flag
                db_changed = True
            
            if llm_data.creditor_address and not case_db_obj.creditor_address_from_doc:
                case_db_obj.creditor_address_from_doc = llm_data.creditor_address
                case_db_obj.creditor_address_source_doc_title = trans_doc_info.original_title
                found_creditor_address_for_case = True # Update case-level flag
                db_changed = True

            if case_db_obj.is_business and llm_data.creditor_registration_state and not case_db_obj.creditor_registration_state_from_doc:
                case_db_obj.creditor_registration_state_from_doc = llm_data.creditor_registration_state
                case_db_obj.creditor_registration_state_source_doc_title = trans_doc_info.original_title
                found_reg_state_for_case = True # Update case-level flag
                db_changed = True

            if self.settings.EXTRACT_ASSOCIATED_PARTY_ADDRESSES and llm_data.associated_parties:
                current_case_assoc_parties = list(case_db_obj.associated_parties_data or [])
                # Create a set of (name, address) tuples from existing data to avoid adding exact duplicates
                existing_name_address_pairs = {(p.get("name"), p.get("address")) for p in current_case_assoc_parties}

                for llm_party_info in llm_data.associated_parties:
                    party_name = llm_party_info.get("name")
                    party_address = llm_party_info.get("address")
                    # Only add if name and address are present, and this specific name-address pair isn't already there
                    if party_name and party_address and (party_name, party_address) not in existing_name_address_pairs:
                        # And only if we don't already have *an* address for this party_name (first found wins for a given name)
                        if not found_party_addresses_for_case.get(party_name, False):
                            current_case_assoc_parties.append({
                                "name": party_name, 
                                "address": party_address, 
                                "source_doc_title": trans_doc_info.original_title
                            })
                            found_party_addresses_for_case[party_name] = True # Update case-level flag for this party
                            existing_name_address_pairs.add((party_name, party_address)) # Add to current doc's tracking
                            db_changed = True
                if db_changed: 
                     case_db_obj.associated_parties_data = current_case_assoc_parties

            if db_changed:
                try:
                    self.db.commit()
                    self.db.refresh(case_db_obj)
                except Exception as e_commit:
                    logger.error(f"[{case_db_obj.case_number}] Error committing LLM updates to DB: {e_commit}")
                    self.db.rollback()
        
        return llm_data, llm_api_notes, found_original_creditor_name_for_case, found_creditor_address_for_case, found_reg_state_for_case, found_party_addresses_for_case


    async def process_single_case(
        self, 
        case_id: int, 
        case_obj_from_queue: db_models.Case # Pass the full case object now
    ) -> None:
        case_number_for_db = case_obj_from_queue.case_number
        case_name_for_search = case_obj_from_queue.case_name_for_search
        input_creditor_name = case_obj_from_queue.input_creditor_name
        is_business = case_obj_from_queue.is_business
        creditor_type = db_models.CreditorTypeEnum(case_obj_from_queue.creditor_type) # Convert back to Enum

        logger.info(f"Starting processing for case_id: {case_id}, DB_Key_Num: {case_number_for_db}")
          # Case is already updated for QUEUED status by API. Now set to PROCESSING.
        # If reprocessing is true, reset_case_for_reprocessing was already called by API.
        crud.update_case_status(self.db, case_id, db_models.CaseStatusEnum.PROCESSING)
        # Instead of refreshing the queue object, get a fresh copy from the database
        case_obj_from_queue = crud.get_case_by_case_number(self.db, case_number_for_db)
        if not case_obj_from_queue:
            logger.error(f"Case with ID {case_id} not found in database after status update")
            return

        # Temporary download path for this case's docs
        sane_case_folder_name = common.sanitize_filename(case_number_for_db)
        # CURRENT_DOWNLOAD_LOCATION is the base for DB file and session, temp files go into subfolder
        temp_case_specific_download_path = os.path.join(self.settings.CURRENT_DOWNLOAD_LOCATION, "temp_case_files", sane_case_folder_name)
        
        # Ensure clean slate for temp downloads for this run
        if os.path.exists(temp_case_specific_download_path):
            try:
                shutil.rmtree(temp_case_specific_download_path)
                logger.info(f"[{case_number_for_db}] Cleaned up existing temp directory: {temp_case_specific_download_path}")
            except Exception as e_rm:
                logger.error(f"[{case_number_for_db}] Error removing existing temp directory {temp_case_specific_download_path}: {e_rm}")
                # Proceed, but downloads might fail or mix if dir is not clean
        os.makedirs(temp_case_specific_download_path, exist_ok=True)
        
        dashboard_page = self.unicourt_handler.dashboard_page_for_worker
        if not dashboard_page or dashboard_page.is_closed():
            msg = f"[{case_number_for_db}] Worker's dashboard page is not available. Cannot process."
            logger.error(msg)
            crud.update_case_status(self.db, case_id, db_models.CaseStatusEnum.WORKER_ERROR)
            return

        case_page: Optional[Page] = None
        final_case_status = db_models.CaseStatusEnum.COMPLETED_WITH_ERRORS # Default pessimistic
        
        # Re-fetch case object for latest state if any background update happened
        # though it's less likely now with direct param passing
        case_db_obj = crud.get_case_by_case_number(self.db, case_number_for_db)
        if not case_db_obj: # Should not happen if case_id and case_obj_from_queue are valid
            logger.error(f"[{case_number_for_db}] Case (ID: {case_id}) vanished from DB. Aborting.")
            return


        # --- Overall Case Processing State ---
        found_original_creditor_name_for_case: bool = bool(case_db_obj.original_creditor_name_from_doc)
        found_creditor_address_for_case: bool = bool(case_db_obj.creditor_address_from_doc)
        found_reg_state_for_case: bool = bool(case_db_obj.creditor_registration_state_from_doc) if case_db_obj.is_business else True # True if not business
        
        # For associated parties, from case_db_obj.associated_parties_data
        # Initialize found_party_addresses_for_case based on what's already in DB (if reprocessing an existing entry)
        target_associated_party_names: List[str] = [] # This will be filled after party tab interaction
        found_party_addresses_for_case: Dict[str, bool] = {} # party_name -> True if address found
        if case_db_obj.associated_parties_data:
            for party_entry in case_db_obj.associated_parties_data:
                if party_entry.get("name") and party_entry.get("address"):
                    found_party_addresses_for_case[party_entry["name"]] = True
        # --- End Overall Case Processing State ---


        try:
            if not await self.unicourt_handler.ensure_authenticated_session(page_to_check=dashboard_page):
                msg = f"[{case_number_for_db}] Failed to ensure Unicourt session."
                logger.error(msg)
                crud.update_case_status(self.db, case_id, db_models.CaseStatusEnum.SESSION_ERROR)
                return
            
            # --- Phase 1: Get the Case Page ---
            case_page, search_notes, unicourt_actual_name, unicourt_actual_number = \
                await self.unicourt_handler.search_and_open_case_page(dashboard_page, case_name_for_search, case_number_for_db)

            if not case_page:
                logger.warning(f"[{case_number_for_db}] Failed to open Unicourt case page. Search notes: {search_notes}")
                final_status_to_set = db_models.CaseStatusEnum.CASE_NOT_FOUND_ON_UNICOURT
                crud.update_case_status(self.db, case_id, final_status_to_set)
                return            
            
            crud.update_case_details_from_unicourt_page(
                self.db, case_id, 
                unicourt_case_name=unicourt_actual_name, 
                unicourt_case_url=case_page.url,
                unicourt_actual_case_number=unicourt_actual_number
            )
            self.db.refresh(case_db_obj) # Refresh after update
            logger.info(f"[{case_number_for_db}] Case page opened. URL: {case_page.url}")
            
            # --- Phase 2.1: Check for "Voluntary Dismissal" ---
            if await self.unicourt_handler.check_for_voluntary_dismissal(case_page, case_number_for_db):
                logger.info(f"[{case_number_for_db}] Voluntary dismissal found. Skipping further processing.")
                final_case_status = db_models.CaseStatusEnum.VOLUNTARY_DISMISSAL_FOUND_SKIPPED
                raise Exception("VoluntaryDismissalStopProcessing") # Use custom exception to jump to finally

            # --- Phase 2.2: Go to 'Parties' tab and extract associated party names ---
            target_associated_party_names = await self.unicourt_handler.extract_party_names_from_parties_tab(
                case_page, creditor_type, input_creditor_name, case_number_for_db
            )
            if target_associated_party_names == []:
                logger.warning(f"[{case_number_for_db}] No associated parties found in 'Parties' tab.")
            else:
                logger.info(f"[{case_number_for_db}] Found associated parties: {target_associated_party_names}")                
                crud.update_case_details_from_unicourt_page(
                    self.db, case_id, associated_parties=target_associated_party_names
                )

            # Initialize found_party_addresses_for_case for these new targets if not already present from DB
            for name in target_associated_party_names:
                if name not in found_party_addresses_for_case:
                    found_party_addresses_for_case[name] = False
            
            # --- Phase 2.3 & Download Logic (Revised): Identify, Order, Download ---
            # This function now handles Paid section (ordering) and CrowdSourced (downloading)
            # It returns successfully downloaded docs for LLM and all doc summaries.
            llm_bundle_docs, doc_summaries_from_handler = \
                await self.unicourt_handler.identify_and_process_documents_on_case_page(
                    case_page, case_number_for_db, temp_case_specific_download_path
                )
            
            # Update case_db_obj.processed_documents_summary with all outcomes
            case_db_obj.processed_documents_summary = doc_summaries_from_handler
            self.db.commit()
            self.db.refresh(case_db_obj)

            if not llm_bundle_docs:
                logger.warning(f"[{case_number_for_db}] No FJ or Complaint documents were successfully downloaded for LLM processing.")
                # Status determination needs to check if *any* relevant docs were identified, even if not downloaded
                identified_relevant_docs = any(
                    self._doc_type_from_summary(s) in [db_models.DocumentTypeEnum.FINAL_JUDGMENT, db_models.DocumentTypeEnum.COMPLAINT]
                    for s in doc_summaries_from_handler
                )
                if not identified_relevant_docs: # No FJ or Complaint docs found at all
                    final_case_status = db_models.CaseStatusEnum.NO_FJ_NO_COMPLAINT_PDFS_FOUND
                else: # Relevant docs identified, but none downloaded (e.g. all paid, all failed download)
                    final_case_status = db_models.CaseStatusEnum.COMPLETED_WITH_ERRORS # Or a more specific status if needed
                raise Exception("NoDocsForLLMStopProcessing")


            # --- Phase 3: Process Downloaded Documents with LLM ---
            logger.info(f"[{case_number_for_db}] Processing {len(llm_bundle_docs)} downloaded documents with LLM.")
            
            docs_iterated_count = 0 # To track how many docs we've started to process in the loop

            for trans_doc_info in llm_bundle_docs: 
                docs_iterated_count += 1
                logger.info(f"[{case_number_for_db}] Considering LLM for: {trans_doc_info.original_title} (Type: {trans_doc_info.document_type.value})")
                
                # Determine if all required data for the case has *already* been found *before* this document
                all_assoc_parties_found_for_case = all(found_party_addresses_for_case.get(name, False) for name in target_associated_party_names) if self.settings.EXTRACT_ASSOCIATED_PARTY_ADDRESSES and target_associated_party_names else True
                
                all_case_info_found_prior_to_this_doc = (
                    found_original_creditor_name_for_case and
                    found_creditor_address_for_case and
                    (not case_db_obj.is_business or found_reg_state_for_case) and
                    all_assoc_parties_found_for_case
                )

                if all_case_info_found_prior_to_this_doc:
                    logger.info(f"[{case_db_obj.case_number}] All required case-level info found BEFORE '{trans_doc_info.original_title}'. Marking as skipped for LLM.")
                    self._update_doc_summary_status(case_db_obj, trans_doc_info.original_title, trans_doc_info.unicourt_doc_key, db_models.DocumentProcessingStatusEnum.SKIPPED_PROCESSING_NOT_NEEDED, "Skipped (LLM); all case info previously found.")
                    # No need to call _process_single_document_with_llm, just update status and continue to next doc in bundle
                    continue # Move to the next document in llm_bundle_docs

                # If we reach here, some case-level info is still needed, so we process this document with LLM
                returned_llm_data, llm_notes, \
                found_original_creditor_name_for_case, found_creditor_address_for_case, \
                found_reg_state_for_case, found_party_addresses_for_case = \
                    await self._process_single_document_with_llm(
                        trans_doc_info,
                        case_db_obj, 
                        found_original_creditor_name_for_case,
                        found_creditor_address_for_case,
                        found_reg_state_for_case,
                        found_party_addresses_for_case,
                        target_associated_party_names
                    )
                
                # Determine the outcome status for *this document's* LLM processing attempt
                current_doc_llm_status: db_models.DocumentProcessingStatusEnum
                if "File_Conversion_Failed" in llm_notes:
                     current_doc_llm_status = db_models.DocumentProcessingStatusEnum.LLM_PREPARATION_FAILED
                elif returned_llm_data is None: # Indicates a hard failure in LLM call or parsing
                    current_doc_llm_status = db_models.DocumentProcessingStatusEnum.LLM_PROCESSING_ERROR
                # returned_llm_data is not None (could be empty LLMResponseData or with data)
                elif "No specific information requested for this LLM pass" in llm_notes:
                     current_doc_llm_status = db_models.DocumentProcessingStatusEnum.SKIPPED_PROCESSING_NOT_NEEDED # No new info needed by this doc
                elif "LLM processed all batches but found no requested data" in llm_notes :
                    current_doc_llm_status = db_models.DocumentProcessingStatusEnum.LLM_EXTRACTION_FAILED # LLM ran but found nothing new
                else: # Assumed success if llm_data is present and no specific error notes for this doc
                    current_doc_llm_status = db_models.DocumentProcessingStatusEnum.LLM_EXTRACTION_SUCCESS
                
                self._update_doc_summary_status(case_db_obj, trans_doc_info.original_title, trans_doc_info.unicourt_doc_key, current_doc_llm_status, llm_notes)

            # are also marked appropriately. This is more of a safeguard now.
            if docs_iterated_count < len(llm_bundle_docs):
                logger.info(f"[{case_db_obj.case_number}] Marking remaining {len(llm_bundle_docs) - docs_iterated_count} docs as skipped post-loop.")
                for i in range(docs_iterated_count, len(llm_bundle_docs)):
                    skipped_doc_info = llm_bundle_docs[i]
                    self._update_doc_summary_status(case_db_obj, skipped_doc_info.original_title, skipped_doc_info.unicourt_doc_key, db_models.DocumentProcessingStatusEnum.SKIPPED_PROCESSING_NOT_NEEDED, "Skipped (LLM); loop ended early or all info found by prior docs.")

            # --- Final Case Status Determination ---
            logger.debug(f"[{case_number_for_db}] Final check of processed_documents_summary before determining case status: {case_db_obj.processed_documents_summary}")

            has_doc_processing_errors = False
            if case_db_obj.processed_documents_summary: 
                for s_item in case_db_obj.processed_documents_summary:
                    doc_type_in_summary = self._doc_type_from_summary(s_item)
                    status_in_summary = s_item.get("status")

                    if doc_type_in_summary in [db_models.DocumentTypeEnum.FINAL_JUDGMENT, db_models.DocumentTypeEnum.COMPLAINT]:
                        if status_in_summary not in [
                            db_models.DocumentProcessingStatusEnum.LLM_EXTRACTION_SUCCESS.value,
                            db_models.DocumentProcessingStatusEnum.LLM_EXTRACTION_FAILED.value,
                            db_models.DocumentProcessingStatusEnum.SKIPPED_PROCESSING_NOT_NEEDED.value,
                            db_models.DocumentProcessingStatusEnum.SKIPPED_REQUIRES_PAYMENT.value,
                        ]:
                            logger.warning(f"[{case_number_for_db}] Relevant document '{s_item.get('document_name')}' has non-final/error status: {status_in_summary}")
                            has_doc_processing_errors = True
                            break 
            elif llm_bundle_docs: # llm_bundle_docs had items, but final summary is empty/None. This is an error.
                 logger.warning(f"[{case_number_for_db}] llm_bundle_docs had items, but final processed_documents_summary is empty. Marking as error.")
                 has_doc_processing_errors = True


            if has_doc_processing_errors:
                final_case_status = db_models.CaseStatusEnum.COMPLETED_WITH_ERRORS
            else:
                # Check if essential data was found for overall success definition
                all_essential_found = (
                    found_original_creditor_name_for_case and
                    found_creditor_address_for_case and
                    (not case_db_obj.is_business or found_reg_state_for_case) and
                    ( (not self.settings.EXTRACT_ASSOCIATED_PARTY_ADDRESSES or not target_associated_party_names) or \
                       all(found_party_addresses_for_case.get(name, False) for name in target_associated_party_names) )
                )
                
                if all_essential_found:
                    final_case_status = db_models.CaseStatusEnum.COMPLETED_SUCCESSFULLY
                else:
                    logger.warning(f"[{case_number_for_db}] Case completed without document processing errors, but not all essential data was found.")
                    final_case_status = db_models.CaseStatusEnum.COMPLETED_MISSING_DATA
                
                logger.info(f"[{case_number_for_db}] Case processing finished. Final status: {final_case_status.value}")

        except (Exception) as e: # Catch custom stop exceptions and others
            error_msg = f"Error processing case {case_number_for_db} (ID: {case_id}): {type(e).__name__} - {str(e)}"
            if str(e) == "VoluntaryDismissalStopProcessing":
                # Final status already set if this was the cause
                pass
            elif str(e) == "NoDocsForLLMStopProcessing":
                # Final status already set if this was the cause
                pass
            else: # Unhandled/generic error
                logger.critical(error_msg, exc_info=True)
                page_to_shot = case_page if case_page and not case_page.is_closed() else dashboard_page
                if page_to_shot and not page_to_shot.is_closed():
                    await playwright_utils.safe_screenshot(page_to_shot, self.settings, "critical_case_proc_error", case_number_for_db)
                final_case_status = db_models.CaseStatusEnum.WORKER_ERROR
        finally:
            if case_page and not case_page.is_closed():
                try: await case_page.close()
                except Exception as e_close: logger.error(f"Error closing case_page in finally: {e_close}")
            
            if dashboard_page and not dashboard_page.is_closed():
                 logger.debug(f"[{case_number_for_db}] Clearing search on dashboard page post-processing.")
                 await self.unicourt_handler.clear_search_input(dashboard_page)

            # Clean up temporary downloaded files for this case
            try:
                if os.path.exists(temp_case_specific_download_path):
                    shutil.rmtree(temp_case_specific_download_path)
                    logger.info(f"[{case_number_for_db}] Successfully deleted temp download folder: {temp_case_specific_download_path}")
            except Exception as e_rm_final:
                logger.error(f"[{case_number_for_db}] Failed to delete temp download folder {temp_case_specific_download_path}: {e_rm_final}")

            # Update final case status in DB
            crud.update_case_status(self.db, case_id, final_case_status)
            logger.info(f"[{case_number_for_db}] Cleaned up. Final DB status: {final_case_status.value}")

    def _update_doc_summary_status(self, case_db_obj: db_models.Case, doc_name: str, doc_key: Optional[str], new_status: db_models.DocumentProcessingStatusEnum, notes: Optional[str] = None):
        """Helper to update a specific document's status in the summary list."""
        if case_db_obj.processed_documents_summary is None: # Should be initialized as []
            case_db_obj.processed_documents_summary = []
        
        summary_list = list(case_db_obj.processed_documents_summary) # Work with a mutable copy
        updated = False
        for item in summary_list:
            match_key = (item.get("unicourt_doc_key") == doc_key and doc_key is not None)
            match_name_if_no_key = (item.get("document_name") == doc_name and doc_key is None and item.get("unicourt_doc_key") is None)
            
            if match_key or match_name_if_no_key:
                item["status"] = new_status.value
                if notes: item["notes"] = notes # Add or overwrite notes
                logger.debug(f"[{case_db_obj.case_number}] Updated doc '{doc_name}' (Key: {doc_key}) status to '{new_status.value}' in summary.")
                updated = True
                break
        if not updated: # Should not happen if doc was added during download phase
            logger.warning(f"[{case_db_obj.case_number}] Doc '{doc_name}' (Key: {doc_key}) not found in summary to update LLM status. Adding new entry.")
            summary_list.append({
                "document_name": doc_name,
                "unicourt_doc_key": doc_key,
                "status": new_status.value,
                "notes": notes
            })
        
        case_db_obj.processed_documents_summary = summary_list # Assign back
        # Flag the JSON column as modified for SQLAlchemy to detect the change
        flag_modified(case_db_obj, "processed_documents_summary")
        try:
            self.db.commit()
            self.db.refresh(case_db_obj)
        except Exception as e:
            logger.error(f"[{case_db_obj.case_number}] DB error updating doc summary for '{doc_name}': {e}")
            self.db.rollback()

    def _doc_type_from_summary(self, summary_item: Dict[str, Any]) -> db_models.DocumentTypeEnum:
        # Helper to infer doc type from summary for logic (not stored in summary)
        # This is a simplified inference based on title
        title = summary_item.get("document_name", "")
        title_upper = title.upper()
        if all(kw.upper() in title_upper for kw in self.settings.DOC_KEYWORDS_FJ):
            return db_models.DocumentTypeEnum.FINAL_JUDGMENT
        if any(kw.upper() in title_upper for kw in self.settings.DOC_KEYWORDS_COMPLAINT):
            return db_models.DocumentTypeEnum.COMPLAINT
        return db_models.DocumentTypeEnum.UNKNOWN
