# app/services/llm_processor.py
import base64
import json
import httpx
import logging
from typing import Tuple, Optional, Dict, List, Any

from pydantic import BaseModel
from app.core.config import AppSettings
from app.db.models import DocumentTypeEnum # For type hint if needed
import fitz  # PyMuPDF
from PIL import Image
import io
import os
import asyncio

logger = logging.getLogger(__name__)

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

# Define the structure we expect from the LLM
class LLMResponseData(BaseModel):
    original_creditor_name: Optional[str] = None
    creditor_address: Optional[str] = None
    associated_parties: List[Dict[str, str]] = [] # List of {"name": "...", "address": "..."}
    creditor_registration_state: Optional[str] = None

class LLMProcessor:
    def __init__(self, settings: AppSettings):
        self.settings = settings

    def _convert_file_to_images(self, file_path: str) -> Tuple[List[str], str]: # Renamed
        processing_notes = ""
        image_base64_list = []
        file_extension = os.path.splitext(file_path)[1].lower()

        try:
            if file_extension == ".pdf":
                pdf_document = fitz.open(file_path)
                for page_num in range(len(pdf_document)):
                    page = pdf_document[page_num]
                    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2)) # Higher DPI
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    
                    img_byte_arr = io.BytesIO()
                    img.save(img_byte_arr, format='PNG') # Convert to PNG for consistency
                    img_base64 = base64.b64encode(img_byte_arr.getvalue()).decode('utf-8')
                    image_base64_list.append(img_base64)
                pdf_document.close()
                processing_notes = f"Converted PDF to {len(image_base64_list)} PNG images."

            elif file_extension == ".tif" or file_extension == ".tiff":
                img_tiff = Image.open(file_path)
                for i in range(img_tiff.n_frames): # Handle multi-page TIFFs
                    img_tiff.seek(i)
                    # Convert to RGB if not already (some TIFFs can be B/W or other modes)
                    img_page = img_tiff.convert("RGB") 
                    
                    img_byte_arr = io.BytesIO()
                    img_page.save(img_byte_arr, format='PNG') # Convert to PNG
                    img_base64 = base64.b64encode(img_byte_arr.getvalue()).decode('utf-8')
                    image_base64_list.append(img_base64)
                processing_notes = f"Converted TIFF to {len(image_base64_list)} PNG images."
            else:
                return [], f"Unsupported file type for image conversion: {file_extension}"

            if not image_base64_list:
                return [], f"File at {file_path} converted to 0 images."
            return image_base64_list, processing_notes
            
        except Exception as e:
            error_msg = f"Failed to convert {file_path} to images: {type(e).__name__} - {str(e)}"
            logger.error(error_msg, exc_info=True)
            return [], error_msg

    def _build_dynamic_prompt(
        self,
        input_creditor_name: str,
        is_business: bool,
        target_associated_party_names: List[str], # Names for whom addresses are still needed
        info_needed: Dict[str, bool] # {"creditor_address": True, "reg_state": False, "original_creditor_name": True ...}
    ) -> str:
        prompt_parts = [
            f"You are an expert legal assistant analyzing a court document (provided as images). The primary creditor of interest is '{input_creditor_name}'."
            "Please extract the following information based *only* on the content of the provided document images:"
        ]

        if info_needed.get("original_creditor_name"):
            prompt_parts.append(
                "- **Original Creditor Full Name**: The full legal name of the primary creditor entity or individual as it appears *exactly* in this document. This might differ slightly from the input name due to typos or variations."
            )
        if info_needed.get("creditor_address"):
            prompt_parts.append(
                f"- **Creditor Address**: The complete mailing address for the primary creditor, '{input_creditor_name}' (or its variation found in the document)."
            )
        
        if target_associated_party_names and info_needed.get("associated_parties_addresses"):
            party_list_str = ", ".join([f"'{name}'" for name in target_associated_party_names])
            prompt_parts.append(
                f"- **Associated Party Addresses**: For each of the following associated parties, if mentioned, provide their full mailing address: {party_list_str}. If a party is not found or their address is not present, omit them from the 'associated_parties' list in the JSON."
            )
        
        if is_business and info_needed.get("reg_state"):
            prompt_parts.append(
                f"- **Creditor Registration State**: Identify state of registration or incorporation for the {input_creditor_name} (if mentioned)."
            )
        
        prompt_parts.append(
            "\nProvide the output STRICTLY in the following JSON format. If a specific piece of information is not found in THIS document, set its value to null (not 'Not Found' or any other string). For 'associated_parties', only include parties for whom an address was found in THIS document."
        )
        prompt_parts.append(
            """
```json
{
  "original_creditor_name": "...",
  "creditor_address": "...",
  """)
        if target_associated_party_names and info_needed.get("associated_parties_addresses"):
            prompt_parts.append(
                """
                "associated_parties": [
                    {"name": "Associated Party Name 1", "address": "Address for Party 1..."},
                    {"name": "Associated Party Name 2", "address": "Address for Party 2..."}
                ],
                """)  
        if is_business and info_needed.get("reg_state"):
            prompt_parts.append(
                """
                "\ncreditor_registration_state": "..."
                """
            )
        prompt_parts.append(
            """
}
```
Ensure all string values are properly escaped within the JSON. If a top-level field like 'creditor_address' is not requested because it was already found, you can omit it or set its value to null in your response. The 'associated_parties' list should only contain entries for the parties explicitly requested and in the example json output (if any. If it's not needed you will not see the "associated_parties" key) AND for whom an address was found in this document. """ )
        return "\n".join(prompt_parts)

    def _strip_markdown_json(self, text: str) -> str:
        """Strips JSON markdown code fences if present."""
        text = text.strip()
        if text.startswith("```json") and text.endswith("```"):
            text = text[len("```json"): -len("```")]
        elif text.startswith("```") and text.endswith("```"): # Generic markdown fence
            text = text[len("```"): -len("```")]
        return text.strip()

    async def _call_llm_with_image_batch(
        self,
        image_batch_b64: List[str], # A subset of images
        prompt_text: str,
        attempt: int = 1
    ) -> Tuple[Optional[Dict[str, Any]], str]: # Returns raw JSON dict from LLM or None, and notes
        """Helper to make a single API call with a batch of images."""
        headers = {
            "Authorization": f"Bearer {self.settings.OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": self.settings.INITIAL_URL,
            "User-Agent": "UniCourtProcessor/1.1",
            "X-Title": "UniCourt Processor Backend"
        }

        logger.debug(f"Preparing LLM call with {len(image_batch_b64)} images for prompt: {prompt_text}... (Attempt {attempt})")
        
        content_parts: List[Dict[str, Any]] = [{"type": "text", "text": prompt_text}]
        for img_b64 in image_batch_b64:
            content_parts.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}})

        data = {
            "model": self.settings.OPENROUTER_LLM_MODEL,
            "messages": [{"role": "user", "content": content_parts}],
            "max_tokens": 1500,
            "temperature": 0.1
        }
        
        try:
            async with httpx.AsyncClient(timeout=self.settings.LLM_TIMEOUT_SECONDS) as client:
                logger.info(f"Calling LLM API (attempt {attempt}) with {len(image_batch_b64)} images.")
                response = await client.post(OPENROUTER_API_URL, headers=headers, json=data)
                response.raise_for_status()
                response_json = response.json()
                message_content_str = response_json.get("choices", [{}])[0].get("message", {}).get("content", "")
                
                if not message_content_str:
                    return None, "LLM response content is empty."

                # Strip markdown fences before parsing
                cleaned_json_str = self._strip_markdown_json(message_content_str)
                
                try:
                    extracted_json_dict = json.loads(cleaned_json_str)
                    return extracted_json_dict, "LLM call successful, content parsed to dict."
                except json.JSONDecodeError as e_json:
                    # Log the cleaned string as well for better debugging
                    return None, f"Failed to parse JSON from LLM response. Cleaned string: '{cleaned_json_str}'.\nOriginal string: '{message_content_str}'.\nError: {e_json}"
        except httpx.HTTPStatusError as e:
            return None, f"LLM API HTTP Error {e.response.status_code} (attempt {attempt}): {e.response.text}"
        except httpx.RequestError as e:
            return None, f"LLM API Request Error (attempt {attempt}): {str(e)}"
        except Exception as e:
            return None, f"Unexpected LLM call error (attempt {attempt}): {type(e).__name__} - {str(e)}"


    async def extract_info_from_document_images( # Renamed from extract_info_from_pdf_images
        self,
        all_images_base64: List[str],
        input_creditor_name: str,
        is_business: bool,
        target_associated_party_names: List[str],
        info_to_extract_for_doc: Dict[str, bool], # What's needed for *this document's current pass*
        max_images_per_llm_call: int = 10, # New parameter for batching
        max_llm_attempts_per_batch: int = 2 # New parameter for retries
    ) -> Tuple[Optional[LLMResponseData], str]:

        if not all_images_base64:
            return None, "No document image content provided to LLM."
        if not self.settings.OPENROUTER_API_KEY or not self.settings.OPENROUTER_LLM_MODEL or \
           self.settings.OPENROUTER_API_KEY == "default_openrouter_api_key_please_configure":
            msg = "OpenRouter API Key or Model not configured or is default."
            logger.error(msg)
            return None, msg
        
        if not any(info_to_extract_for_doc.values()):
            # This check should ideally happen before calling this function (e.g., in case_processor)
            # but as a safeguard:
            logger.info("No new information specifically requested from LLM for this document processing pass.")
            return LLMResponseData(), "No specific information requested for this LLM pass." 

        num_images = len(all_images_base64)
        num_batches = (num_images + max_images_per_llm_call - 1) // max_images_per_llm_call
        
        aggregated_llm_data = LLMResponseData() # To accumulate results if batching
        all_batch_notes: List[str] = []
        
        # Dynamic prompt will be the same for all batches of this document,
        # but it reflects what's *still needed* for the document overall.
        # The case_processor will handle what's needed for the *case*.
        prompt_text = self._build_dynamic_prompt(
            input_creditor_name, 
            is_business, 
            target_associated_party_names, # All targets for the case
            info_to_extract_for_doc # What this document pass is trying to find
        )

        for i in range(num_batches):
            start_index = i * max_images_per_llm_call
            end_index = min((i + 1) * max_images_per_llm_call, num_images)
            image_batch = all_images_base64[start_index:end_index]
            
            logger.info(f"Processing image batch {i+1}/{num_batches} (images {start_index+1}-{end_index}) for document.")

            raw_json_dict: Optional[Dict[str, Any]] = None
            batch_note = ""

            for attempt in range(1, max_llm_attempts_per_batch + 1):
                raw_json_dict, batch_note = await self._call_llm_with_image_batch(image_batch, prompt_text, attempt)
                if raw_json_dict is not None: # Successful call and JSON parsing
                    break 
                logger.warning(f"LLM batch {i+1} attempt {attempt} failed. Note: {batch_note}")
                if attempt < max_llm_attempts_per_batch:
                    await asyncio.sleep(2) # Wait before retrying
            
            all_batch_notes.append(f"Batch {i+1}: {batch_note}")

            if raw_json_dict:
                try:
                    # Convert any "Not Found" strings to None for consistency
                    for key in raw_json_dict:
                        if key != "associated_parties" and raw_json_dict[key] == "Not Found":
                            raw_json_dict[key] = None
                    
                    # Validate and merge data from this batch
                    batch_llm_data = LLMResponseData(**raw_json_dict)
                    
                    # Merge logic: Prioritize newly found data
                    if batch_llm_data.original_creditor_name and not aggregated_llm_data.original_creditor_name:
                        aggregated_llm_data.original_creditor_name = batch_llm_data.original_creditor_name
                    if batch_llm_data.creditor_address and not aggregated_llm_data.creditor_address:
                        aggregated_llm_data.creditor_address = batch_llm_data.creditor_address
                    if batch_llm_data.creditor_registration_state and not aggregated_llm_data.creditor_registration_state:
                        aggregated_llm_data.creditor_registration_state = batch_llm_data.creditor_registration_state
                    
                    # Merge associated parties, avoiding duplicates by name
                    existing_assoc_party_names = {p["name"] for p in aggregated_llm_data.associated_parties if p.get("name")}
                    for new_party in batch_llm_data.associated_parties:
                        if new_party.get("name") and new_party.get("address") and new_party["name"] not in existing_assoc_party_names:
                            aggregated_llm_data.associated_parties.append(new_party)
                            existing_assoc_party_names.add(new_party["name"])
                            
                except Exception as e_val:
                    all_batch_notes.append(f"Batch {i+1} Pydantic/Merge Error: {e_val}. Data: {str(raw_json_dict)[:200]}")
                    logger.warning(f"Error validating/merging LLM data for batch {i+1}: {e_val}")
            else:
                logger.error(f"LLM processing failed for batch {i+1} after {max_llm_attempts_per_batch} attempts.")
                # If any batch fails completely, we might return None for the whole document
                # or return what was aggregated so far. For now, let's be strict.
                return None, "; ".join(all_batch_notes)

        # Check if any meaningful data was aggregated
        if not aggregated_llm_data.original_creditor_name and \
           not aggregated_llm_data.creditor_address and \
           not aggregated_llm_data.creditor_registration_state and \
           not aggregated_llm_data.associated_parties:
            if any("LLM call successful" in note for note in all_batch_notes): # LLM ran but found nothing
                 return aggregated_llm_data, "LLM processed all batches but found no requested data. Notes: " + "; ".join(all_batch_notes) # Return empty but valid LLMResponseData
            return None, "LLM processing failed to yield any data after all batches. Notes: " + "; ".join(all_batch_notes)


        return aggregated_llm_data, "Successfully processed all image batches. Notes: " + "; ".join(all_batch_notes)


    async def process_document_for_case_info( # Renamed from process_pdf_for_case_info
        self,
        doc_full_path: str,
        input_creditor_name: str,
        is_business: bool,
        target_associated_party_names: List[str], # For the whole case
        info_to_extract_for_doc: Dict[str, bool], # Specifically for this document pass
        max_images_per_llm_call: int,
        max_llm_attempts_per_batch: int

    ) -> Tuple[Optional[LLMResponseData], str]:
        
        logger.info(f"Starting LLM processing for document: {doc_full_path}")
        images_base64, conv_notes = self._convert_file_to_images(doc_full_path) # Use new method
        
        if not images_base64:
            logger.error(f"Document to images conversion failed for {doc_full_path}. Notes: {conv_notes}")
            return None, f"File_Conversion_Failed: {conv_notes}"
            
        llm_data, llm_api_notes = await self.extract_info_from_document_images(
            images_base64, 
            input_creditor_name, 
            is_business, 
            target_associated_party_names,
            info_to_extract_for_doc,
            max_images_per_llm_call=max_images_per_llm_call,
            max_llm_attempts_per_batch=max_llm_attempts_per_batch
        )
        combined_notes = f"Conv: {conv_notes}. LLM: {llm_api_notes}".strip()
        
        if llm_data is not None: # Could be an empty LLMResponseData if nothing found
            logger.info(f"LLM processing for document {doc_full_path} completed.")
        else: # Hard failure
            logger.warning(f"Failed to extract info from {doc_full_path} using LLM. Notes: {combined_notes}")
            
        return llm_data, combined_notes