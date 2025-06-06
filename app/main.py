# app/main.py
import os
import asyncio
import logging
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from contextlib import asynccontextmanager 

from app.core.config import settings, AppSettings, get_app_settings, load_settings
from app.core.lifespan import lifespan_manager
from app.api.routers import cases as cases_router, cases as service_control_router, cases as health_router 
from app.workers.case_worker import background_processor_worker
from app.db.session import engine, SQLALCHEMY_DATABASE_URL 
from app.db.init_db import init_db

load_dotenv()
initial_settings = load_settings()

log_level_str = os.getenv("LOG_LEVEL", initial_settings.LOG_LEVEL if initial_settings else "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level_str, logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def app_lifespan(app_fastapi: FastAPI): # Renamed 'app' to 'app_fastapi' to avoid conflict
    logger.info("FastAPI application startup...")
    current_app_settings = get_app_settings() 
    logger.info(f"Using database at: {SQLALCHEMY_DATABASE_URL}")

    app_fastapi.state.playwright_instance = None # Initialized in lifespan_manager
    app_fastapi.state.active_processing_count = 0
    app_fastapi.state.processing_count_lock = asyncio.Lock()
    app_fastapi.state.case_processing_queue = asyncio.Queue()
    app_fastapi.state.actively_processing_cases = set() 
    app_fastapi.state.active_cases_lock = asyncio.Lock()
    app_fastapi.state.background_worker_tasks = []
    app_fastapi.state.service_ready = False 
    app_fastapi.state.shutting_down = False

    async with lifespan_manager(app_fastapi): # lifespan_manager handles Playwright setup
        init_db() 

        if app_fastapi.state.service_ready:
            for i in range(current_app_settings.MAX_CONCURRENT_TASKS):
                task = asyncio.create_task(background_processor_worker(app_fastapi, worker_id=i))
                app_fastapi.state.background_worker_tasks.append(task)
            logger.info(f"Started {len(app_fastapi.state.background_worker_tasks)} background worker(s).")
        else:
            logger.error("Service not ready after lifespan setup. Workers not started.")
        
        logger.info("FastAPI application startup complete.")
        yield
        logger.info("FastAPI application shutdown...")
        # Cleanup handled in lifespan_manager
    logger.info("FastAPI application shutdown complete.")


app = FastAPI( # FastAPI app instance
    title="Unicourt Case Processor API",
    lifespan=app_lifespan,
    openapi_url="/api/v1/openapi.json"
)

app.include_router(health_router.router, prefix="/api/v1", tags=["Health"])
app.include_router(cases_router.router, prefix="/api/v1/cases", tags=["Cases"])
app.include_router(service_control_router.router, prefix="/api/v1/service", tags=["Service Control"])


@app.middleware("http")
async def settings_middleware(request: Request, call_next):
    if not hasattr(request.app.state, 'settings') or request.app.state.settings is None:
        # This ensures settings are available, especially if lifespan_manager had issues
        # or if settings were cleared and not reloaded by a subsequent request quickly.
        logger.debug("Settings middleware: app.state.settings not found or None, ensuring fresh load.")
        request.app.state.settings = get_app_settings() 
    response = await call_next(request)
    return response

if __name__ == "__main__":
    import uvicorn
    # Settings should be loaded by now via `initial_settings = load_settings()` at module level
    effective_settings = get_app_settings()
    host = effective_settings.HOST
    port = effective_settings.PORT
    reload_dev = os.getenv("RELOAD_DEV", "false").lower() == "true"
    effective_log_level_str = effective_settings.LOG_LEVEL # Use from loaded settings

    logger.info(f"Starting Uvicorn server on {host}:{port} (Reload: {reload_dev}, LogLevel: {effective_log_level_str})")

    uvicorn.run(
        "app.main:app", # Assuming main.py is in 'app' directory, and run from parent
        host=host,
        port=port,
        reload=reload_dev,
        log_level=effective_log_level_str.lower()
    )