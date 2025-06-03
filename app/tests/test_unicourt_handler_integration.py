# test_unicourt_handler_integration.py
import pytest
import asyncio
import os
from playwright.async_api import async_playwright, Page, Browser, BrowserContext
from app.services.unicourt_handler import UnicourtHandler
from app.core.config import AppSettings, UnicourtSelectors # For UnicourtSelectors if needed by handler
from app.db.models import CreditorTypeEnum
import shutil # For cleaning up temp download directory
from app.db.models import DocumentTypeEnum, DocumentProcessingStatusEnum # If not already there

@pytest.mark.asyncio
async def test_identify_and_process_documents_real_page_and_keep_browser_open():
    """
    Integration test for identify_and_process_documents_on_case_page.
    Uses a real browser, session file, and keeps the browser open at the end.
    Attempts to order free documents and download from CrowdSourced.
    """
    settings = AppSettings(
        UNICOURT_EMAIL="dev2@goodwillrecovery.com", # Replace with your actual test credentials
        UNICOURT_PASSWORD="Devstaff0525!",      # Replace with your actual test credentials
        API_ACCESS_KEY="dummy-key",
        DB_URL="sqlite:///:memory:",
    )
    
    session_dir = os.path.dirname(settings.UNICOURT_SESSION_PATH)
    if session_dir and not os.path.exists(session_dir):
        os.makedirs(session_dir)

    # Create a temporary directory for this test's downloads
    # This should match the structure the main app uses if settings.CURRENT_DOWNLOAD_LOCATION is involved
    # For this test, let's use a dedicated temp subfolder.
    # The `identify_and_process_documents_on_case_page` expects `temp_case_download_path`
    
    # Using a subfolder within where the app might normally download
    base_test_download_dir = os.path.join(os.path.abspath(settings.CURRENT_DOWNLOAD_LOCATION), "pytest_temp_docs")
    case_identifier_for_test = "TEST-DOC-PROCESSING-001"  # Unique identifier for this test case
    temp_case_download_path_for_this_test = os.path.join(base_test_download_dir, case_identifier_for_test)
    
    if os.path.exists(temp_case_download_path_for_this_test):
        shutil.rmtree(temp_case_download_path_for_this_test) # Clean up from previous runs
    os.makedirs(temp_case_download_path_for_this_test, exist_ok=True)
    print(f"Temporary download path for this test: {temp_case_download_path_for_this_test}")


    async with async_playwright() as playwright:
        initial_handler = UnicourtHandler(playwright_instance=playwright, settings=settings)
        print("Ensuring authenticated session for document processing test...")
        session_is_valid = await initial_handler.ensure_authenticated_session()
        
        if not session_is_valid:
            pytest.fail("Failed to ensure an authenticated session. Cannot proceed with document processing test.")
        
        if not os.path.exists(settings.UNICOURT_SESSION_PATH):
            pytest.fail(f"Session file was not created at {settings.UNICOURT_SESSION_PATH} for document processing test.")
        
        print(f"Session file ready for document processing test: {settings.UNICOURT_SESSION_PATH}")

        test_browser: Browser = None
        test_context: BrowserContext = None
        test_page: Page = None
        
        try:
            print("Launching browser for document processing test using the session file...")
            test_browser = await playwright.chromium.launch(
                headless=True, # Keep False for debugging document interactions
            )
            test_context = await test_browser.new_context(
                storage_state=settings.UNICOURT_SESSION_PATH,
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1366, "height": 768},
                java_script_enabled=True,
                accept_downloads=True # Crucial for document downloads
            )
            test_page = await test_context.new_page()
            
            handler_for_test = UnicourtHandler(playwright_instance=playwright, settings=settings)

            # --- IMPORTANT: Use a URL known to have various document types for testing ---
            # This case (GFGCAJBLIRDT4F34H44XDDLMMRNRK0954) has documents.
            # You need to verify if it has:
            # 1. "Paid" section docs: some free, some with cost.
            # 2. "CrowdSourced" section docs: some matching your FJ/Complaint keywords.
            test_url_docs = "https://app.unicourt.com/researcher/case/detail/GBFR6IZ2GM3UCF4JHM4GVEDDMNIRG0935#dockets"
            print(f"Navigating to test case URL for documents: {test_url_docs}")
            # Give ample time for document-heavy pages to load and JS to execute
            await test_page.goto(test_url_docs, wait_until="networkidle", timeout=settings.GENERAL_TIMEOUT_SECONDS * 3000) 
            
            if settings.LOGIN_PAGE_URL_IDENTIFIER in test_page.url:
                 pytest.fail("Landed on login page for document test. Session might be invalid.")

            print("Waiting a bit for document page to fully render...")
            await asyncio.sleep(5) # Increased wait for document tab potentially loading a lot
            
            test_page.on("console", lambda msg: print(f"Browser log (doc test): {msg.type} - {msg.text}"))
            
            print("Testing document identification and processing...")
            
            llm_bundle, processed_summaries = await handler_for_test.identify_and_process_documents_on_case_page(
                case_page=test_page,
                case_identifier=case_identifier_for_test, # Used for logging and potential filenames
                temp_case_download_path=temp_case_download_path_for_this_test
            )
            
            print(f"LLM Processing Bundle ({len(llm_bundle)} items): {llm_bundle}")
            print(f"Processed Document Summaries ({len(processed_summaries)} items): {processed_summaries}")

            # --- Example Assertions (ADJUST THESE BASED ON YOUR TEST URL's ACTUAL DATA) ---
            assert isinstance(llm_bundle, list), "llm_bundle should be a list."
            assert isinstance(processed_summaries, list), "processed_summaries should be a list."

            # Check for downloaded files in llm_bundle
            downloaded_fj_found = False
            downloaded_complaint_found = False
            for doc_info in llm_bundle:
                assert doc_info.temp_local_path is not None, f"Downloaded doc {doc_info.original_title} has no temp_local_path."
                assert os.path.exists(doc_info.temp_local_path), f"Downloaded file {doc_info.temp_local_path} does not exist."
                assert os.path.getsize(doc_info.temp_local_path) > 0, f"Downloaded file {doc_info.temp_local_path} is empty."
                assert doc_info.processing_status == DocumentProcessingStatusEnum.DOWNLOAD_SUCCESS
                if doc_info.document_type == DocumentTypeEnum.FINAL_JUDGMENT:
                    downloaded_fj_found = True
                if doc_info.document_type == DocumentTypeEnum.COMPLAINT:
                    downloaded_complaint_found = True
            
            # You might assert that at least one relevant doc was downloaded if your test case guarantees it
            # For GFGCAJBLIRDT4F34H44XDDLMMRNRK0954:
            # "ORDER DENYING WRIT(S) AND FINAL JUDGMENT" - This might be a FJ.
            # "COMPLAINT" - This is a complaint.
            # These are in the dockets, need to verify if they are orderable/downloadable in the Documents tab sections.
            
            # Example: Check if at least one document of any relevant type was downloaded
            # This is a loose assertion, make it more specific if your test case allows.
            # if not settings.DOC_KEYWORDS_FJ and not settings.DOC_KEYWORDS_COMPLAINT:
            #     print("WARN: No FJ or Complaint keywords configured, cannot assert specific downloads.")
            # else:
            #     assert len(llm_bundle) > 0, "Expected at least one relevant document to be downloaded."
            
            # Check processed_summaries for specific statuses
            skipped_payment_found = any(
                item["status"] == DocumentProcessingStatusEnum.SKIPPED_REQUIRES_PAYMENT.value for item in processed_summaries
            )
            download_success_in_summary = any(
                item["status"] == DocumentProcessingStatusEnum.DOWNLOAD_SUCCESS.value for item in processed_summaries
            )
            ordering_failed_found = any( # This might occur if a free doc order fails
                item["status"] == DocumentProcessingStatusEnum.ORDERING_FAILED.value for item in processed_summaries
            )

            # TODO: Based on your specific test_url_docs, assert these flags.
            # For example, if you know there's a paid document:
            # assert skipped_payment_found, "Expected to find a document skipped due to payment."
            # If you know there's a downloadable CrowdSourced document:
            # assert download_success_in_summary, "Expected at least one download success in summaries."
            print(f"Skipped payment found in summary: {skipped_payment_found}")
            print(f"Download success found in summary: {download_success_in_summary}")
            print(f"Ordering failed found in summary: {ordering_failed_found}")

            if not llm_bundle and not skipped_payment_found:
                 print("WARNING: No documents were downloaded, and no documents were skipped for payment. "
                       "Check if the test case URL has relevant/free documents or if selectors are correct.")
            
            print("Document processing test completed. Browser will remain open for inspection.")
            print("Downloaded files (if any) are in:", temp_case_download_path_for_this_test)
            print("Press Ctrl+C in the terminal (or stop the debugger) to close the browser when done.")
            
            while True: 
                await asyncio.sleep(1)
            
        except Exception as e:
            print(f"Error during document processing test execution: {str(e)}")
            if test_page and not test_page.is_closed():
                screenshot_dir = settings.SCREENSHOT_PATH 
                os.makedirs(screenshot_dir, exist_ok=True)
                await test_page.screenshot(path=os.path.join(screenshot_dir, "test_doc_processing_error.png"))
            raise
        finally:
            # Clean up the temporary download directory for this specific test run
            if os.path.exists(temp_case_download_path_for_this_test):
                print(f"Cleaning up temporary download directory: {temp_case_download_path_for_this_test}")
                try:
                    shutil.rmtree(temp_case_download_path_for_this_test)
                except Exception as e_clean:
                    print(f"Error cleaning up temp directory {temp_case_download_path_for_this_test}: {e_clean}")

