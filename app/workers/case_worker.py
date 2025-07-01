# app/workers/case_worker.py
import asyncio
import logging
from typing import Optional
from fastapi import FastAPI # For type hinting app state
from app.db.session import SessionLocal
from app.services.case_processor import CaseProcessorService
from app.services.unicourt_handler import UnicourtHandler
from app.services.llm_processor import LLMProcessor
from app.core.config import get_app_settings # To get current settings for worker

logger = logging.getLogger(__name__)

async def background_processor_worker(app: FastAPI, worker_id: int):
    worker_browser = None
    worker_context = None
    worker_dashboard_page = None
    worker_unicourt_handler = None
    worker_settings = get_app_settings()
    playwright_instance = app.state.playwright_instance
    
    async def initialize_browser_resources(retry_count=0):
        nonlocal worker_browser, worker_context, worker_dashboard_page, worker_unicourt_handler
        
        # Close any existing resources first
        if worker_unicourt_handler and worker_browser and worker_context:
            await worker_unicourt_handler.close_worker_browser_resources(worker_browser, worker_context)
        elif worker_context:
            await worker_context.close()
        elif worker_browser:
            await worker_browser.close()
        
        # Create fresh handler for setup
        temp_handler_for_setup = UnicourtHandler(playwright_instance, worker_settings)
        
        # On retry, force new session creation through login
        if retry_count > 0:
            logger.info(f"Worker {worker_id}: Attempting to create new session through login (retry {retry_count})...")
            login_success = await temp_handler_for_setup.ensure_authenticated_session()
            if not login_success:
                logger.error(f"Worker {worker_id}: Failed to create new session through login.")
                return False
                
        # Create new browser resources
        worker_browser, worker_context, worker_dashboard_page = \
            await temp_handler_for_setup.create_worker_browser_context_and_dashboard_page()

        if not worker_dashboard_page or not worker_browser or not worker_context:
            logger.error(f"Worker {worker_id}: Failed to initialize Playwright resources.")
            return False
            
        # Create the worker's handler with the new page
        worker_unicourt_handler = UnicourtHandler(playwright_instance, worker_settings, 
                                                dashboard_page_for_worker=worker_dashboard_page)
        logger.info(f"Worker {worker_id}: Playwright resources initialized successfully.")
        return True
    
    try:
        logger.info(f"Worker {worker_id}: Initializing Playwright browser context and dashboard page...")
        setup_success = await initialize_browser_resources()
        if not setup_success:
            logger.error(f"Worker {worker_id}: Initial setup failed. Worker cannot start.")
            return

        llm_processor = LLMProcessor(worker_settings)

        while not app.state.shutting_down:
            try:
                # Get case details from the queue
                # Queue items: (case_id, case_obj_from_queue: db_models.Case)
                case_id, _ = await asyncio.wait_for(app.state.case_processing_queue.get(), timeout=1.0)
                
                # Create a new database session for this iteration
                db_session = SessionLocal()
                try:
                    # Get a fresh copy of the case object from the database
                    from app.db import crud
                    case_obj_for_processing = crud.get_case_by_id(db_session, case_id)
                    if not case_obj_for_processing:
                        logger.error(f"Worker {worker_id}: Case with ID {case_id} not found in database")
                        app.state.case_processing_queue.task_done()
                        continue

                    case_number_for_db = case_obj_for_processing.case_number # For logging and tracking

                    logger.info(f"Worker {worker_id}: Picked up case {case_number_for_db} (ID: {case_id}) from queue.")

                    async with app.state.active_cases_lock:
                        if case_number_for_db in app.state.actively_processing_cases:
                            logger.warning(f"Worker {worker_id}: Case {case_number_for_db} (ID: {case_id}) is already being processed by another worker. Re-queuing.")
                            await app.state.case_processing_queue.put((case_id, case_obj_for_processing))
                            app.state.case_processing_queue.task_done() # Mark original task_done
                            await asyncio.sleep(0.1) # Small delay
                            continue
                        app.state.actively_processing_cases.add(case_number_for_db)
                    
                    async with app.state.processing_count_lock:
                        app.state.active_processing_count += 1
                    
                    logger.info(f"Worker {worker_id}: Starting processing for case {case_number_for_db} (ID: {case_id}). Active tasks: {app.state.active_processing_count}")

                    retry_count = 0
                    max_retries = 2
                    while retry_count <= max_retries:
                        try:
                            case_processor_service = CaseProcessorService(
                                db=db_session,
                                settings=worker_settings,
                                unicourt_handler=worker_unicourt_handler, # Pass worker-specific handler
                                llm_processor=llm_processor
                            )
                            await case_processor_service.process_single_case(case_id, case_obj_for_processing)
                            break  # Success, exit retry loop
                            
                        except Exception as e:
                            if retry_count < max_retries and ("Connection closed" in str(e) or "Failed to ensure Unicourt session" in str(e)):
                                retry_count += 1
                                logger.warning(f"Worker {worker_id}: Session error during processing. Attempting retry {retry_count}/{max_retries}...")
                                
                                # Try to reinitialize with new session
                                setup_success = await initialize_browser_resources(retry_count=retry_count)
                                if not setup_success:
                                    logger.error(f"Worker {worker_id}: Failed to reinitialize browser resources on retry {retry_count}")
                                    continue
                                
                                await asyncio.sleep(2)  # Brief pause before retry
                            else:
                                logger.critical(f"Worker {worker_id}: Unhandled error during case {case_number_for_db} (ID: {case_id}) processing: {e}", exc_info=True)
                                # Basic error status update in DB if process_single_case failed critically before setting status
                                from app.db import crud, models as db_models # Local import for safety
                                crud.update_case_status(db_session, case_id, db_models.CaseStatusEnum.WORKER_ERROR)
                                break  # Exit retry loop on non-session errors
                    
                    app.state.case_processing_queue.task_done()
                    async with app.state.active_cases_lock:
                        if case_number_for_db in app.state.actively_processing_cases:
                            app.state.actively_processing_cases.remove(case_number_for_db)
                    async with app.state.processing_count_lock:
                        app.state.active_processing_count -= 1
                    logger.info(f"Worker {worker_id}: Finished processing case {case_number_for_db} (ID: {case_id}). Active tasks: {app.state.active_processing_count}")
                finally:
                    db_session.close()

            except asyncio.TimeoutError:
                # Queue was empty, continue checking
                await asyncio.sleep(0.1) # Prevent tight loop when idle
            except asyncio.CancelledError:
                logger.info(f"Worker {worker_id}: Task cancelled. Shutting down.")
                break
            except Exception as e_outer:
                logger.error(f"Worker {worker_id}: Outer loop error: {e_outer}", exc_info=True)
                await asyncio.sleep(5) # Wait a bit before retrying to get from queue

    except asyncio.CancelledError:
        logger.info(f"Worker {worker_id}: Main task cancelled during setup or loop. Exiting.")
    except Exception as e_worker_setup:
        logger.critical(f"Worker {worker_id}: Fatal error during setup: {e_worker_setup}", exc_info=True)
    finally:
        if worker_unicourt_handler and worker_browser and worker_context: # If handler was successfully created
            logger.info(f"Worker {worker_id}: Closing Playwright resources...")
            await worker_unicourt_handler.close_worker_browser_resources(worker_browser, worker_context)
        elif worker_context: # If only context was created
             await worker_context.close()
        elif worker_browser: # If only browser was created
             await worker_browser.close()
        logger.info(f"Background Worker {worker_id}: Stopped.")

