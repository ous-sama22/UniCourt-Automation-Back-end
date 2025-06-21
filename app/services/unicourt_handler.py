# app/services/unicourt_handler.py
import os
import asyncio
import logging
import re
from datetime import datetime
from typing import Optional, Tuple, List, Set, Dict, Any, AsyncGenerator
from pydantic import BaseModel
from playwright.async_api import Playwright, Page, BrowserContext, Browser, TimeoutError as PlaywrightTimeoutError, expect, Download, Locator

from app.core.config import AppSettings, UnicourtSelectors
from app.db.models import DocumentTypeEnum, DocumentProcessingStatusEnum # Enums for logic
from app.utils import playwright_utils, common 

logger = logging.getLogger(__name__)

# Structure for transient document info during processing
class TransientDocumentInfo(BaseModel):
    original_title: str
    unicourt_doc_key: Optional[str] = None
    document_type: DocumentTypeEnum # FJ or Complaint
    # For "Paid" section, we need to track the row locator to re-evaluate after ordering
    paid_section_row_locator: Optional[Locator] = None 
    # For "CrowdSourced", we might have a direct link locator
    crowdsourced_section_link_locator: Optional[Locator] = None
    cost_str: Optional[str] = None # If from paid section
    # This will hold the path to the temporarily downloaded file
    temp_local_path: Optional[str] = None 
    # Final processing status for this document
    processing_status: DocumentProcessingStatusEnum = DocumentProcessingStatusEnum.IDENTIFIED_FOR_PROCESSING
    processing_notes: Optional[str] = None

    class Config:
        arbitrary_types_allowed = True  # Allow Playwright Locator objects