@pytest.mark.asyncio
async def test_extract_party_names_real_page_and_keep_browser_open():
    """
    Integration test for extract_party_names_from_parties_tab.
    Uses a real browser, session file, and keeps the browser open at the end.
    """
    settings = AppSettings(
        UNICOURT_EMAIL="dev2@goodwillrecovery.com", # Replace with your actual test credentials
        UNICOURT_PASSWORD="Devstaff0525!",      # Replace with your actual test credentials
        API_ACCESS_KEY="dummy-key",
        DB_URL="sqlite:///:memory:",
    )
    
    session_dir = os.path.dirname(settings.UNICOURT_SESSION_PATH)
    if session_dir and not os.path.exists(session_dir):
        os.makedirs(session_dir)

    async with async_playwright() as playwright:
        initial_handler = UnicourtHandler(playwright_instance=playwright, settings=settings)
        print("Ensuring authenticated session and session file for party extraction test...")
        session_is_valid = await initial_handler.ensure_authenticated_session()
        
        if not session_is_valid:
            pytest.fail("Failed to ensure an authenticated session. Cannot proceed with the party extraction test.")
        
        if not os.path.exists(settings.UNICOURT_SESSION_PATH):
            pytest.fail(f"Session file was not created at {settings.UNICOURT_SESSION_PATH} for party extraction test.")
        
        print(f"Session file ready for party extraction test: {settings.UNICOURT_SESSION_PATH}")

        test_browser: Browser = None
        test_context: BrowserContext = None
        test_page: Page = None
        
        try:
            print("Launching browser for the party extraction test using the session file...")
            test_browser = await playwright.chromium.launch(
                headless=False,
                devtools=True 
            )
            test_context = await test_browser.new_context(
                storage_state=settings.UNICOURT_SESSION_PATH,
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1366, "height": 768},
                java_script_enabled=True,
                accept_downloads=True
            )
            test_page = await test_context.new_page()
            
            handler_for_test = UnicourtHandler(playwright_instance=playwright, settings=settings)

            test_url_parties = "https://app.unicourt.com/researcher/case/detail/GFGCAJBLIRDT4F34H44XDDLMMRNRK0954#dockets"
            print(f"Navigating to test case URL for parties: {test_url_parties}")
            await test_page.goto(test_url_parties, wait_until="networkidle", timeout=settings.GENERAL_TIMEOUT_SECONDS * 2000)
            
            if settings.LOGIN_PAGE_URL_IDENTIFIER in test_page.url:
                 pytest.fail("Landed on login page even after loading session state for party test. Session might be invalid.")

            print("Waiting a bit for page to fully render (party test)...")
            await asyncio.sleep(3)
            
            test_page.on("console", lambda msg: print(f"Browser log (party test): {msg.type} - {msg.text}"))
            
            # --- Define test parameters ---
            # This is the party whose perspective we are taking (e.g., our client is this plaintiff)
            # We want to find other parties of a specific type, *excluding* this input_creditor_name.
            input_creditor_name = "EUGENIO F. BIRD, M.D. P.A." # Assuming this is a Plaintiff
            target_party_type = CreditorTypeEnum.DEFENDANT  # We are looking for Defendants

            print(f"Testing party extraction for type '{target_party_type.value}', excluding '{input_creditor_name}'...")
            
            # Ensure the Parties tab is clicked and content loaded (the method handles this)
            # Make sure your selectors in UnicourtSelectors are correct:
            # PARTIES_TAB_BUTTON, PARTIES_TAB_CONTENT_DETECTOR, 
            # PARTY_ROW_SELECTOR, PARTY_NAME_SELECTOR, PARTY_TYPE_SELECTOR
            
            extracted_party_names = await handler_for_test.extract_party_names_from_parties_tab(
                case_page=test_page,
                target_creditor_type=target_party_type,
                input_creditor_name=input_creditor_name,
                case_identifier="TEST-PARTIES-001"
            )
            
            print(f"Extracted party names: {extracted_party_names}")

            # --- Example Assertions (ADJUST THESE BASED ON YOUR TEST URL's ACTUAL DATA) ---
            assert extracted_party_names is not None, "Expected a list of party names, got None."
            
            # For the GFGCAJBLIRDT4F34H44XDDLMMRNRK0954 case:
            # Example expected defendants (if Bird Eye Institute P.A. is the plaintiff)
            expected_defendants = [
                "POINCIANA LOAN CENTER, INC.", # Check exact name from Unicourt
                "BIRD, EUGENIO F",              # Check exact name
                "YGLESIAS, ANABEL",            # Check exact name
                "OGEERALLY, MILLISSA",         # Check exact name
                "OGEERALLY, TERRIN"            # Check exact name
            ]
            
            # Convert to lowercase and strip for robust comparison
            extracted_party_names_lower = {name.lower().strip() for name in extracted_party_names}
            
            for expected_defendant in expected_defendants:
                assert expected_defendant.lower().strip() in extracted_party_names_lower, \
                    f"Expected defendant '{expected_defendant}' not found in extracted names."

            assert input_creditor_name.lower().strip() not in extracted_party_names_lower, \
                f"Input creditor name '{input_creditor_name}' should not be in the extracted list."
            
            if not extracted_party_names:
                 print("WARNING: No parties extracted. This might be okay if none match criteria, or it might indicate a selector issue.")
            else:
                print(f"Successfully extracted {len(extracted_party_names)} party names of type '{target_party_type.value}'.")


            print("Party extraction test completed. Browser will remain open for inspection.")
            print("Press Ctrl+C in the terminal (or stop the debugger) to close the browser when done.")
            # Keep the browser open by not closing it in the finally block for this test
            while True: # Loop indefinitely to keep browser open
                await asyncio.sleep(1) 
                # This loop can be broken by stopping the script (Ctrl+C)
            
        except Exception as e:
            print(f"Error during party extraction test execution: {str(e)}")
            if test_page and not test_page.is_closed():
                # Ensure screenshot path exists, AppSettings has SCREENSHOT_PATH property
                screenshot_dir = settings.SCREENSHOT_PATH 
                os.makedirs(screenshot_dir, exist_ok=True)
                await test_page.screenshot(path=os.path.join(screenshot_dir, "test_party_extraction_error.png"))
            raise
  

