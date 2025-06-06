# app/core/config.py
import os
import json
from pydantic import BaseModel, Field, EmailStr
from typing import Dict, Optional, List
import logging

logger = logging.getLogger(__name__)

CONFIG_FILE_PATH = "config.json"
DOTENV_PATH = ".env"

class UnicourtSelectors(BaseModel):
    # Login & Dashboard
    EMAIL_INPUT: str = "input#login-input-emailid"
    PASSWORD_INPUT: str = "input#login-input-password"
    LOGIN_BUTTON: str = "button#login-btn-login"
    COOKIE_AGREE_BUTTON: str = "button#cookiesfooter-btn-agree"
    LOGIN_FORM_DETECTOR: str = "form.ng-untouched.ng-pristine.ng-invalid"
    DASHBOARD_LOGIN_SUCCESS_DETECTOR: str = "div[title='Everything']"

    # Search Page (Dashboard)
    SEARCH_CHIP_CONTAINER: str = "md-chips[name=\"searcher_terms\"]"
    SEARCH_CHIP_REMOVE_BUTTON: str = "md-chip button.md-chip-remove"
    SEARCH_EVERYTHING_BUTTON: str = "div[title=\"Everything\"] button"
    SEARCH_MORE_OPTIONS_BUTTON: str = "button:has-text(\"More Options\"):has(md-icon:text(\"more_vert\"))"
    SEARCH_CASE_NAME_OPTION: str = "md-menu-content button:has-text(\"Case Name\")"
    SEARCH_CASE_NUMBER_OPTION: str = "md-menu-content button:has-text(\"Case Number\")"
    SEARCH_INPUT_FIELD: str = "md-chips[name=\"searcher_terms\"] input.md-input"
    SEARCH_BUTTON: str = "div.search-btn button:has-text(\"Search\")"
    SEARCH_RESULTS_AREA_DETECTOR: str = "md-content:has-text(\"Showing Results for:\")"
    SEARCH_NO_RESULTS_TEXT_PATTERN: str = "Sorry, no results containing any of your search terms were found."
    SEARCH_RESULT_ROW_DIV: str = "div.s_result"
    SEARCH_RESULT_CASE_NAME_H3_A: str = "h3 a.researcher-case"
    SEARCH_RESULT_METADATA_H4: str = "h4.case-metadata"
    SEARCH_RESET_BUTTON: str = "button.rest-search:has-text('Reset')"
    SEARCH_CRITERIA_EXPAND_BUTTON: str = "button.search-criteria-collase-btn md-icon[aria-label='keyboard_arrow_down']"
    
    ADD_CONDITIONS_BUTTON: str = "button.md-button.md-accent.condition-button"
    AND_CONDITION_OPTION: str = "button.menu-option-button:has-text(\"AND\")"
    SECOND_SEARCH_CRITERIA: str = "div[ng-repeat*=\"search_criteria_key\"][ng-hide*=\"criteria_collapse\"]:nth-child(2)"    
    SEARCH_FOR_DROPDOWN_BUTTON: str = "div[ng-repeat*=\"search_criteria_key\"]:nth-child(2) button:has-text(\"Search for\")"
    SEARCH_FOR_DROPDOWN_ALT_BUTTON: str = "div[ng-repeat*=\"search_criteria_key\"]:nth-child(2) button.md-button.search-menu-button:has-text(\"Search for\")"
    CASE_NUMBER_OPTION_IN_DROPDOWN: str =  "div.md-open-menu-container.md-active md-menu-content button:has-text('Case Number')" # More specific
    SECOND_CONDITION_INPUT: str = "div[ng-repeat*=\"search_criteria_key\"]:nth-child(2) input.md-input"
    SECOND_CONDITION_CHIP: str = "div[ng-repeat*=\"search_criteria_key\"]:nth-child(2) md-chip:has-text(\"{}\")"
    SEARCH_BUTTON_MULTI_CRITERIA: str = "button.all-criterias-srch:has-text('Search')"

    # Case Detail Page
    CASE_DETAIL_PAGE_LOAD_DETECTOR: str = "h2.case-name"
    CASE_NAME_ON_DETAIL_PAGE_LOCATOR: str = "h2.case-name"
    CASE_NUMBER_ON_DETAIL_PAGE_LOCATOR: str = "span[flex][class*='ng-binding'][class*='flex']"
    
    # DOCKET_TAB_CONTENT_DETECTOR is for general presence of the docket tab's main component or header
    DOCKET_TAB_CONTENT_DETECTOR: str = "case-dockets h2:has-text(\"Docket Entries\")"
    # VOLUNTARY_DISMISSAL_DOCKET_TEXT_AREA is for the specific area to get inner_text from for dismissal check
    VOLUNTARY_DISMISSAL_DOCKET_TEXT_AREA: str = "case-dockets" # The <case-dockets> element itself

    # Parties Tab
    PARTIES_TAB_BUTTON: str = "md-tab-item:has(md-icon[aria-label=\"supervisor_account\"]):has-text(\"Parties\")"
    PARTIES_TAB_CONTENT_DETECTOR: str = "md-tab-content.md-active parties table.md-table"
    PARTY_ROW_SELECTOR: str = (
    "md-tabs-content-wrapper > md-tab-content.md-active:has(parties) " # Ensures active tab is the one with parties
    "parties table.md-table tbody "
    "tr[ng-repeat*='in parties.column_details']" # Targets the collection name
    )
    PARTY_NAME_SELECTOR: str = "td:nth-child(1) span[ng-bind-html*='party_fullname']"
    PARTY_TYPE_SELECTOR: str = "td:nth-child(2)"

    # Documents Tab on Case Detail Page
    DOCUMENTS_TAB_BUTTON: str = "md-tab-item:has-text('Documents')"
    LOADING_INDICATOR: str = ".pt30.pb30.ng-scope.layout-sm-column.layout-align-space-around-stretch.layout-row"
    
    CROWDSOURCED_DOCS_TABLE_SELECTOR: str = "div.download-docs table.document-table"
    CROWDSOURCED_DOC_ROW_SELECTOR: str = "div.download-docs table.document-table > tbody[ng-repeat*='available_doc']"
    CROWDSOURCED_DOC_TITLE_SPAN_SELECTOR: str = "td span.author[title]"
    CROWDSOURCED_DOC_LINK_A_SELECTOR: str = "a[ng-href*='/file/researchCourtCaseFile/']"
    CROWDSOURCED_DOCS_SCROLLABLE_CONTAINER: str = "div.download-docs"

    PAID_DOCS_TABLE_SELECTOR: str = "div.order-document table.document-table"
    PAID_DOCS_SCROLLABLE_CONTAINER: str = "div.order-document"
    PAID_DOC_ROW_SELECTOR: str = "div.order-document table.document-table tbody[ng-repeat*='paid_doc'] tr[ng-class*='paid_doc']"
    PAID_DOC_CHECKBOX_SELECTOR: str = "td md-checkbox[ng-click*='toggle_docs_selection']"
    PAID_DOC_TITLE_SPAN_SELECTOR: str = "td span.docket-document-name[title]"
    PAID_DOC_COST_TD_SELECTOR: str = "td.ng-binding[ng-if*='order.cost'], td.ng-binding[ng-if*='paid_doc.postgresdb_document.cost']"
    PAID_DOC_DOWNLOAD_LINK_SELECTOR: str = "td span.author a[ng-href*='/file/researchCourtCaseFile/']" 
    PAID_DOC_ORDER_FAILED_LIST_UPDATE_SELECTOR: str = "div.top-message b:has-text('Document Order Failed - Document List Needs Update')"
    PAID_DOC_ORDER_ROW_FAILED_INDICATOR: str = "td.order-status-failed-indicator" 
    PAID_DOC_ORDER_LOADING_INDICATOR_SELECTOR: str = "div.md-container.md-mode-indeterminate" # The bar that appears when documents are being ordered
    

    ORDER_DOCUMENTS_BUTTON_SELECTOR: str = "button[ng-click*='order_docs'][hide-xs]:not([disabled])"
    CONFIRM_ORDER_DIALOG_SELECTOR: str = "md-dialog[aria-label*='Confirm Order'], md-dialog[class*='flex-gt-md-40']"
    CONFIRM_ORDER_PROCEED_BUTTON_SELECTOR: str = "md-dialog-actions button[ng-click*='confirm_ordering_docs']:has-text('Proceed')"

    # Document Viewer / Download Fallback
    PDF_VIEWER_UNSUPPORTED_FILE_MESSAGE_TEXT: str = "Your browser does not support viewing this file." # Text to check for
    PDF_VIEWER_DOWNLOAD_LINK_FALLBACK: str = "p.uc-padding:has-text('Your browser does not support viewing this file.') > a[download]" # The 'download' link itself