class UnicourtHandler:
    def __init__(self, playwright_instance: Playwright, settings: AppSettings, dashboard_page_for_worker: Optional[Page] = None):
        self.playwright = playwright_instance
        self.settings = settings
        self.selectors: UnicourtSelectors = settings.UNICOURT_SELECTORS
        self.dashboard_page_for_worker: Optional[Page] = dashboard_page_for_worker

    async def _launch_browser(self) -> Browser:
        browser_launch_args = ['--disable-blink-features=AutomationControlled', '--no-sandbox']
        return await self.playwright.chromium.launch(headless=True, args=browser_launch_args)

    def _get_common_context_options(self) -> Dict:
        return {
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "viewport": {"width": 1920, "height": 1080},
            "java_script_enabled": True,
            "accept_downloads": True # Important for direct downloads
        }

    async def _perform_headless_automated_login(self, page: Page) -> bool:
        email = self.settings.UNICOURT_EMAIL
        password = self.settings.UNICOURT_PASSWORD
        if not email or not password or email == "default_unicourt_email_please_configure@example.com":
            logger.error("UNICOURT_EMAIL or UNICOURT_PASSWORD not set or is default in configuration.")
            return False
        logger.info("Attempting fully headless automated login...")
        try:
            await page.goto(self.settings.INITIAL_URL, wait_until="networkidle", timeout=self.settings.GENERAL_TIMEOUT_SECONDS * 1000)
            await playwright_utils.handle_cookie_banner_if_present(page, self.settings)
            
            # Check if already logged in (e.g., due to a valid session file being loaded by context)
            if self.settings.DASHBOARD_URL_IDENTIFIER in page.url:
                 if await page.locator(self.selectors.DASHBOARD_LOGIN_SUCCESS_DETECTOR).is_visible(timeout=3000):
                    logger.info("Already on dashboard and logged in. Login not needed.")
                    return True
            
            if self.settings.LOGIN_PAGE_URL_IDENTIFIER not in page.url:
                logger.info(f"Not on login page (current: {page.url}). Navigating to login page.")
                await page.goto(self.settings.INITIAL_URL, wait_until="networkidle", timeout=self.settings.GENERAL_TIMEOUT_SECONDS * 1000)
                if self.settings.DASHBOARD_URL_IDENTIFIER in page.url: # Check again after navigation
                    if await page.locator(self.selectors.DASHBOARD_LOGIN_SUCCESS_DETECTOR).is_visible(timeout=3000):
                        logger.info("Navigated to dashboard, already logged in.")
                        return True


            await page.wait_for_selector(self.selectors.EMAIL_INPUT, timeout=self.settings.GENERAL_TIMEOUT_SECONDS * 1000, state="visible")
            logger.info("Login form elements detected.")
            await page.fill(self.selectors.EMAIL_INPUT, email)
            await common.random_delay(0.5, 1.0)
            await page.fill(self.selectors.PASSWORD_INPUT, password)
            await common.random_delay(0.5, 1.0)
            login_button = page.locator(self.selectors.LOGIN_BUTTON)
            await expect(login_button).to_be_enabled(timeout=self.settings.SHORT_TIMEOUT_SECONDS * 1000)
            
            async with page.expect_navigation(wait_until="networkidle", timeout=self.settings.GENERAL_TIMEOUT_SECONDS * 1000 * 1.5):
                await login_button.click()
            logger.info(f"Navigation after login click completed. Current URL: {page.url}")
            await playwright_utils.handle_cookie_banner_if_present(page, self.settings)
            await page.wait_for_selector(self.selectors.DASHBOARD_LOGIN_SUCCESS_DETECTOR, timeout=self.settings.GENERAL_TIMEOUT_SECONDS * 1000, state="visible")
            logger.info("Headless automated login successful: Target dashboard detector visible.")
            return True
        except PlaywrightTimeoutError as e:
            logger.error(f"Timeout during headless automated login: {e}")
            await playwright_utils.safe_screenshot(page, self.settings, "headless_login_timeout")
            return False
        except Exception as e:
            logger.error(f"An error occurred during headless automated login: {e}", exc_info=True)
            await playwright_utils.safe_screenshot(page, self.settings, "headless_login_error")
            return False

    async def ensure_authenticated_session(self, page_to_check: Optional[Page] = None) -> bool:
        session_file_path = self.settings.UNICOURT_SESSION_PATH
        browser: Optional[Browser] = None
        context: Optional[BrowserContext] = None
        page_for_ops: Optional[Page] = None

        try:
            if page_to_check and not page_to_check.is_closed():
                logger.info(f"Checking provided page for valid session. URL: {page_to_check.url}")
                if self.settings.DASHBOARD_URL_IDENTIFIER in page_to_check.url.lower():
                    try:
                        await page_to_check.wait_for_selector(self.selectors.DASHBOARD_LOGIN_SUCCESS_DETECTOR, timeout=3000, state="visible")
                        logger.info("Provided page is on dashboard and seems valid.")
                        if page_to_check.context:
                           await page_to_check.context.storage_state(path=session_file_path)
                        return True
                    except PlaywrightTimeoutError:
                        logger.warning("Provided page is on dashboard URL but success detector not found. Session might be stale.")
                elif self.settings.LOGIN_PAGE_URL_IDENTIFIER in page_to_check.url.lower():
                    logger.warning("Provided page is on login page. Session is invalid.")
                    page_for_ops = page_to_check
                else:
                    logger.info(f"Provided page URL '{page_to_check.url}' not dashboard/login. Attempting navigation.")
                    await page_to_check.goto(self.settings.INITIAL_URL, wait_until="networkidle", timeout=self.settings.GENERAL_TIMEOUT_SECONDS * 1000)
                    if self.settings.DASHBOARD_URL_IDENTIFIER in page_to_check.url.lower():
                        try:
                            await page_to_check.wait_for_selector(self.selectors.DASHBOARD_LOGIN_SUCCESS_DETECTOR, timeout=3000, state="visible")
                            logger.info("Navigation to dashboard successful, session valid.")
                            if page_to_check.context: await page_to_check.context.storage_state(path=session_file_path)
                            return True
                        except PlaywrightTimeoutError:
                            logger.warning("Navigated to dashboard URL, but success detector not found.")
                    elif self.settings.LOGIN_PAGE_URL_IDENTIFIER in page_to_check.url.lower():
                        page_for_ops = page_to_check

            if not page_for_ops and os.path.exists(session_file_path):
                logger.info(f"Checking existing session file: {session_file_path}")
                browser = await self._launch_browser()
                context = await browser.new_context(storage_state=session_file_path, **self._get_common_context_options())
                page_for_ops = await context.new_page()
                await page_for_ops.goto(self.settings.INITIAL_URL, wait_until="networkidle", timeout=self.settings.GENERAL_TIMEOUT_SECONDS * 1000)
                await playwright_utils.handle_cookie_banner_if_present(page_for_ops, self.settings)
                try:
                    await page_for_ops.wait_for_selector(self.selectors.DASHBOARD_LOGIN_SUCCESS_DETECTOR, timeout=self.settings.SHORT_TIMEOUT_SECONDS * 1000, state="visible")
                    logger.info("Existing Unicourt session file is valid.")
                    await context.storage_state(path=session_file_path)
                    return True # page_for_ops, context, browser will be cleaned up in finally if not passed in
                except PlaywrightTimeoutError:
                    logger.warning(f"Existing session file check failed. Will attempt fresh login.")
                    if self.settings.LOGIN_PAGE_URL_IDENTIFIER not in page_for_ops.url.lower():
                        await page_for_ops.close()
                        page_for_ops = None
            
            logger.info("Attempting automated login to create/update Unicourt session...")
            if not page_for_ops or page_for_ops.is_closed():
                if context and not context.is_closed(): await context.close()
                if browser and browser.is_connected(): await browser.close()
                browser = await self._launch_browser()
                context = await browser.new_context(**self._get_common_context_options())
                page_for_ops = await context.new_page()
                # Initial goto handled by _perform_headless_automated_login

            if await self._perform_headless_automated_login(page_for_ops): # This function now handles initial navigation
                logger.info("Login successful. Saving new session state.")
                await page_for_ops.context.storage_state(path=session_file_path)
                return True
            else:
                logger.error("Automated login attempt failed.")
                return False
        except Exception as e:
            logger.critical(f"Critical error during ensure_authenticated_session: {e}", exc_info=True)
            if page_for_ops and not page_for_ops.is_closed():
                await playwright_utils.safe_screenshot(page_for_ops, self.settings, "ensure_session_critical_error")
            return False
        finally:
            if page_for_ops and (not page_to_check or page_for_ops != page_to_check) and not page_for_ops.is_closed():
                await page_for_ops.close()
            if context and (not page_to_check or page_to_check.context != context):
                await context.close()
            if browser and (not page_to_check or (page_to_check.context and page_to_check.context.browser != browser)):
                 await browser.close()
    
    async def create_worker_browser_context_and_dashboard_page(self) -> Tuple[Optional[Browser], Optional[BrowserContext], Optional[Page]]:
        if not os.path.exists(self.settings.UNICOURT_SESSION_PATH):
            logger.error(f"Unicourt session file not found at {self.settings.UNICOURT_SESSION_PATH}.")
            if not await self.ensure_authenticated_session(): # This will try to log in
                logger.error("Failed to establish initial Unicourt session for worker.")
                return None, None, None
        
        browser: Optional[Browser] = None
        context: Optional[BrowserContext] = None
        dashboard_page: Optional[Page] = None
        try:
            browser = await self._launch_browser()
            context = await browser.new_context(
                storage_state=self.settings.UNICOURT_SESSION_PATH,
                **self._get_common_context_options()
            )
            dashboard_page = await context.new_page()
            logger.info(f"[WorkerSetup] Navigating to Unicourt dashboard: {self.settings.INITIAL_URL}")
            await dashboard_page.goto(self.settings.INITIAL_URL, wait_until="networkidle", timeout=self.settings.GENERAL_TIMEOUT_SECONDS * 1000 * 2)
            await playwright_utils.handle_cookie_banner_if_present(dashboard_page, self.settings) # Handle cookies after navigation
            await dashboard_page.wait_for_selector(self.selectors.DASHBOARD_LOGIN_SUCCESS_DETECTOR, timeout=self.settings.GENERAL_TIMEOUT_SECONDS * 1000)
            logger.info(f"[WorkerSetup] Worker dashboard page loaded: {dashboard_page.url}")
            self.dashboard_page_for_worker = dashboard_page
            return browser, context, dashboard_page
        except Exception as e:
            logger.error(f"[WorkerSetup] Failed to create worker browser/context/dashboard page: {e}", exc_info=True)
            if dashboard_page and not dashboard_page.is_closed(): await dashboard_page.close()
            if context: await context.close()
            if browser and browser.is_connected(): await browser.close()
            return None, None, None

    async def close_worker_browser_resources(self, browser: Optional[Browser], context: Optional[BrowserContext]):
        if self.dashboard_page_for_worker and not self.dashboard_page_for_worker.is_closed():
            await self.dashboard_page_for_worker.close()
            self.dashboard_page_for_worker = None
        if context:
            try: await context.close()
            except Exception: pass
        if browser and browser.is_connected():
            try: await browser.close()
            except Exception: pass
        logger.info("Closed worker browser resources.")

    async def clear_search_input(self, page: Page):
        logger.debug("Attempting to clear search input using Reset button...")
        try:
            expand_button_locator = page.locator(self.selectors.SEARCH_CRITERIA_EXPAND_BUTTON)
            if await expand_button_locator.is_visible(timeout=1000):
                logger.info("Search criteria section is collapsed. Expanding.")
                await expand_button_locator.click()
                await common.random_delay(0.5, 1.0, "after expanding criteria")

            reset_button_locator = page.locator(self.selectors.SEARCH_RESET_BUTTON)
            clicked_a_reset = False
            all_resets = await reset_button_locator.all()
            for btn_loc in all_resets:
                if await btn_loc.is_visible(timeout=1000):
                    await btn_loc.click(timeout=self.settings.SHORT_TIMEOUT_SECONDS * 1000)
                    await common.random_delay(1.0, 2.0, "after clicking Reset")
                    clicked_a_reset = True
                    break
            if clicked_a_reset:
                logger.info("Search input cleared successfully using Reset button.")
            else:
                logger.debug("No visible Reset button found or clicked.")
        except Exception as e:
            logger.error(f"Error during search input clear (Reset button strategy): {e}", exc_info=True)
            await playwright_utils.safe_screenshot(page, self.settings, "search_clear_reset_error")
    
    async def _perform_search_on_dashboard(
        self, dashboard_page: Page, search_term_primary: str, search_term_secondary: Optional[str] = None
    ) -> Tuple[bool, str]:
        max_len = 99
        if len(search_term_primary) > max_len:
            original_primary = search_term_primary
            search_term_primary = search_term_primary[:max_len]
            logger.warning(
                f"Primary search term was too long (len: {len(original_primary)}), "
                f"truncated to {max_len} chars: '{search_term_primary}'"
            )

        if search_term_secondary and len(search_term_secondary) > max_len:
            original_secondary = search_term_secondary
            search_term_secondary = search_term_secondary[:max_len]
            logger.warning(
                f"Secondary search term was too long (len: {len(original_secondary)}), "
                f"truncated to {max_len} chars: '{search_term_secondary}'"
            )
            
        log_prefix = f"[{search_term_primary}{' + ' + search_term_secondary if search_term_secondary else ''}]"
        search_notes: List[str] = []        
        try:            
            
            if search_term_secondary is None: # This is a primary search operation
                logger.info(f"{log_prefix} Performing primary search. Ensuring fresh dashboard state.")
                await dashboard_page.goto(self.settings.INITIAL_URL, wait_until="networkidle", timeout=self.settings.GENERAL_TIMEOUT_SECONDS * 1000 * 1.5) # Increased timeout slightly
                await playwright_utils.handle_cookie_banner_if_present(dashboard_page, self.settings)
                await self.clear_search_input(dashboard_page) # Clear any previous state
                
                # Input primary search term
                more_options_button = dashboard_page.locator(self.selectors.SEARCH_MORE_OPTIONS_BUTTON)
                if await more_options_button.is_visible(timeout=3000):
                    await more_options_button.click()
                    await common.random_delay(0.3, 0.8)
                    case_name_option = dashboard_page.locator(self.selectors.SEARCH_CASE_NAME_OPTION)
                    await case_name_option.wait_for(state="visible", timeout=self.settings.SHORT_TIMEOUT_SECONDS * 1000)
                    await case_name_option.click()
                    await common.random_delay(0.2, 1.0)
                
                search_input_field = dashboard_page.locator(self.selectors.SEARCH_INPUT_FIELD)
                await search_input_field.wait_for(state="visible", timeout=self.settings.SHORT_TIMEOUT_SECONDS * 1000)
                await search_input_field.fill(search_term_primary)
                await common.random_delay(0.3, 0.7)
                await search_input_field.press("Enter")
                # Ensure the primary search chip is visible
                await expect(dashboard_page.locator(f'md-chip:has-text("{search_term_primary}")')).to_be_visible(timeout=self.settings.SHORT_TIMEOUT_SECONDS * 1000)
            
            if search_term_secondary: 
                logger.info(f"{log_prefix} Adding secondary search condition: {search_term_secondary}")
                # We should already be on a page with the primary search term active.
                # No need to re-fill primary search_input_field or press Enter for it.
                
                add_conditions_button = dashboard_page.locator(self.selectors.ADD_CONDITIONS_BUTTON)
                # Increased timeout for visibility of this button, as it might appear after page settles
                await expect(add_conditions_button).to_be_visible(timeout=self.settings.SHORT_TIMEOUT_SECONDS * 1000 * 1.5) 
                await add_conditions_button.click(timeout=self.settings.SHORT_TIMEOUT_SECONDS * 1000) # This was the timeout point
                await common.random_delay(0.3, 0.7)

                and_option = dashboard_page.locator(self.selectors.AND_CONDITION_OPTION)
                await and_option.click()
                await common.random_delay(0.5, 1.0)
                await dashboard_page.wait_for_selector(self.selectors.SECOND_SEARCH_CRITERIA, state="visible", timeout=self.settings.SHORT_TIMEOUT_SECONDS * 1000)
                
                search_for_button = dashboard_page.locator(self.selectors.SEARCH_FOR_DROPDOWN_BUTTON)
                if not await search_for_button.is_visible(timeout=1000): 
                    search_for_button = dashboard_page.locator(self.selectors.SEARCH_FOR_DROPDOWN_ALT_BUTTON)
                await search_for_button.click()
                await common.random_delay(0.3, 0.7)
                
                case_number_option = dashboard_page.locator(self.selectors.CASE_NUMBER_OPTION_IN_DROPDOWN)
                await case_number_option.click()
                await common.random_delay(0.5, 1.0)
                
                second_condition_input = dashboard_page.locator(self.selectors.SECOND_CONDITION_INPUT)
                await second_condition_input.fill(search_term_secondary)
                await common.random_delay(0.3, 0.7)
                await second_condition_input.press("Enter")
                second_condition_chip_selector = self.selectors.SECOND_CONDITION_CHIP.format(search_term_secondary)
                await expect(dashboard_page.locator(second_condition_chip_selector)).to_be_visible(timeout=self.settings.SHORT_TIMEOUT_SECONDS * 1000)
            
            # Click the appropriate search button
            # If search_term_secondary is present, use SEARCH_BUTTON_MULTI_CRITERIA
            # Otherwise (primary search only), use SEARCH_BUTTON
            final_search_button_locator_selector = self.selectors.SEARCH_BUTTON_MULTI_CRITERIA if search_term_secondary else self.selectors.SEARCH_BUTTON
            final_search_button_locator = dashboard_page.locator(final_search_button_locator_selector)
            
            logger.info(f"{log_prefix} Clicking final search button ({final_search_button_locator_selector}).")
            await expect(final_search_button_locator).to_be_enabled(timeout=self.settings.SHORT_TIMEOUT_SECONDS * 1000)
            await final_search_button_locator.click()
            
            await dashboard_page.wait_for_selector(self.selectors.SEARCH_RESULTS_AREA_DETECTOR, timeout=self.settings.GENERAL_TIMEOUT_SECONDS * 1000 * 2) # Increased timeout
            await common.random_delay(1.5, 3.5, "after final search click for results to populate") # Allow results to populate
            return True, "; ".join(search_notes)
        except Exception as e:
            note = f"SearchPerformError: {type(e).__name__} for '{search_term_primary}{(' + ' + search_term_secondary) if search_term_secondary else ''}': {str(e).splitlines()[0]}" # Cleaner error
            search_notes.append(note)
            logger.error(f"{log_prefix} {note}", exc_info=True)
            await playwright_utils.safe_screenshot(dashboard_page, self.settings, "search_perform_exception", common.sanitize_filename(search_term_primary))
            return False, "; ".join(search_notes)
        
    async def search_and_open_case_page(self, dashboard_page: Page, case_name_for_search: str, case_number_for_db_id: str) -> Tuple[Optional[Page], str, Optional[str], Optional[str]]:
        log_prefix = f"[{case_name_for_search} / {case_number_for_db_id}]"
        search_notes_list: List[str] = []
        
        search_success, notes = await self._perform_search_on_dashboard(dashboard_page, case_name_for_search)
        if notes: search_notes_list.append(notes)
        if not search_success:
            return None, "; ".join(search_notes_list), None, None

        all_results_locators = dashboard_page.locator(self.selectors.SEARCH_RESULT_ROW_DIV)
        num_results = await all_results_locators.count()
        logger.info(f"{log_prefix} Found {num_results} result(s) after case name search.")

        target_case_link_locator: Optional[Locator] = None
        
        if num_results == 0:
            # Double check after a small delay
            await common.random_delay(1.0, 2.0)
            num_results = await all_results_locators.count()
            if num_results == 0:
                search_notes_list.append(f"No results for case name '{case_name_for_search}'.")
                await playwright_utils.safe_screenshot(dashboard_page, self.settings, "case_search_name_no_results", common.sanitize_filename(case_name_for_search))
                return None, "; ".join(search_notes_list), None, None

        if num_results == 1:
            target_case_link_locator = all_results_locators.first.locator(self.selectors.SEARCH_RESULT_CASE_NAME_H3_A)
        elif num_results > 1:
            logger.info(f"{log_prefix} Multiple results ({num_results}). Refining with case number '{case_number_for_db_id}'.")
            search_notes_list.append(f"Multiple ({num_results}) for name; refining with number.")
            search_success, notes = await self._perform_search_on_dashboard(dashboard_page, case_name_for_search, case_number_for_db_id)
            if notes: search_notes_list.append(notes)
            if not search_success:
                return None, "; ".join(search_notes_list), None, None

            all_refined_results_locators = dashboard_page.locator(self.selectors.SEARCH_RESULT_ROW_DIV)
            num_refined_results = await all_refined_results_locators.count()
            logger.info(f"{log_prefix} Found {num_refined_results} result(s) after combined search.")

            if num_refined_results == 0:
                search_notes_list.append(f"No results after refining with name and number.")
                await playwright_utils.safe_screenshot(dashboard_page, self.settings, "case_search_refined_no_results", f"{common.sanitize_filename(case_name_for_search)}_{case_number_for_db_id}")
                return None, "; ".join(search_notes_list), None, None
            
            # If multiple matches, use the first one.
            target_case_link_locator = all_refined_results_locators.first.locator(self.selectors.SEARCH_RESULT_CASE_NAME_H3_A)
            if num_refined_results > 1:
                search_notes_list.append(f"Multiple ({num_refined_results}) results after refinement; selecting first listed.")

        if not target_case_link_locator:
            search_notes_list.append("Logic error: target case link not identified.")
            return None, "; ".join(search_notes_list), None, None


        try:
            logger.info(f"{log_prefix} Clicking case link: '{case_name_for_search}' (Case Number: {case_number_for_db_id})")
            current_context = dashboard_page.context
            async with current_context.expect_page(timeout=self.settings.GENERAL_TIMEOUT_SECONDS * 1000) as new_page_event:
                await target_case_link_locator.click(timeout=self.settings.SHORT_TIMEOUT_SECONDS * 1000)
            new_case_page = await new_page_event.value
            await new_case_page.wait_for_selector(self.selectors.CASE_DETAIL_PAGE_LOAD_DETECTOR, timeout=self.settings.GENERAL_TIMEOUT_SECONDS * 1000, state="visible")
            logger.info(f"{log_prefix} Case detail page verified: {new_case_page.url}")
            
            final_case_name_on_page = await self.extract_case_name_from_detail_page(new_case_page, case_number_for_db_id)
            final_case_number_on_page = await self.extract_case_number_from_detail_page(new_case_page, case_number_for_db_id)
            
            return new_case_page, "; ".join(search_notes_list), final_case_name_on_page, final_case_number_on_page

        except Exception as e:
            note = f"PageOpenError: {type(e).__name__} - {e}"
            search_notes_list.append(note)
            logger.error(f"{log_prefix} {note}", exc_info=True)
            await playwright_utils.safe_screenshot(dashboard_page, self.settings, "case_page_open_exception", common.sanitize_filename(case_name_for_search))
            return None, "; ".join(search_notes_list), None, None

    async def extract_case_name_from_detail_page(self, case_page: Page, log_id: str) -> Optional[str]:
        try:
            name_loc = case_page.locator(self.selectors.CASE_NAME_ON_DETAIL_PAGE_LOCATOR).first
            await name_loc.wait_for(state="visible", timeout=self.settings.SHORT_TIMEOUT_SECONDS*1000)
            return common.clean_html_text(await name_loc.inner_text())
        except Exception as e:
            logger.warning(f"[{log_id}] Error extracting case name from detail page: {e}")
            return None
            
    async def extract_case_number_from_detail_page(self, case_page: Page, log_id: str) -> Optional[str]:
        try:
            num_loc = case_page.locator(self.selectors.CASE_NUMBER_ON_DETAIL_PAGE_LOCATOR).first
            await num_loc.wait_for(state="visible", timeout=self.settings.SHORT_TIMEOUT_SECONDS*1000)
            return common.clean_html_text(await num_loc.inner_text())
        except Exception as e:
            logger.warning(f"[{log_id}] Error extracting case number from detail page: {e}")
            return None

    async def check_for_voluntary_dismissal(self, case_page: Page, case_identifier: str) -> bool:
        """Checks the case page (default: Docket Entries) for 'voluntary dismissal' case-insensitively."""
        logger.info(f"[{case_identifier}] Checking for 'voluntary dismissal' in docket entries.")
        try:
            # Ensure docket tab content is visible (Test Case 3 handles timeout here)
            # docket_area_locator should identify the main container for docket entries,
            # e.g., <case-dockets> or a similar element indicated by the user's XPath.
            await case_page.wait_for_selector(
                self.selectors.VOLUNTARY_DISMISSAL_DOCKET_TEXT_AREA, 
                state="visible", 
                timeout=self.settings.GENERAL_TIMEOUT_SECONDS * 1000
            )
            
            logger.debug(f"[{case_identifier}] Starting to scroll page to load all docket entries.")
            last_height = await case_page.evaluate('document.body.scrollHeight')
            scroll_attempts = 0
            max_scroll_attempts = 15 # Prevent infinite loops on stubborn pages

            while scroll_attempts < max_scroll_attempts:
                await case_page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                # Wait for potential dynamic content to load after scroll
                await case_page.wait_for_timeout(1500) # Increased from 1000ms
                
                new_height = await case_page.evaluate('document.body.scrollHeight')
                
                if new_height == last_height:
                    # Height hasn't changed, try one more time after a longer pause
                    logger.debug(f"[{case_identifier}] Scroll height unchanged ({new_height}). Pausing for final check.")
                    await case_page.wait_for_timeout(2500) # Longer pause for final check
                    new_height = await case_page.evaluate('document.body.scrollHeight')
                    if new_height == last_height:
                        logger.debug(f"[{case_identifier}] Scroll height confirmed unchanged. Assuming end of scrollable content.")
                        break # Exit loop if height is still the same
                
                last_height = new_height
                scroll_attempts += 1
                logger.debug(f"[{case_identifier}] Scrolling... Attempt {scroll_attempts}, Current height: {new_height}")
            
            if scroll_attempts >= max_scroll_attempts:
                logger.warning(f"[{case_identifier}] Reached max scroll attempts ({max_scroll_attempts}). Proceeding with text extraction.")

            logger.debug(f"[{case_identifier}] Finished scrolling. Extracting text from VOLUNTARY_DISMISSAL_DOCKET_TEXT_AREA: '{self.selectors.VOLUNTARY_DISMISSAL_DOCKET_TEXT_AREA}'")
            docket_area_locator = case_page.locator(self.selectors.VOLUNTARY_DISMISSAL_DOCKET_TEXT_AREA)
            docket_area_content = await docket_area_locator.inner_text(timeout=self.settings.GENERAL_TIMEOUT_SECONDS * 500) # Using a shorter timeout as content should be loaded.

            if 'Order Granting Motion to Vacate'.lower() in docket_area_content.lower() or 'Notice of Voluntary Dismissal'.lower() in docket_area_content.lower():
                logger.info(f"[{case_identifier}] 'Order Granting Motion to Vacate' or 'Notice of Voluntary Dismissal' found on page (case-insensitive).")
                return True

            logger.info(f"[{case_identifier}] 'Order Granting Motion to Vacate' and 'Notice of Voluntary Dismissal' NOT found on page.")
            return False

        except PlaywrightTimeoutError as e:
            logger.warning(f"[{case_identifier}] Timeout waiting for docket content or during text extraction for voluntary dismissal: {e}")
            await playwright_utils.safe_screenshot(case_page, self.settings, "voluntary_dismissal_timeout", case_identifier)
            return False

        except Exception as e:
            logger.error(f"[{case_identifier}] Error checking for voluntary dismissal: {e}", exc_info=True)
            await playwright_utils.safe_screenshot(case_page, self.settings, "voluntary_dismissal_error", case_identifier)
            return False
        
    async def extract_party_names_from_parties_tab(
        self, case_page: Page, target_creditor_type: str, input_creditor_name: str, case_identifier: str
    ) -> List[str]:
        """Navigates to Parties tab and extracts names of parties matching target_creditor_type, excluding input_creditor_name."""
        logger.info(f"[{case_identifier}] Extracting party names from 'Parties' tab for type '{target_creditor_type}'.")
        associated_party_names: List[str] = []
        try:
            parties_tab_button = case_page.locator(self.selectors.PARTIES_TAB_BUTTON)
            await parties_tab_button.click()
            await case_page.wait_for_selector(self.selectors.PARTIES_TAB_CONTENT_DETECTOR, 
                                              state="visible", 
                                              timeout=self.settings.GENERAL_TIMEOUT_SECONDS * 1000)
            logger.info(f"[{case_identifier}] 'Parties' tab content loaded.")
            
            await case_page.wait_for_selector(self.selectors.PARTY_ROW_SELECTOR, 
                                            state="visible", 
                                            timeout=self.settings.SHORT_TIMEOUT_SECONDS * 1000)

            party_rows = await case_page.locator(self.selectors.PARTY_ROW_SELECTOR).all()
            if not party_rows:
                
                logger.warning(f"[{case_identifier}] No party rows found using selector '{self.selectors.PARTY_ROW_SELECTOR}'.")
                return []

            for row in party_rows:
                try:
                    party_name_element = row.locator(self.selectors.PARTY_NAME_SELECTOR)
                    party_type_element = row.locator(self.selectors.PARTY_TYPE_SELECTOR)

                    party_name = common.clean_html_text(await party_name_element.inner_text(timeout=2000))
                    party_type_str = common.clean_html_text(await party_type_element.inner_text(timeout=2000))

                    # Normalize party_type_str for comparison (e.g. "Plaintiff", "Defendant")
                    if target_creditor_type.lower() in party_type_str.lower():
                        # Exclude the input creditor name itself
                        if input_creditor_name.lower().strip() not in party_name.lower().strip():
                            associated_party_names.append(party_name)
                            logger.debug(f"[{case_identifier}] Found matching associated party: '{party_name}' (Type: '{party_type_str}')")
                except Exception as e_row:
                    logger.warning(f"[{case_identifier}] Error processing a party row: {e_row}")
            
            logger.info(f"[{case_identifier}] Extracted {len(associated_party_names)} associated party names: {associated_party_names}")
            return list(set(associated_party_names)) # Return unique names
        except Exception as e:
            logger.error(f"[{case_identifier}] Error navigating to or processing 'Parties' tab: {e}", exc_info=True)
            await playwright_utils.safe_screenshot(case_page, self.settings, "parties_tab_error", case_identifier)
            return []

    def _categorize_doc_title(self, title: str) -> DocumentTypeEnum:
        title_upper = title.upper()
        is_fj = any(kw.upper() in title_upper for kw in self.settings.DOC_KEYWORDS_FJ)
        is_complaint = any(kw.upper() in title_upper for kw in self.settings.DOC_KEYWORDS_COMPLAINT)

        if is_fj: return DocumentTypeEnum.FINAL_JUDGMENT
        if is_complaint: return DocumentTypeEnum.COMPLAINT
        return DocumentTypeEnum.UNKNOWN

    async def _download_doc_from_crowdsourced_section_link(
        self,
        page_context: BrowserContext, # Use page's context for new tab
        link_locator: Locator, # The initial link on the case documents tab
        doc_title: str,
        unicourt_doc_key: Optional[str],
        case_identifier: str,
        temp_case_download_path: str
    ) -> Tuple[Optional[str], str]: # (saved_filepath, notes)
        """
        Helper to download a single document given its link locator from CrowdSourced.
        Handles both direct PDF downloads and fallback for unsupported file types.
        """
        new_doc_viewer_page: Optional[Page] = None
        notes = ""
        download_event: Optional[Download] = None

        try:
            logger.debug(f"[{case_identifier}] CrowdSourced: Setting up new page listener for '{doc_title}'.")
            async with page_context.expect_page(timeout=self.settings.GENERAL_TIMEOUT_SECONDS * 1000) as page_info:
                await link_locator.click(timeout=self.settings.SHORT_TIMEOUT_SECONDS * 1000)
            new_doc_viewer_page = await page_info.value
            logger.info(f"[{case_identifier}] CrowdSourced: New tab for '{doc_title}' (Key: {unicourt_doc_key}) URL: {new_doc_viewer_page.url}")

            # Wait for the page to generally load
            try:
                await new_doc_viewer_page.wait_for_load_state("domcontentloaded", timeout=self.settings.GENERAL_TIMEOUT_SECONDS * 1000)
            except PlaywrightTimeoutError:
                logger.warning(f"[{case_identifier}] CrowdSourced: Timeout on 'domcontentloaded' for document viewer page, proceeding.")

            # Check for the "Your browser does not support viewing this file." message
            unsupported_message_locator = new_doc_viewer_page.locator(f"text={self.selectors.PDF_VIEWER_UNSUPPORTED_FILE_MESSAGE_TEXT}")
            fallback_download_link_locator = new_doc_viewer_page.locator(self.selectors.PDF_VIEWER_DOWNLOAD_LINK_FALLBACK)

            if await unsupported_message_locator.is_visible(timeout=3000): # Short timeout to check for the message
                logger.info(f"[{case_identifier}] CrowdSourced: Unsupported file type message detected for '{doc_title}'. Attempting fallback download.")
                if await fallback_download_link_locator.is_visible(timeout=1000):
                    async with new_doc_viewer_page.expect_download(timeout=self.settings.GENERAL_TIMEOUT_SECONDS * 1000 * 1.5) as download_promise_fallback:
                        await fallback_download_link_locator.click(timeout=self.settings.SHORT_TIMEOUT_SECONDS * 1000)
                        logger.info(f"[{case_identifier}] CrowdSourced: Clicked fallback download link for '{doc_title}'.")
                        download_event = await download_promise_fallback.value
                else:
                    notes = f"CrowdSourcedUnsupportedFileError: Unsupported file message present, but fallback download link not found for '{doc_title}'."
                    logger.error(f"[{case_identifier}] {notes}")
                    await playwright_utils.safe_screenshot(new_doc_viewer_page, self.settings, "cs_dl_fallback_link_missing", f"{case_identifier}_{common.sanitize_filename(doc_title, max_length=30)}")
                    return None, notes
            else:
                logger.info(f"[{case_identifier}] CrowdSourced: No unsupported file message. Expecting direct/automatic download for '{doc_title}'.")
                
                try:
                    async with new_doc_viewer_page.expect_download(timeout=self.settings.SHORT_TIMEOUT_SECONDS * 1000 * 0.5 * 0.5) as download_promise_direct:
                        download_event = await download_promise_direct.value
                except PlaywrightTimeoutError:
                    logger.warning(f"[{case_identifier}] CrowdSourced: Timeout waiting for download event for '{doc_title}'. Trying to refreash the page.")
                    await new_doc_viewer_page.reload(wait_until="domcontentloaded", timeout=self.settings.GENERAL_TIMEOUT_SECONDS * 1000)
                    async with new_doc_viewer_page.expect_download(timeout=self.settings.SHORT_TIMEOUT_SECONDS * 1000 * 0.5 * 0.5) as download_promise_direct:
                        download_event = await download_promise_direct.value

            logger.info(f"[{case_identifier}] CrowdSourced: Download event captured for '{doc_title}'.")
                
            if not download_event:
                notes = f"CrowdSourcedDownloadEventError: Download event not captured for '{doc_title}'."
                logger.error(f"[{case_identifier}] {notes}")
                await playwright_utils.safe_screenshot(new_doc_viewer_page, self.settings, "cs_dl_no_event", f"{case_identifier}_{common.sanitize_filename(doc_title, max_length=30)}")
                return None, notes


            key_suffix = f"_k-{unicourt_doc_key}" if unicourt_doc_key else ""
            base_name = common.sanitize_filename(f"{doc_title}{key_suffix}", default_name=f"doc_{common.sanitize_filename(case_identifier)}{key_suffix}")
            
            _, orig_ext = os.path.splitext(download_event.suggested_filename)
            # Prefer .tif if it's in the original name, otherwise default to .pdf or original
            if 'tif' in (orig_ext or "").lower():
                final_ext = ".tif"
            elif 'pdf' in (orig_ext or "").lower():
                final_ext = ".pdf"
            else:
                final_ext = orig_ext or ".file"


            counter = 0
            prospective_filename = f"{base_name}{final_ext}"
            save_path = os.path.join(temp_case_download_path, prospective_filename)
            while os.path.exists(save_path): 
                counter += 1
                prospective_filename = f"{base_name}_{counter}{final_ext}"
                save_path = os.path.join(temp_case_download_path, prospective_filename)

            # Ensure the directory exists before saving the file
            os.makedirs(temp_case_download_path, exist_ok=True)
            await download_event.save_as(save_path)
            notes = f"Downloaded '{doc_title}' as '{os.path.basename(save_path)}'."
            logger.info(f"[{case_identifier}] CrowdSourced SUCCESS: {notes}")
            return save_path, notes
            
        except PlaywrightTimeoutError as pte:
            # This might catch timeouts from expect_page, expect_download, or wait_for_load_state
            notes = f"CrowdSourcedTimeout: Timeout during document download process for '{doc_title}': {str(pte).splitlines()[0]}"
            logger.error(f"[{case_identifier}] {notes}")
            page_to_screenshot = new_doc_viewer_page if new_doc_viewer_page and not new_doc_viewer_page.is_closed() else page_context.pages[-1] if page_context.pages else None
            if page_to_screenshot:
                await playwright_utils.safe_screenshot(page_to_screenshot, self.settings, "cs_dl_timeout", f"{case_identifier}_{common.sanitize_filename(doc_title, max_length=30)}")
            return None, notes
        except Exception as e:
            notes = f"CrowdSourcedError: General error during document download for '{doc_title}': {type(e).__name__} - {str(e)}"
            logger.error(f"[{case_identifier}] {notes}", exc_info=True)
            page_to_screenshot = new_doc_viewer_page if new_doc_viewer_page and not new_doc_viewer_page.is_closed() else page_context.pages[-1] if page_context.pages else None
            if page_to_screenshot:
                 await playwright_utils.safe_screenshot(page_to_screenshot, self.settings, "cs_dl_error", f"{case_identifier}_{common.sanitize_filename(doc_title, max_length=30)}")
            return None, notes
        finally:
            if new_doc_viewer_page and not new_doc_viewer_page.is_closed():
                await new_doc_viewer_page.close()

    async def identify_and_process_documents_on_case_page(
        self,
        case_page: Page,
        case_identifier: str, # case_number_for_db_id
        temp_case_download_path: str # Specific temporary path for this case's downloads
    ) -> Tuple[List[TransientDocumentInfo], List[Dict[str, Any]]]:
        """
        Handles document identification, ordering (from Paid), and downloading (from CrowdSourced).
        Returns a list of TransientDocumentInfo for successfully downloaded docs, and 
        a list of summary dicts for processed_documents_summary.
        """
        logger.info(f"[{case_identifier}] Starting document identification and processing.")
        
        # This list will store info about all docs identified, including their final processing status for this phase
        processed_doc_summaries: List[Dict[str, Any]] = []
        # This list will store info for successfully downloaded docs to be passed to LLM
        llm_processing_bundle: List[TransientDocumentInfo] = []

        os.makedirs(temp_case_download_path, exist_ok=True)

        try:
            # Use a more specific selector for the Documents tab
            documents_tab_locator = case_page.locator(self.selectors.DOCUMENTS_TAB_BUTTON)
            
            logger.debug(f"[{case_identifier}] Clicking Documents tab...")
            # Ensure the tab is visible and enabled before clicking, Playwright handles some of this.
            await documents_tab_locator.wait_for(state="visible", timeout=self.settings.SHORT_TIMEOUT_SECONDS * 1000)
            await documents_tab_locator.click()
            
            # Wait for either table to appear, or just a delay
            # The existing random_delay is kept, but the subsequent try/except for table selectors is more robust.
            await common.random_delay(3.0, 5.0, "after clicking Documents tab") 
            
            # Add a more robust wait for content loading, e.g. one of the table selectors
            try:
                await case_page.wait_for_selector(
                    f"{self.selectors.PAID_DOCS_TABLE_SELECTOR}, {self.selectors.CROWDSOURCED_DOCS_TABLE_SELECTOR}",
                    state="attached", # Check if element is in DOM, not necessarily visible
                    timeout=self.settings.GENERAL_TIMEOUT_SECONDS * 1000
                )
                logger.info(f"[{case_identifier}] Documents tab content area detected.")
            except PlaywrightTimeoutError:
                logger.warning(f"[{case_identifier}] Neither paid nor crowdsourced table selectors found after Documents tab click. Proceeding cautiously.")
                await playwright_utils.safe_screenshot(case_page, self.settings, "docs_tab_not_found", case_identifier)


        except PlaywrightTimeoutError as e:
            note = f"Timeout navigating/loading Documents tab: {str(e).splitlines()[0]}"
            logger.error(f"[{case_identifier}] {note}")
            await playwright_utils.safe_screenshot(case_page, self.settings, "docs_tab_nav_fail", case_identifier)
            # This is a critical failure for document processing for this case
            # No documents can be processed. Return empty lists.
            return [], [{"document_name": "Document Tab Navigation", "unicourt_doc_key": None, "status": DocumentProcessingStatusEnum.GENERIC_PROCESSING_ERROR.value, "notes": note}]


        # --- Phase A: "Documents available for Download" (Paid Section) ---
        docs_to_order_from_paid: List[TransientDocumentInfo] = [] # Store TransientDocumentInfo for those to be ordered
        
        if await case_page.locator(self.selectors.PAID_DOCS_TABLE_SELECTOR).is_visible(timeout=5000):
            logger.info(f"[{case_identifier}] Processing 'Documents available for Download' (Paid) section.")
            await playwright_utils.scroll_to_bottom_of_scrollable(case_page, self.selectors.PAID_DOCS_SCROLLABLE_CONTAINER, self.selectors.PAID_DOC_ROW_SELECTOR, "Paid Docs", case_identifier)
            
            all_paid_doc_rows = await case_page.locator(self.selectors.PAID_DOC_ROW_SELECTOR).all()
            logger.info(f"[{case_identifier}] Found {len(all_paid_doc_rows)} rows in Paid section.")

            for i, row_locator in enumerate(all_paid_doc_rows):
                doc_original_title = "Unknown_Paid_Doc_Title"
                doc_status_for_summary = DocumentProcessingStatusEnum.IDENTIFIED_FOR_PROCESSING
                doc_key_for_summary = None # Key usually not available pre-order/pre-link
                try:
                    title_span = row_locator.locator(self.selectors.PAID_DOC_TITLE_SPAN_SELECTOR).first
                    doc_original_title = common.clean_html_text(await title_span.get_attribute('title') or await title_span.inner_text())
                    
                    doc_type = self._categorize_doc_title(doc_original_title)
                    if doc_type == DocumentTypeEnum.UNKNOWN:
                        continue # Skip non-relevant documents

                    logger.debug(f"[{case_identifier}] Paid: Found '{doc_original_title}' (Type: {doc_type.value}). Checking cost...")
                    cost_td = row_locator.locator(self.selectors.PAID_DOC_COST_TD_SELECTOR).first
                    cost_str = common.clean_html_text(await cost_td.inner_text(timeout=3000))
                    is_free = cost_str == "$0.00" or cost_str.lower() == "free" or cost_str == "" or cost_str.lower() == "n/a"

                    trans_doc_info = TransientDocumentInfo(
                        original_title=doc_original_title,
                        document_type=doc_type,
                        paid_section_row_locator=row_locator, # Store locator for re-assessment
                        cost_str=cost_str
                    )

                    if not is_free:
                        logger.warning(f"[{case_identifier}] Paid: '{doc_original_title}' requires payment (Cost: {cost_str}). Skipping order.")
                        doc_status_for_summary = DocumentProcessingStatusEnum.SKIPPED_REQUIRES_PAYMENT
                        processed_doc_summaries.append({
                            "document_name": doc_original_title, 
                            "unicourt_doc_key": doc_key_for_summary, 
                            "status": doc_status_for_summary.value,
                            "notes": f"Document requires payment. Cost: {cost_str}"
                        })
                        continue
                    
                    # If free, add to list for ordering
                    docs_to_order_from_paid.append(trans_doc_info)
                    logger.info(f"[{case_identifier}] Paid: Identified free doc '{doc_original_title}' for ordering.")

                except Exception as e_paid_row:
                    logger.error(f"[{case_identifier}] Paid: Error processing row {i+1} ('{doc_original_title}'): {e_paid_row}")
                    processed_doc_summaries.append({
                        "document_name": doc_original_title, 
                        "unicourt_doc_key": doc_key_for_summary, 
                        "status": DocumentProcessingStatusEnum.GENERIC_PROCESSING_ERROR.value
                    })
            
            # Order documents in chunks
            if docs_to_order_from_paid:
                num_ordered_successfully_estimate = 0
                for i in range(0, len(docs_to_order_from_paid), self.settings.PAID_DOC_ORDER_CHUNK_SIZE):
                    chunk_to_order = docs_to_order_from_paid[i:i + self.settings.PAID_DOC_ORDER_CHUNK_SIZE]
                    logger.info(f"[{case_identifier}] Paid: Attempting to order chunk {i//self.settings.PAID_DOC_ORDER_CHUNK_SIZE + 1} ({len(chunk_to_order)} docs).")
                    
                    # Select checkboxes for this chunk
                    for doc_info_to_order in chunk_to_order:
                        if doc_info_to_order.paid_section_row_locator:
                            checkbox = doc_info_to_order.paid_section_row_locator.locator(self.selectors.PAID_DOC_CHECKBOX_SELECTOR)
                            try:
                                if await checkbox.is_enabled(timeout=1000) and not await checkbox.is_checked(timeout=1000):
                                    await checkbox.check(timeout=1000)
                            except Exception as e_check:
                                logger.warning(f"[{case_identifier}] Paid: Error checking box for '{doc_info_to_order.original_title}': {e_check}")
                                # Mark this doc as failed to order if checkbox fails
                                doc_info_to_order.processing_status = DocumentProcessingStatusEnum.ORDERING_FAILED 
                                doc_info_to_order.processing_notes = "Checkbox interaction failed."
                    
                    order_button = case_page.locator(self.selectors.ORDER_DOCUMENTS_BUTTON_SELECTOR)
                    if await order_button.is_visible(timeout=3000) and await order_button.is_enabled(timeout=1000):
                        await order_button.click()
                        await common.random_delay(1,2, "after clicking order docs button")
                        confirm_dialog = case_page.locator(self.selectors.CONFIRM_ORDER_DIALOG_SELECTOR)
                        await confirm_dialog.wait_for(state="visible", timeout=self.settings.SHORT_TIMEOUT_SECONDS * 1000)
                        proceed_button = confirm_dialog.locator(self.selectors.CONFIRM_ORDER_PROCEED_BUTTON_SELECTOR)
                        await proceed_button.click()
                        logger.info(f"[{case_identifier}] Paid: 'Proceed' clicked for chunk. Waiting for order processing...")
                        # Wait for loading indicators to appear and disappear for each doc in chunk
                        all_loading_indicators = case_page.locator(self.selectors.PAID_DOC_ORDER_LOADING_INDICATOR_SELECTOR)
                        logger.debug(f"[{case_identifier}] Paid: PAID_DOC_ORDER_LOADING_INDICATOR_SELECTOR count: {await all_loading_indicators.count()}")
                        expected_count = len(chunk_to_order)
                          # First wait for all indicators to appear
                        try:
                            timeout_ms = self.settings.SHORT_TIMEOUT_SECONDS * 1000
                            while (await all_loading_indicators.count()) < expected_count and timeout_ms > 0:
                                await case_page.wait_for_timeout(100)  # Check every 100ms
                                timeout_ms -= 100
                            if timeout_ms <= 0:
                                logger.error(f"[{case_identifier}] Timeout waiting for all {expected_count} loading indicators to appear")
                                # Mark docs as failed if loading indicators don't appear
                                for doc_info_to_order in chunk_to_order:
                                    if doc_info_to_order.processing_status == DocumentProcessingStatusEnum.IDENTIFIED_FOR_PROCESSING:
                                        doc_info_to_order.processing_status = DocumentProcessingStatusEnum.ORDERING_FAILED
                                        doc_info_to_order.processing_notes = "Loading indicators failed to appear."
                        except Exception as e:
                            logger.error(f"[{case_identifier}] Error waiting for loading indicators to appear: {e}")
                            # Mark docs as failed if there's an exception
                            for doc_info_to_order in chunk_to_order:
                                if doc_info_to_order.processing_status == DocumentProcessingStatusEnum.IDENTIFIED_FOR_PROCESSING:
                                    doc_info_to_order.processing_status = DocumentProcessingStatusEnum.ORDERING_FAILED
                                    doc_info_to_order.processing_notes = f"Exception waiting for loading indicators: {str(e)}"

                        logger.debug(f"[{case_identifier}] Paid: Waiting for {expected_count}/{await all_loading_indicators.count()} loading indicators to disappear after order click.")

                        # Then wait for all indicators to disappear
                        try:
                            await case_page.wait_for_selector(
                                self.selectors.PAID_DOC_ORDER_LOADING_INDICATOR_SELECTOR, 
                                state="hidden", 
                                timeout=self.settings.GENERAL_TIMEOUT_SECONDS * 1000 * 2
                            )
                            logger.info(f"[{case_identifier}] Paid: All loading indicators disappeared after order click. Marking docs as ORDERING_COMPLETED.")
                            # Mark successfully ordered documents as ORDERING_COMPLETED
                            for doc_info_to_order in chunk_to_order:
                                if doc_info_to_order.processing_status == DocumentProcessingStatusEnum.IDENTIFIED_FOR_PROCESSING:
                                    doc_info_to_order.processing_status = DocumentProcessingStatusEnum.ORDERING_COMPLETED
                                    doc_info_to_order.processing_notes = "Document successfully ordered and will be processed for download."
                        except Exception as e:
                            logger.error(f"[{case_identifier}] Error waiting for loading indicators to disappear: {e}")
                            playwright_utils.safe_screenshot(case_page, self.settings, "paid_docs_order_loading_timeout", case_identifier)
                            # Mark docs as failed if indicators don't disappear
                            for doc_info_to_order in chunk_to_order:
                                if doc_info_to_order.processing_status == DocumentProcessingStatusEnum.IDENTIFIED_FOR_PROCESSING:
                                    doc_info_to_order.processing_status = DocumentProcessingStatusEnum.ORDERING_FAILED
                                    doc_info_to_order.processing_notes = f"Loading indicators timeout: {str(e)}"
                        num_ordered_successfully_estimate += len(chunk_to_order) # Rough estimate
                    else:
                        logger.error(f"[{case_identifier}] Paid: Order Documents button not available for chunk. Marking docs in chunk as failed.")
                        for doc_info_to_order in chunk_to_order:
                             doc_info_to_order.processing_status = DocumentProcessingStatusEnum.ORDERING_FAILED
                             doc_info_to_order.processing_notes = "Order button not available."
                
                # After attempting all orders, check for global failure message
                if await case_page.locator(self.selectors.PAID_DOC_ORDER_FAILED_LIST_UPDATE_SELECTOR).is_visible(timeout=2000):
                    logger.error(f"[{case_identifier}] Paid: Global 'Document List Needs Update' message detected. Many orders may have failed.")
                    # This might imply all docs in docs_to_order_from_paid should be marked as failed.
                    for doc_info in docs_to_order_from_paid:
                        if doc_info.processing_status == DocumentProcessingStatusEnum.IDENTIFIED_FOR_PROCESSING: # Only if not already failed
                            doc_info.processing_status = DocumentProcessingStatusEnum.ORDERING_FAILED
                            doc_info.processing_notes = "Global order failure message observed."                  
                # Add summary for docs attempted to be ordered from paid section
                # Their actual download will happen if they appear in CrowdSourced.
                # Here, we record the outcome of the *ordering attempt*.
                for doc_info in docs_to_order_from_paid:
                    # Ensure no document is left in IDENTIFIED_FOR_PROCESSING status
                    final_status = doc_info.processing_status
                    if final_status == DocumentProcessingStatusEnum.IDENTIFIED_FOR_PROCESSING:
                        logger.warning(f"[{case_identifier}] Paid doc '{doc_info.original_title}' still in IDENTIFIED_FOR_PROCESSING status. Marking as ORDERING_FAILED.")
                        final_status = DocumentProcessingStatusEnum.ORDERING_FAILED
                        doc_info.processing_notes = "Document was not properly processed during ordering phase."
                    
                    processed_doc_summaries.append({
                        "document_name": doc_info.original_title,
                        "unicourt_doc_key": None, # Key not known yet
                        "status": final_status.value, # Reflects order attempt outcome
                        "notes": doc_info.processing_notes
                    })
        else:
            logger.info(f"[{case_identifier}] 'Documents available for Download' (Paid) section not found or not visible.")
            await playwright_utils.safe_screenshot(case_page, self.settings, "docs_tab_paid_section_not_found", case_identifier)

        # --- Phase B: "Documents in CrowdSourced Library™" Section (Sole Download Point) ---
        if await case_page.locator(self.selectors.CROWDSOURCED_DOCS_TABLE_SELECTOR).is_visible(timeout=5000):
            logger.info(f"[{case_identifier}] Processing 'Documents in CrowdSourced Library™' section for downloads.")
            await playwright_utils.scroll_to_bottom_of_scrollable(case_page, self.selectors.CROWDSOURCED_DOCS_SCROLLABLE_CONTAINER, self.selectors.CROWDSOURCED_DOC_ROW_SELECTOR, "CrowdSourced Docs", case_identifier)

            all_crowdsourced_doc_rows = await case_page.locator(self.selectors.CROWDSOURCED_DOC_ROW_SELECTOR).all()
            logger.info(f"[{case_identifier}] Found {len(all_crowdsourced_doc_rows)} rows in CrowdSourced section.")

            for i, row_locator in enumerate(all_crowdsourced_doc_rows):
                doc_original_title = "Unknown_CrowdSourced_Doc_Title"
                unicourt_key: Optional[str] = None
                doc_processing_status = DocumentProcessingStatusEnum.IDENTIFIED_FOR_PROCESSING # Default for this iteration
                
                try:
                    title_span = row_locator.locator(self.selectors.CROWDSOURCED_DOC_TITLE_SPAN_SELECTOR).first
                    doc_original_title = common.clean_html_text(await title_span.get_attribute('title') or await title_span.inner_text())
                    
                    doc_type = self._categorize_doc_title(doc_original_title)
                    if doc_type == DocumentTypeEnum.UNKNOWN:
                        continue # Skip non-relevant documents

                    link_locator = row_locator.locator(self.selectors.CROWDSOURCED_DOC_LINK_A_SELECTOR).first
                    doc_url_href = await link_locator.get_attribute("href")
                    if doc_url_href:
                        unicourt_key = common.extract_unicourt_document_key(doc_url_href)
                    
                    logger.info(f"[{case_identifier}] CrowdSourced: Found '{doc_original_title}' (Type: {doc_type.value}, Key: {unicourt_key}). Attempting download.")
                    
                    temp_dl_path, dl_notes = await self._download_doc_from_crowdsourced_section_link(
                        case_page.context, link_locator, doc_original_title, unicourt_key, case_identifier, temp_case_download_path
                    )

                    if temp_dl_path and os.path.exists(temp_dl_path):
                        doc_processing_status = DocumentProcessingStatusEnum.DOWNLOAD_SUCCESS
                        llm_processing_bundle.append(TransientDocumentInfo(
                            original_title=doc_original_title,
                            unicourt_doc_key=unicourt_key,
                            document_type=doc_type,
                            temp_local_path=temp_dl_path,
                            processing_status=doc_processing_status # Will be updated after LLM
                        ))
                    else:
                        doc_processing_status = DocumentProcessingStatusEnum.DOWNLOAD_FAILED
                    
                    # Add or update summary:
                    # Check if this doc (by key if available, or title) was from paid section and already has an 'ORDERING_FAILED' status.
                    # If so, we don't overwrite that, but log that it appeared in CS.
                    # For simplicity now, just add. More robust merging might be needed if a doc fails order then magically appears in CS.
                    existing_summary_entry = next((s for s in processed_doc_summaries if s["unicourt_doc_key"] == unicourt_key and unicourt_key is not None), None)
                    if not existing_summary_entry and unicourt_key is None: # try by name if keyless
                         existing_summary_entry = next((s for s in processed_doc_summaries if s["document_name"] == doc_original_title and s["unicourt_doc_key"] is None), None)


                    if existing_summary_entry:
                        # If it was previously marked SKIPPED_REQUIRES_PAYMENT or ORDERING_FAILED, and now we downloaded it,
                        # this is an update. Or if it was already DOWNLOAD_SUCCESS (e.g. page reloaded, processed again)
                        logger.info(f"[{case_identifier}] CrowdSourced: Doc '{doc_original_title}' (Key: {unicourt_key}) already in summary with status '{existing_summary_entry['status']}'. Updating to '{doc_processing_status.value}'.")
                        existing_summary_entry["status"] = doc_processing_status.value
                        if unicourt_key and existing_summary_entry["unicourt_doc_key"] is None:
                            existing_summary_entry["unicourt_doc_key"] = unicourt_key
                    else:
                        processed_doc_summaries.append({
                            "document_name": doc_original_title,
                            "unicourt_doc_key": unicourt_key,
                            "status": doc_processing_status.value,
                            "notes": dl_notes
                        })
                    await common.random_delay(0.5, 1.5, f"after processing crowdsourced doc '{doc_original_title}'")                
                except Exception as e_cs_row:
                    logger.error(f"[{case_identifier}] CrowdSourced: Error processing row ('{doc_original_title}'): {e_cs_row}")
                    processed_doc_summaries.append({
                        "document_name": doc_original_title, 
                        "unicourt_doc_key": unicourt_key, 
                        "status": DocumentProcessingStatusEnum.GENERIC_PROCESSING_ERROR.value,
                        "notes": str(e_cs_row)
                    })
        else:
            logger.info(f"[{case_identifier}] 'CrowdSourced Library' section not found or not visible.")
            await playwright_utils.safe_screenshot(case_page, self.settings, "docs_tab_crowdsourced_section_not_found", case_identifier)
        
        if not llm_processing_bundle and not any(s["status"] == DocumentProcessingStatusEnum.SKIPPED_REQUIRES_PAYMENT.value for s in processed_doc_summaries):
            logger.warning(f"[{case_identifier}] No relevant documents (FJ/Complaint) were successfully downloaded or marked as requiring payment.")
          # Final safeguard: Ensure no documents are left in IDENTIFIED_FOR_PROCESSING or ORDERING_COMPLETED status
        identified_count = 0
        ordering_completed_count = 0
        for summary_item in processed_doc_summaries:
            if summary_item["status"] == DocumentProcessingStatusEnum.IDENTIFIED_FOR_PROCESSING.value:
                identified_count += 1
                logger.warning(f"[{case_identifier}] Document '{summary_item['document_name']}' (Key: {summary_item.get('unicourt_doc_key', 'None')}) was left in IDENTIFIED_FOR_PROCESSING status. Marking as ORDERING_FAILED.")
                summary_item["status"] = DocumentProcessingStatusEnum.ORDERING_FAILED.value
                summary_item["notes"] = "Document was not properly processed through the ordering phase."
            elif summary_item["status"] == DocumentProcessingStatusEnum.ORDERING_COMPLETED.value:
                ordering_completed_count += 1
                logger.warning(f"[{case_identifier}] Document '{summary_item['document_name']}' (Key: {summary_item.get('unicourt_doc_key', 'None')}) was left in ORDERING_COMPLETED status. Marking as ORDERING_FAILED.")
                summary_item["status"] = DocumentProcessingStatusEnum.ORDERING_FAILED.value
                summary_item["notes"] = "Document was ordered successfully but failed to appear in CrowdSourced section for download."
        
        if identified_count > 0:
            logger.warning(f"[{case_identifier}] Fixed {identified_count} documents that were left in IDENTIFIED_FOR_PROCESSING status.")
        if ordering_completed_count > 0:
            logger.warning(f"[{case_identifier}] Fixed {ordering_completed_count} documents that were left in ORDERING_COMPLETED status.")
        
        return llm_processing_bundle, processed_doc_summaries