@pytest.mark.asyncio
async def test_check_for_voluntary_dismissal_real_page():
    """
    Integration test that uses a real browser to verify selectors.
    It first ensures a session file is available, then uses it for the test.
    """
    settings = AppSettings(
        UNICOURT_EMAIL="dev2@goodwillrecovery.com", # Replace with your actual test credentials
        UNICOURT_PASSWORD="Devstaff0525!",      # Replace with your actual test credentials
        API_ACCESS_KEY="dummy-key",
        DB_URL="sqlite:///:memory:",
        # UNICOURT_SESSION_PATH is defined in AppSettings by default
    )
    
    # Ensure the directory for the session file exists
    session_dir = os.path.dirname(settings.UNICOURT_SESSION_PATH)
    if session_dir and not os.path.exists(session_dir):
        os.makedirs(session_dir)

    async with async_playwright() as playwright:
        initial_handler = UnicourtHandler(playwright_instance=playwright, settings=settings)
        print("Ensuring authenticated session and session file...")
        session_is_valid = await initial_handler.ensure_authenticated_session()
        
        if not session_is_valid:
            pytest.fail("Failed to ensure an authenticated session. Cannot proceed with the test.")
        
        if not os.path.exists(settings.UNICOURT_SESSION_PATH):
            pytest.fail(f"Session file was not created at {settings.UNICOURT_SESSION_PATH} even after successful session ensure.")
        
        print(f"Session file should now be ready at: {settings.UNICOURT_SESSION_PATH}")

        # Step 2: Launch a new browser instance for the test, using the session file.
        test_browser: Browser = None
        test_context: BrowserContext = None
        test_page: Page = None
        
        try:
            print("Launching browser for the test using the session file...")
            test_browser = await playwright.chromium.launch(
                headless=False
            )
            test_context = await test_browser.new_context(
                storage_state=settings.UNICOURT_SESSION_PATH, # Load session from file
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1366, "height": 768},
                java_script_enabled=True,
                accept_downloads=True
            )
            test_page = await test_context.new_page()
            
            # The handler instance can be the same, as it's stateless regarding browser/page objects for this method
            # It just needs the playwright_instance and settings.
            handler_for_test = UnicourtHandler(playwright_instance=playwright, settings=settings)

            # Navigate to your test case page
            # This page is known to have "Voluntary Dismissal"
            test_url = "https://app.unicourt.com/researcher/case/detail/GFGCAJBLIRDT4F34H44XDDLMMRNRK0954#dockets"
            print(f"Navigating to test case URL: {test_url}")
            await test_page.goto(test_url, wait_until="networkidle", timeout=settings.GENERAL_TIMEOUT_SECONDS * 2000)
            
            # Verify we are likely logged in (e.g., by checking for a dashboard element or not being on login page)
            # This is an extra check; loading with storage_state should handle it.
            if settings.LOGIN_PAGE_URL_IDENTIFIER in test_page.url:
                 pytest.fail("Landed on login page even after loading session state. Session might be invalid or expired.")

            print("Waiting a bit for page to fully render...")
            await asyncio.sleep(3) # Give some time for manual inspection if headless=False
        
            # Test the voluntary dismissal check
            print("Testing voluntary dismissal check...")

            result = await handler_for_test.check_for_voluntary_dismissal(test_page, "TEST-CASE-VD-001")
            print(f"Result of voluntary dismissal check: {result}")
            
            assert result is True or "Expected to find 'voluntary dismissal' on the page."

            print("Test completed. Waiting a bit before closing to allow inspection...")
            await asyncio.sleep(5) # For manual observation if headless=False
            
        except Exception as e:
            print(f"Error during test execution: {str(e)}")
            if test_page:
                await test_page.screenshot(path=os.path.join(settings.SCREENSHOT_PATH, "test_voluntary_dismissal_error.png"))
            raise
        finally:
            print("Cleaning up test browser resources...")
            if test_page and not test_page.is_closed():
                await test_page.close()
            if test_context:
                await test_context.close()
            if test_browser and test_browser.is_connected():
                await test_browser.close()
            print("Test browser resources closed.")

if __name__ == "__main__":

    
    #asyncio.run(test_check_for_voluntary_dismissal_real_page())
    #asyncio.run(test_extract_party_names_real_page_and_keep_browser_open())
    asyncio.run(test_identify_and_process_documents_real_page_and_keep_browser_open())