class AppSettings(BaseModel):
    UNICOURT_EMAIL: EmailStr = "default_unicourt_email_please_configure@example.com"
    UNICOURT_PASSWORD: str = "default_unicourt_password_please_configure"
    OPENROUTER_API_KEY: str = "default_openrouter_api_key_please_configure"
    OPENROUTER_LLM_MODEL: str = "meta-llama/llama-4-maverick" 

    PORT: int = Field(int(os.getenv("PORT", "8000")), gt=1023, lt=65536)
    HOST: str = os.getenv("HOST", "0.0.0.0")
    API_ACCESS_KEY: str = os.getenv("API_ACCESS_KEY", "CONFIG_ERROR_API_KEY_NOT_IN_ENV")
    DATABASE_FILENAME: str = os.getenv("DATABASE_FILENAME", "app_data.db")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()
    
    MAX_CONCURRENT_TASKS: int = Field(int(os.getenv("MAX_CONCURRENT_TASKS", "2")), gt=0)
    CURRENT_DOWNLOAD_LOCATION: str = os.getenv("CURRENT_DOWNLOAD_LOCATION", "unicourt_downloads") 

    INITIAL_URL: str = "https://app.unicourt.com/dashboard"
    LOGIN_PAGE_URL_IDENTIFIER: str = "/login"
    DASHBOARD_URL_IDENTIFIER: str = "/dashboard"
    SESSION_FILENAME: str = "unicourt_session.json"
    
    UNICOURT_SELECTORS: UnicourtSelectors = Field(default_factory=UnicourtSelectors)
    
    LLM_TIMEOUT_SECONDS: int = Field(int(os.getenv("LLM_TIMEOUT_SECONDS", "180")), gt=0)
    GENERAL_TIMEOUT_SECONDS: int = Field(int(os.getenv("GENERAL_TIMEOUT_SECONDS", "60")), gt=0)
    SHORT_TIMEOUT_SECONDS: int = Field(int(os.getenv("SHORT_TIMEOUT_SECONDS", "20")), gt=0)
    VERY_LONG_TIMEOUT_SECONDS: int = Field(int(os.getenv("VERY_LONG_TIMEOUT_SECONDS", "300")), gt=0)

    EXTRACT_ASSOCIATED_PARTY_ADDRESSES: bool = Field(bool(os.getenv("EXTRACT_ASSOCIATED_PARTY_ADDRESSES", True)))

    DOC_KEYWORDS_FJ: List[str] = ["FINAL", "JUDGMENT"] 
    DOC_KEYWORDS_COMPLAINT: List[str] = ["COMPLAINT"] 
    PAID_DOC_ORDER_CHUNK_SIZE: int = 10

    MAX_IMAGES_PER_LLM_CALL: int = Field(int(os.getenv("MAX_IMAGES_PER_LLM_CALL", "5")), gt=0)
    MAX_LLM_ATTEMPTS_PER_BATCH: int = Field(int(os.getenv("MAX_LLM_ATTEMPTS_PER_BATCH", "2")), gt=0)



    @property
    def DATABASE_URL(self) -> str:
        abs_download_path = os.path.abspath(self.CURRENT_DOWNLOAD_LOCATION)
        return f"sqlite:///{os.path.join(abs_download_path, self.DATABASE_FILENAME)}"

    @property
    def UNICOURT_SESSION_PATH(self) -> str:
        abs_download_path = os.path.abspath(self.CURRENT_DOWNLOAD_LOCATION)
        return os.path.join(abs_download_path, self.SESSION_FILENAME)
    
    @property # Adding screenshot path property
    def SCREENSHOT_PATH(self) -> str:
        # Store screenshots in a 'screenshots' subdirectory of CURRENT_DOWNLOAD_LOCATION
        abs_download_path = os.path.abspath(self.CURRENT_DOWNLOAD_LOCATION)
        path = os.path.join(abs_download_path, "playwright_screenshots")
        os.makedirs(path, exist_ok=True)
        return path

    class Config:
        extra = 'ignore' 

