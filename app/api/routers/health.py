# app/api/routers/health_router.py
from fastapi import APIRouter, Request, status
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/healthz", status_code=status.HTTP_200_OK, summary="Health Check")
async def health_check(request: Request):
    service_is_ready = getattr(request.app.state, "service_ready", False)
    playwright_ok = hasattr(request.app.state, 'playwright_instance') and request.app.state.playwright_instance is not None
    
    if service_is_ready and playwright_ok:
        return {"status": "healthy", "message": "Service is ready, Unicourt session active, and Playwright is initialized."}
    elif playwright_ok and not service_is_ready:
        logger.warning("Health check: Playwright OK, but service not fully ready (e.g., Unicourt session failed).")
        return {"status": "degraded", "message": "Playwright initialized, but service not fully ready (e.g., Unicourt session failed)."}
    else:
        logger.error("Health check: Playwright not initialized or service in a bad state.")
        return {"status": "unhealthy", "message": "Playwright not initialized or service not ready."}
