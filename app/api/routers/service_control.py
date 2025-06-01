# app/api/routers/service_control_router.py
import os
import sys
import asyncio
import logging
from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Request, status
from app.core.config import AppSettings
from app.api.deps import get_write_api_key, get_current_settings
from app.models_api import service as api_models
from app.services.config_manager import ConfigManager

logger = logging.getLogger(__name__)
router = APIRouter()

config_manager_instance = ConfigManager() # Create an instance

@router.get("/status", response_model=api_models.ServiceStatusResponse)
async def get_service_status_info(
    request: Request,
    settings: AppSettings = Depends(get_current_settings),
    api_key: str = Depends(get_write_api_key) 
):
    num_actively_processing_from_set = len(request.app.state.actively_processing_cases) if hasattr(request.app.state, 'actively_processing_cases') else 0
    active_processing_counter = request.app.state.active_processing_count if hasattr(request.app.state, 'active_processing_count') else 0
    queue_size = request.app.state.case_processing_queue.qsize() if hasattr(request.app.state, 'case_processing_queue') else 0
    
    session_file_path = settings.UNICOURT_SESSION_PATH
    unicourt_session_ok = os.path.exists(session_file_path)

    return api_models.ServiceStatusResponse(
        service_ready=getattr(request.app.state, "service_ready", False),
        unicourt_session_file_exists=unicourt_session_ok,
        current_queue_size=queue_size,
        active_processing_tasks_count=active_processing_counter,
        distinct_cases_actively_processing_count=num_actively_processing_from_set,
        max_concurrent_tasks=settings.MAX_CONCURRENT_TASKS,
        playwright_initialized=hasattr(request.app.state, 'playwright_instance') and request.app.state.playwright_instance is not None,
        current_download_location=settings.CURRENT_DOWNLOAD_LOCATION,
        extract_associated_party_addresses_enabled=settings.EXTRACT_ASSOCIATED_PARTY_ADDRESSES
    )

@router.get("/config", response_model=Dict[str, Any])
async def get_current_client_configuration(
    api_key: str = Depends(get_write_api_key)
):
    try:
        return config_manager_instance.get_current_client_config_dict()
    except Exception as e:
        logger.error(f"Failed to get client configuration: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Could not read client configuration: {e}")


@router.put("/config", response_model=api_models.ConfigUpdateResponse)
async def update_client_configuration(
    update_payload: api_models.ConfigUpdateRequest,
    api_key: str = Depends(get_write_api_key)
):
    logger.info(f"Received request to update client configuration: {update_payload.model_dump(exclude_unset=True)}")
    try:
        changed_fields, restart_needed = config_manager_instance.update_client_config(update_payload)
        
        if not changed_fields:
            return api_models.ConfigUpdateResponse(
                message="No client-configurable settings were changed.",
                updated_fields={},
                restart_required=False
            )
        msg = "Client configuration updated successfully. A server restart is required for changes to take effect."
        return api_models.ConfigUpdateResponse(
            message=msg,
            updated_fields=changed_fields,
            restart_required=restart_needed
        )
    except Exception as e:
        logger.error(f"Failed to update client configuration: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Could not update client configuration: {e}")

@router.post("/request-restart", status_code=status.HTTP_202_ACCEPTED)
async def request_server_restart(
    request: Request, 
    api_key: str = Depends(get_write_api_key)
):
    logger.info("Received request for server restart.")
    if not hasattr(request.app.state, 'case_processing_queue') or \
       not hasattr(request.app.state, 'active_processing_count'):
        logger.error("Server state not fully initialized. Cannot process restart request safely.")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Server state error, cannot restart.")

    queue_size = request.app.state.case_processing_queue.qsize()
    active_tasks = request.app.state.active_processing_count

    if queue_size == 0 and active_tasks == 0:
        logger.info("Queue is empty and no active tasks. Proceeding with graceful shutdown signal.")
        request.app.state.shutting_down = True 
        async def delayed_exit():
            await asyncio.sleep(0.5) 
            logger.info("Exiting process for restart (expected to be handled by systemd or external manager)...")
            sys.exit(0) 
        asyncio.create_task(delayed_exit()) # Use asyncio.create_task for modern Python
        return {"message": "Server shutdown initiated. External process manager (e.g., systemd) should restart the application."}
    else:
        logger.warning(f"Cannot restart now. Queue size: {queue_size}, Active tasks: {active_tasks}.")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot restart: {queue_size} case(s) in queue, {active_tasks} task(s) actively processing."
        )