# app/utils/playwright_utils.py
import asyncio
import logging
import os
from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError
from app.core.config import AppSettings, UnicourtSelectors # AppSettings needed
from app.utils.common import sanitize_filename # Moved import here
from app.core.config import get_app_settings # For accessing current settings
logger = logging.getLogger(__name__)

async def handle_cookie_banner_if_present(page: Page, settings: AppSettings):
    selectors: UnicourtSelectors = settings.UNICOURT_SELECTORS
    try:
        cookie_button = page.locator(selectors.COOKIE_AGREE_BUTTON)
        if await cookie_button.is_visible(timeout=3000):
            logger.info("Cookie consent banner found. Clicking 'I Agree'.")
            await cookie_button.click(timeout=settings.SHORT_TIMEOUT_SECONDS * 1000)
            await page.wait_for_timeout(1000) 
            logger.info("Cookie consent banner handled.")
            return True
    except PlaywrightTimeoutError:
        logger.debug("Cookie consent banner not found or not visible within timeout.")
    except Exception as e:
        logger.warning(f"Minor error handling cookie banner: {e}")
    return False

async def safe_screenshot(page: Page, settings: AppSettings, filename_prefix: str, details: str = ""):
    sane_details = sanitize_filename(details, max_length=50)
    screenshot_filename = f"debug_{filename_prefix}_{sane_details}.png"
    
    # Screenshots now go into a general debug_screenshots folder within the main download location
    # not inside case-specific folders, as those might be deleted.
    screenshot_path = os.path.join(settings.CURRENT_DOWNLOAD_LOCATION, "debug_screenshots", screenshot_filename)
    
    try:
        os.makedirs(os.path.dirname(screenshot_path), exist_ok=True)
        await page.screenshot(path=screenshot_path)
        logger.info(f"Debug screenshot saved: {screenshot_path}")
    except Exception as e:
        logger.error(f"Failed to save screenshot {screenshot_path}: {e}")

async def scroll_to_bottom_of_scrollable(page: Page, scrollable_container_selector: str, item_selector: str, section_name: str, case_identifier: str, no_change_threshold: int = 10):
    """
    Scrolls a specific container to load all items, like document lists.
    """
    logger.debug(f"[{case_identifier}] Scrolling in {section_name} using container '{scrollable_container_selector}' looking for '{item_selector}'.")

    scrollable_container = page.locator(scrollable_container_selector)
    if not await scrollable_container.is_visible(timeout=5000):
        logger.warning(f"[{case_identifier}] Scrollable container for {section_name} ('{scrollable_container_selector}') not visible. Skipping scroll.")
        return 0

    last_item_count = -1
    no_change_count = 0
    i = 0

    while True:
        current_items = await page.locator(item_selector).count()
        logger.debug(f"[{case_identifier}] {section_name} scroll attempt {i+1}: Found {current_items} items. Last count: {last_item_count}.")

        if current_items == last_item_count:
            no_change_count += 1
            if no_change_count >= no_change_threshold:
                logger.info(f"[{case_identifier}] {section_name} scrolling stabilized. Found {current_items} items after {no_change_count} scrolls with no new items.")
                break
        else:
            no_change_count = 0
            last_item_count = current_items
        
        await scrollable_container.evaluate("element => element.scrollTop = element.scrollHeight")
        try:
            # Wait for potential network activity or a short fixed delay
            await page.wait_for_load_state("networkidle", timeout=6000) # Shorter timeout for network idle
            i += 1
        except PlaywrightTimeoutError:
            await asyncio.sleep(4) # Fallback delay if network doesn't idle quickly
    return last_item_count