_cached_settings: Optional[AppSettings] = None
CLIENT_CONFIG_KEYS = {"UNICOURT_EMAIL", "UNICOURT_PASSWORD", "OPENROUTER_API_KEY", "OPENROUTER_LLM_MODEL", "EXTRACT_ASSOCIATED_PARTY_ADDRESSES"}

def load_settings() -> AppSettings:
    global _cached_settings
    if _cached_settings is None:
        try:
            current_values = AppSettings() 
            
            if os.path.exists(CONFIG_FILE_PATH):
                try:
                    with open(CONFIG_FILE_PATH, 'r') as f:
                        json_config = json.load(f)
                    for key in CLIENT_CONFIG_KEYS:
                        if key in json_config and json_config[key] is not None: 
                            setattr(current_values, key, json_config[key])
                    if "UNICOURT_SELECTORS" in json_config and isinstance(json_config["UNICOURT_SELECTORS"], dict):
                        try:
                            current_values.UNICOURT_SELECTORS = UnicourtSelectors(**json_config["UNICOURT_SELECTORS"])
                            logger.info(f"Loaded UNICOURT_SELECTORS from {CONFIG_FILE_PATH}.")
                        except Exception as e_sel:
                            logger.warning(f"Error parsing UNICOURT_SELECTORS from {CONFIG_FILE_PATH}: {e_sel}. Using defaults.")
                            
                except Exception as e:
                    logger.error(f"Error reading or applying {CONFIG_FILE_PATH}: {e}. Using .env/defaults for client keys and selectors.")
            else:
                logger.warning(f"{CONFIG_FILE_PATH} not found. Client must configure it. Using .env/defaults for client keys and selectors.")

            _cached_settings = current_values
            
            if _cached_settings.API_ACCESS_KEY == "CONFIG_ERROR_API_KEY_NOT_IN_ENV":
                logger.critical("API_ACCESS_KEY IS NOT SET IN .env! API will be inaccessible.")

            download_loc = os.path.abspath(_cached_settings.CURRENT_DOWNLOAD_LOCATION)
            if not os.path.exists(download_loc):
                try:
                    os.makedirs(download_loc, exist_ok=True)
                    logger.info(f"Created main download directory during settings load: {download_loc}")
                except Exception as e:
                    logger.critical(f"CRITICAL: Could not create download directory {download_loc} during settings load: {e}")
            
            logger.info("Application settings processed.")
            logger.debug(f"Effective settings (secrets/selectors redacted for brevity): "
                         f"Email='{_cached_settings.UNICOURT_EMAIL[:5]}...', "
                         f"LLM Model='{_cached_settings.OPENROUTER_LLM_MODEL}', "
                         f"DownloadLoc='{_cached_settings.CURRENT_DOWNLOAD_LOCATION}', "
                         f"MaxTasks='{_cached_settings.MAX_CONCURRENT_TASKS}', "
                         f"ExtractAssocPartyAddr='{_cached_settings.EXTRACT_ASSOCIATED_PARTY_ADDRESSES}'")

        except Exception as e: 
            logger.critical(f"CRITICAL ERROR initializing AppSettings: {e}.", exc_info=True)
            class FallbackSettings: 
                API_ACCESS_KEY="CRITICAL_SETTINGS_FAILURE"
            _cached_settings = FallbackSettings()
            raise 

    return _cached_settings

def get_app_settings() -> AppSettings:
    if _cached_settings is None:
        load_settings()
    if not isinstance(_cached_settings, AppSettings): 
        logger.critical("Attempted to get settings, but initial loading failed critically.")
        raise RuntimeError("Application settings are not properly initialized due to a critical failure during startup.")
    return _cached_settings

def clear_cached_settings():
    global _cached_settings
    _cached_settings = None
    logger.info("Cached settings cleared.")

settings = load_settings()