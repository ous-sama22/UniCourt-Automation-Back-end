# app/core/security.py
from fastapi import Security, HTTPException, status
from fastapi.security.api_key import APIKeyHeader
from app.core.config import get_app_settings # Use get_app_settings to ensure loaded
import secrets
import logging

logger = logging.getLogger(__name__)

API_KEY_NAME = "X-API-KEY"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

async def get_api_key(api_key_header_value: str = Security(api_key_header)):
    settings = get_app_settings() # Get current settings instance
    if not settings.API_ACCESS_KEY or settings.API_ACCESS_KEY == "CONFIG_ERROR_API_KEY_NOT_IN_ENV":
        logger.critical("API_ACCESS_KEY is not configured on the server or is default. Denying all API access.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="API Key not configured on server. Access denied.",
        )
    if api_key_header_value and secrets.compare_digest(api_key_header_value, settings.API_ACCESS_KEY):
        return api_key_header_value
    
    logger.warning(f"Invalid API Key attempt. Provided key: '{api_key_header_value[:10] if api_key_header_value else 'None'}...'")
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Invalid or missing API Key.",
    )