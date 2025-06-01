# app/utils/common.py
import asyncio
import random
import time
import os
import re
import logging
from typing import Optional, List, Dict, Any
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger(__name__)

async def random_delay(min_seconds=1.0, max_seconds=2.5, reason: Optional[str] = None):
    delay = random.uniform(min_seconds, max_seconds)
    if reason:
        logger.debug(f"Delaying for {delay:.2f}s: {reason}")
    else:
        logger.debug(f"Delaying for {delay:.2f}s")
    await asyncio.sleep(delay)

def sanitize_filename(name: str, default_name: str = "unnamed_document", max_length: int = 100) -> str:
    if not name:
        name = default_name
    
    name = str(name)
    # Remove or replace characters invalid in Windows/Linux/MacOS filenames
    name = re.sub(r'[<>:"/\\|?*]', '_', name) 
    # Remove control characters and other non-printable characters, keep alphanumeric, spaces, dots, hyphens
    name = re.sub(r'[^\w\s.-]', '', name) 
    # Replace multiple spaces/hyphens with a single hyphen, strip leading/trailing hyphens/underscores
    name = re.sub(r'[-\s]+', '-', name).strip('-_') 
    
    base, ext = os.path.splitext(name)
    # Ensure extension is not part of the length check for the base
    if len(base) > max_length:
        base = base[:max_length]
    
    name = base + ext
    if not name or name == ext : # If sanitization resulted in an empty string or just an extension
        name = default_name
        if ext and default_name != "unnamed_document": # try to preserve original extension if possible
            name = default_name.split('.')[0] + ext
    return name


def extract_unicourt_document_key(url: str) -> Optional[str]:
    """
    Extracts a unique document key from a Unicourt PDF URL.
    Prioritizes the 'key' query parameter.
    """
    if not url:
        return None
    try:
        parsed_url = urlparse(url)
        query_params = parse_qs(parsed_url.query)
        
        if 'key' in query_params and query_params['key']:
            doc_key = query_params['key'][0]
            logger.debug(f"Extracted document key '{doc_key}' from URL query parameter.")
            return doc_key

        path_parts = [part for part in parsed_url.path.split('/') if part]
        if len(path_parts) >= 3 and path_parts[0] == 'file' and path_parts[1] == 'researchCourtCaseFile':
            potential_path_key = path_parts[2]
            logger.warning(f"URL '{url}' missing 'key' query param. Using path component '{potential_path_key}' as potential key. Verify if this is a stable document ID.")
            return potential_path_key
            
    except Exception as e:
        logger.error(f"Error parsing URL '{url}' to extract document key: {e}")
    
    logger.warning(f"Could not determine a unique document key from URL: {url}")
    return None

def clean_html_text(text: Optional[str]) -> str:
    """Basic cleaning of text extracted from HTML (e.g., inner_text())."""
    if not text:
        return ""
    text = text.replace('\n', ' ').replace('\r', ' ') # Replace newlines with spaces
    text = re.sub(r'\s+', ' ', text) # Compact multiple spaces
    return text.strip()