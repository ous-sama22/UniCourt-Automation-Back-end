# app/core/lifespan.py
import os
import asyncio
import logging
from contextlib import asynccontextmanager
from playwright.async_api import async_playwright
from app.core.config import get_app_settings
from app.services.unicourt_handler import UnicourtHandler

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan_manager(app):
    app_settings = get_app_settings() # Settings are loaded here, including CURRENT_DOWNLOAD_LOCATION
    logger.info("--- FastAPI App Starting Up (Lifespan Manager) ---")

    # Download location (where DB and session file reside) is now created during settings load
    # if it doesn't exist. Here we just confirm.
    download_loc = os.path.abspath(app_settings.CURRENT_DOWNLOAD_LOCATION)
    if not os.path.exists(download_loc):
        # This state should ideally be prevented by settings load creating it.
        # If it still doesn't exist, it's a critical issue.
        logger.critical(f"CRITICAL: Download directory {download_loc} does not exist and was not created during settings load.")
        app.state.service_ready = False
        yield 
        return

    # Temp case files directory (sibling to DB file within CURRENT_DOWNLOAD_LOCATION)
    temp_case_files_base_dir = os.path.join(download_loc, "temp_case_files")
    if not os.path.exists(temp_case_files_base_dir):
        try:
            os.makedirs(temp_case_files_base_dir, exist_ok=True)
            logger.info(f"Created base directory for temporary case files: {temp_case_files_base_dir}")
        except Exception as e:
            logger.critical(f"CRITICAL: Could not create temp case files base directory {temp_case_files_base_dir}: {e}")
            app.state.service_ready = False
            yield
            return
            
    # Debug screenshots directory
    debug_screenshots_dir = os.path.join(download_loc, "debug_screenshots")
    if not os.path.exists(debug_screenshots_dir):
        try:
            os.makedirs(debug_screenshots_dir, exist_ok=True)
            logger.info(f"Created directory for debug screenshots: {debug_screenshots_dir}")
        except Exception as e:
            logger.warning(f"Could not create debug screenshots directory {debug_screenshots_dir}: {e}. Screenshots may fail.")


    # Check essential configurations
    if not all([app_settings.UNICOURT_EMAIL, app_settings.UNICOURT_PASSWORD, app_settings.API_ACCESS_KEY]) or \
       app_settings.UNICOURT_EMAIL == "default_unicourt_email_please_configure@example.com" or \
       app_settings.API_ACCESS_KEY == "CONFIG_ERROR_API_KEY_NOT_IN_ENV":
        logger.critical("CRITICAL STARTUP FAILURE: UNICOURT_EMAIL, UNICOURT_PASSWORD, or API_ACCESS_KEY not set or is default.")
        app.state.service_ready = False
        yield
        logger.info("--- FastAPI App Shut Down (Lifespan - startup failed due to missing creds) ---")
        return

    logger.info("--- Initializing Playwright (Lifespan) ---")
    try:
        app.state.playwright_instance = await async_playwright().start()
        logger.info("--- Playwright Initialized (Lifespan) ---")
    except Exception as e:
        logger.critical(f"CRITICAL STARTUP FAILURE: Could not initialize Playwright: {e}")
        app.state.service_ready = False
        yield
        logger.info("--- FastAPI App Shut Down (Lifespan - playwright init failed) ---")
        return

    logger.info("--- Ensuring Unicourt Authenticated Session (Lifespan) ---")
    unicourt_handler = UnicourtHandler(app.state.playwright_instance, app_settings, dashboard_page_for_worker=None) 
    login_success = await unicourt_handler.ensure_authenticated_session()
    
    if not login_success:
        logger.critical("CRITICAL STARTUP FAILURE: Could not establish Unicourt authenticated session.")
        app.state.service_ready = False
    else:
        logger.info("--- Unicourt Session Ready (Lifespan) ---")
        app.state.service_ready = True
    
    app.state.settings = app_settings

    yield # Application is running

    logger.info("--- FastAPI App Shutting Down (Lifespan Manager) ---")
    app.state.shutting_down = True

    if hasattr(app.state, "background_worker_tasks") and app.state.background_worker_tasks:
        logger.info("Cancelling background workers...")
        for task in app.state.background_worker_tasks:
            if not task.done():
                task.cancel()
        worker_shutdown_timeout = app_settings.GENERAL_TIMEOUT_SECONDS * 2 
        try:
            await asyncio.wait_for(
                asyncio.gather(*[t for t in app.state.background_worker_tasks if not t.done()], return_exceptions=True),
                timeout=worker_shutdown_timeout
            )
            logger.info("All background workers cancelled/completed.")
        except asyncio.TimeoutError:
            logger.warning(f"Timeout waiting for background workers to complete shutdown after {worker_shutdown_timeout}s.")
        except Exception as e:
            logger.error(f"Error during background worker shutdown: {e}")

    if app.state.playwright_instance:
        logger.info("Stopping Playwright (Lifespan)...")
        try:
            await app.state.playwright_instance.stop()
            app.state.playwright_instance = None
            logger.info("Playwright stopped (Lifespan).")
        except Exception as e:
            logger.error(f"Error stopping Playwright: {e}")
    
    logger.info("--- FastAPI App Shutdown Complete (Lifespan Manager) ---")