# app/api/deps.py
from fastapi import Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.core.security import get_api_key
from app.core.config import AppSettings, get_app_settings
import logging

logger = logging.getLogger(__name__)

def get_current_settings(request: Request) -> AppSettings:
    if hasattr(request.app.state, 'settings') and request.app.state.settings is not None:
        return request.app.state.settings
    logger.warning("Settings not found in app.state or is None, attempting to load fresh. This should ideally not happen frequently post-startup.")
    return get_app_settings() # Fallback

class CommonDeps:
    def __init__(
        self,
        api_key: str = Depends(get_api_key),
        db: Session = Depends(get_db),
        settings: AppSettings = Depends(get_current_settings)
    ):
        self.api_key = api_key
        self.db = db
        self.settings = settings

def get_read_api_key(api_key: str = Depends(get_api_key)):
    return api_key

def get_write_api_key(api_key: str = Depends(get_api_key)):
    return api_key