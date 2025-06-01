# app/models_api/service.py
from pydantic import BaseModel, Field, EmailStr
from typing import Optional, Dict, Any

class ConfigUpdateRequest(BaseModel):
    UNICOURT_EMAIL: Optional[EmailStr] = None
    UNICOURT_PASSWORD: Optional[str] = None
    OPENROUTER_API_KEY: Optional[str] = None
    OPENROUTER_LLM_MODEL: Optional[str] = None
    EXTRACT_ASSOCIATED_PARTY_ADDRESSES: Optional[bool] = None

    class Config:
        extra = 'forbid'

class ConfigUpdateResponse(BaseModel):
    message: str
    updated_fields: Dict[str, Any]
    restart_required: bool

class ServiceStatusResponse(BaseModel):
    service_ready: bool
    unicourt_session_file_exists: bool
    current_queue_size: int
    active_processing_tasks_count: int
    distinct_cases_actively_processing_count: int
    max_concurrent_tasks: int 
    playwright_initialized: bool
    current_download_location: str
    extract_associated_party_addresses_enabled: bool