# tests/test_search_and_open_case_page.py
import pytest
import os
import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from playwright.async_api import Page, Locator, BrowserContext, TimeoutError as PlaywrightTimeoutError

from app.services.unicourt_handler import UnicourtHandler
from app.core.config import AppSettings


@pytest.fixture
def mock_settings():
    """Create a mock settings object with required attributes."""
    settings = Mock(spec=AppSettings)
    settings.GENERAL_TIMEOUT_SECONDS = 30
    settings.SHORT_TIMEOUT_SECONDS = 10
    settings.CURRENT_DOWNLOAD_LOCATION = "/tmp/test_downloads"  # Add missing attribute
    
    # Create mock selectors
    selectors = Mock()
    selectors.SEARCH_RESULT_ROW_DIV = ".search-result-row"
    selectors.SEARCH_RESULT_CASE_NAME_H3_A = "h3 a"
    selectors.CASE_DETAIL_PAGE_LOAD_DETECTOR = ".case-detail-page"
    selectors.CASE_NAME_ON_DETAIL_PAGE_LOCATOR = ".case-name"
    selectors.CASE_NUMBER_ON_DETAIL_PAGE_LOCATOR = ".case-number"
    settings.UNICOURT_SELECTORS = selectors
    
    return settings


@pytest.fixture
def mock_handler(mock_settings):
    """Create a UnicourtHandler instance with mocked dependencies."""
    with patch('app.services.unicourt_handler.logger'), \
         patch('app.utils.playwright_utils.safe_screenshot', new_callable=AsyncMock), \
         patch('app.utils.common.sanitize_filename', return_value="test_case"), \
         patch('app.utils.common.random_delay', new_callable=AsyncMock):
        handler = UnicourtHandler(None, mock_settings)
        handler.extract_case_name_from_detail_page = AsyncMock(return_value="Test Case Name")
        handler.extract_case_number_from_detail_page = AsyncMock(return_value="12345")
        handler.clear_search_input = AsyncMock()
        handler._perform_search_on_dashboard = AsyncMock()
        return handler


@pytest.fixture
def mock_dashboard_page():
    """Create a mock dashboard page."""
    page = AsyncMock(spec=Page)
    page.context = AsyncMock(spec=BrowserContext)
    return page


@pytest.fixture
def mock_locator():
    """Create a mock locator."""
    locator = AsyncMock(spec=Locator)
    locator.count = AsyncMock()
    locator.first = Mock()
    
    # Create a nested locator for the chain .first.locator()
    nested_locator = AsyncMock(spec=Locator)
    nested_locator.click = AsyncMock()
    locator.first.locator = Mock(return_value=nested_locator)
    
    return locator


class MockAsyncContextManager:
    """Helper class to mock async context managers like expect_page()"""
    def __init__(self, return_value):
        self.return_value = return_value
    
    async def __aenter__(self):
        # This should return an object with a .value property that awaits to the page
        mock_event = Mock()
        
        # Create an async function that returns the page
        async def get_page():
            return self.return_value
        
        mock_event.value = get_page()  # This is now awaitable
        return mock_event
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


class TestSearchAndOpenCasePage:

    @pytest.mark.asyncio
    async def test_initial_search_fails(self, mock_handler, mock_dashboard_page):
        """Test when initial search by case name fails."""
        mock_handler._perform_search_on_dashboard.return_value = (False, "Search failed")
        
        result = await mock_handler.search_and_open_case_page(
            mock_dashboard_page, "Test Case", "12345"
        )
        
        assert result == (None, "Search failed", None, None)
        mock_handler._perform_search_on_dashboard.assert_called_once_with(
            mock_dashboard_page, "Test Case"
        )

    @pytest.mark.asyncio
    async def test_single_result_from_initial_search_success(self, mock_handler, mock_dashboard_page, mock_locator):
        """Test successful search with single result from initial case name search."""
        # Setup mocks
        mock_handler._perform_search_on_dashboard.return_value = (True, "")
        mock_dashboard_page.locator.return_value = mock_locator
        mock_locator.count.return_value = 1
        
        # Mock the page opening process
        new_page = AsyncMock(spec=Page)
        new_page.url = "https://example.com/case/12345"
        new_page.wait_for_selector = AsyncMock()
        
        # Create proper context manager mock
        mock_context = mock_dashboard_page.context
        mock_context.expect_page.return_value = MockAsyncContextManager(new_page)
        
        result = await mock_handler.search_and_open_case_page(
            mock_dashboard_page, "Test Case", "12345"
        )
        
        # Verify result
        assert result[0] == new_page
        assert result[2] == "Test Case Name"  # final_case_name_on_page
        assert result[3] == "12345"  # final_case_number_on_page
        
        # Verify calls
        mock_handler._perform_search_on_dashboard.assert_called_once_with(
            mock_dashboard_page, "Test Case"
        )
        mock_locator.first.locator.return_value.click.assert_called_once()

    @pytest.mark.asyncio
    async def test_multiple_results_refined_search_success(self, mock_handler, mock_dashboard_page, mock_locator):
        """Test multiple results from initial search, then successful refinement."""
        # Setup mocks for initial search (multiple results)
        mock_handler._perform_search_on_dashboard.side_effect = [
            (True, ""),  # Initial search success
            (True, "")   # Refined search success
        ]
        
        mock_dashboard_page.locator.return_value = mock_locator
        mock_locator.count.side_effect = [3, 1]  # 3 initial results, 1 after refinement
        
        # Mock the page opening process
        new_page = AsyncMock(spec=Page)
        new_page.url = "https://example.com/case/12345"
        new_page.wait_for_selector = AsyncMock()
        
        # Create proper context manager mock
        mock_context = mock_dashboard_page.context
        mock_context.expect_page.return_value = MockAsyncContextManager(new_page)
        
        result = await mock_handler.search_and_open_case_page(
            mock_dashboard_page, "Test Case", "12345"
        )
        
        # Verify result
        assert result[0] == new_page
        assert "Multiple (3) for name; refining with number" in result[1]
        
        # Verify both searches were called
        assert mock_handler._perform_search_on_dashboard.call_count == 2
        mock_handler._perform_search_on_dashboard.assert_any_call(
            mock_dashboard_page, "Test Case"
        )
        mock_handler._perform_search_on_dashboard.assert_any_call(
            mock_dashboard_page, "Test Case", "12345"
        )

    @pytest.mark.asyncio
    async def test_no_results_fallback_to_case_number_success(self, mock_handler, mock_dashboard_page, mock_locator):
        """Test no results from case name, successful fallback to case number search."""
        # Setup mocks
        mock_handler._perform_search_on_dashboard.side_effect = [
            (True, ""),  # Initial search success but no results
            (True, "")   # Fallback search success
        ]
        
        mock_dashboard_page.locator.return_value = mock_locator
        mock_locator.count.side_effect = [0, 0, 1]  # No results initially, then 1 after fallback
        
        # Mock the page opening process
        new_page = AsyncMock(spec=Page)
        new_page.url = "https://example.com/case/12345"
        new_page.wait_for_selector = AsyncMock()
        
        # Create proper context manager mock
        mock_context = mock_dashboard_page.context
        mock_context.expect_page.return_value = MockAsyncContextManager(new_page)
        
        result = await mock_handler.search_and_open_case_page(
            mock_dashboard_page, "Test Case", "12345"
        )
        
        # Verify result
        assert result[0] == new_page
        assert "No results for case name, attempting fallback search by case number" in result[1]
        assert "Single result found by case number fallback search" in result[1]
        
        # Verify searches and clear_search_input was called
        assert mock_handler._perform_search_on_dashboard.call_count == 2
        mock_handler.clear_search_input.assert_called_once_with(mock_dashboard_page)

    @pytest.mark.asyncio
    async def test_fallback_multiple_results_refined_success(self, mock_handler, mock_dashboard_page, mock_locator):
        """Test fallback to case number finds multiple results, then refined with case name."""
        # Setup mocks
        mock_handler._perform_search_on_dashboard.side_effect = [
            (True, ""),  # Initial search success but no results
            (True, ""),  # Fallback search success with multiple results
            (True, "")   # Refined fallback search success
        ]
        
        mock_dashboard_page.locator.return_value = mock_locator
        mock_locator.count.side_effect = [0, 0, 3, 2]  # No results, then 3, then 2 after refinement
        
        # Mock the page opening process
        new_page = AsyncMock(spec=Page)
        new_page.url = "https://example.com/case/12345"
        new_page.wait_for_selector = AsyncMock()
        
        # Create proper context manager mock
        mock_context = mock_dashboard_page.context
        mock_context.expect_page.return_value = MockAsyncContextManager(new_page)
        
        result = await mock_handler.search_and_open_case_page(
            mock_dashboard_page, "Test Case", "12345"
        )
        
        # Verify result
        assert result[0] == new_page
        assert "Multiple results for case number, refining with case name" in result[1]
        assert "Multiple (2) results after fallback refinement; selecting first listed" in result[1]
        
        # Verify all three searches were called
        assert mock_handler._perform_search_on_dashboard.call_count == 3

    @pytest.mark.asyncio
    async def test_no_results_after_all_searches(self, mock_handler, mock_dashboard_page, mock_locator):
        """Test when no results are found after all search attempts."""
        # Setup mocks
        mock_handler._perform_search_on_dashboard.side_effect = [
            (True, ""),  # Initial search success but no results
            (True, "")   # Fallback search success but no results
        ]
        
        mock_dashboard_page.locator.return_value = mock_locator
        mock_locator.count.return_value = 0  # Always no results
        
        result = await mock_handler.search_and_open_case_page(
            mock_dashboard_page, "Test Case", "12345"
        )
        
        # Verify result
        assert result == (None, "No results for case name, attempting fallback search by case number.; No results found by case number. Case not found.", None, None)

    @pytest.mark.asyncio
    async def test_refined_search_no_results(self, mock_handler, mock_dashboard_page, mock_locator):
        """Test when refined search yields no results."""
        # Setup mocks
        mock_handler._perform_search_on_dashboard.side_effect = [
            (True, ""),  # Initial search success with multiple results
            (True, "")   # Refined search success but no results
        ]
        
        mock_dashboard_page.locator.return_value = mock_locator
        mock_locator.count.side_effect = [3, 0]  # 3 initial results, 0 after refinement
        
        result = await mock_handler.search_and_open_case_page(
            mock_dashboard_page, "Test Case", "12345"
        )
        
        # Verify result
        assert result[0] is None
        assert "No results after refining with name and number" in result[1]

    @pytest.mark.asyncio
    async def test_page_opening_exception(self, mock_handler, mock_dashboard_page, mock_locator):
        """Test when page opening fails with an exception."""
        # Setup mocks for successful search
        mock_handler._perform_search_on_dashboard.return_value = (True, "")
        mock_dashboard_page.locator.return_value = mock_locator
        mock_locator.count.return_value = 1
        
        # Make the nested locator's click method raise an exception
        mock_locator.first.locator.return_value.click.side_effect = PlaywrightTimeoutError("Click timeout")
        
        result = await mock_handler.search_and_open_case_page(
            mock_dashboard_page, "Test Case", "12345"
        )
        
        # Verify result
        assert result[0] is None
        assert "PageOpenError: TimeoutError - Click timeout" in result[1]

    @pytest.mark.asyncio
    async def test_context_expect_page_exception(self, mock_handler, mock_dashboard_page, mock_locator):
        """Test when context.expect_page fails."""
        # Setup mocks for successful search
        mock_handler._perform_search_on_dashboard.return_value = (True, "")
        mock_dashboard_page.locator.return_value = mock_locator
        mock_locator.count.return_value = 1
        
        # Mock context.expect_page to raise an exception
        mock_context = mock_dashboard_page.context
        mock_context.expect_page.side_effect = Exception("Page creation failed")
        
        result = await mock_handler.search_and_open_case_page(
            mock_dashboard_page, "Test Case", "12345"
        )
        
        # Verify result
        assert result[0] is None
        assert "PageOpenError: Exception - Page creation failed" in result[1]

    @pytest.mark.asyncio
    async def test_target_case_link_locator_none(self, mock_handler, mock_dashboard_page, mock_locator):
        """Test logic error when target_case_link_locator is None."""
        # Setup mocks
        mock_handler._perform_search_on_dashboard.return_value = (True, "")
        mock_dashboard_page.locator.return_value = mock_locator
        mock_locator.count.return_value = 1
        mock_locator.first.locator.return_value = None  # Force None locator
        
        result = await mock_handler.search_and_open_case_page(
            mock_dashboard_page, "Test Case", "12345"
        )
        
        # Verify result - this should hit the logic error case
        assert result[0] is None
        assert "Logic error: target case link not identified" in result[1]

    @pytest.mark.asyncio
    async def test_search_notes_accumulation(self, mock_handler, mock_dashboard_page, mock_locator):
        """Test that search notes are properly accumulated throughout the process."""
        # Setup mocks for a complex scenario with multiple notes
        mock_handler._perform_search_on_dashboard.side_effect = [
            (True, "Initial search note"),  # Initial search
            (True, "Refined search note")   # Refined search
        ]
        
        mock_dashboard_page.locator.return_value = mock_locator
        mock_locator.count.side_effect = [3, 2]  # Multiple results, then fewer after refinement
        
        # Mock the page opening process
        new_page = AsyncMock(spec=Page)
        new_page.url = "https://example.com/case/12345"
        new_page.wait_for_selector = AsyncMock()
        
        # Create proper context manager mock
        mock_context = mock_dashboard_page.context
        mock_context.expect_page.return_value = MockAsyncContextManager(new_page)
        
        result = await mock_handler.search_and_open_case_page(
            mock_dashboard_page, "Test Case", "12345"
        )
        
        # Verify that notes are accumulated
        notes = result[1]
        assert "Initial search note" in notes
        assert "Refined search note" in notes
        assert "Multiple (3) for name; refining with number" in notes
        assert "Multiple (2) results after refinement; selecting first listed" in notes

    @pytest.mark.asyncio
    async def test_extract_methods_called_on_success(self, mock_handler, mock_dashboard_page, mock_locator):
        """Test that extract methods are called when page opens successfully."""
        # Setup mocks for successful single result
        mock_handler._perform_search_on_dashboard.return_value = (True, "")
        mock_dashboard_page.locator.return_value = mock_locator
        mock_locator.count.return_value = 1
        
        # Mock the page opening process
        new_page = AsyncMock(spec=Page)
        new_page.url = "https://example.com/case/12345"
        new_page.wait_for_selector = AsyncMock()
        
        # Create proper context manager mock
        mock_context = mock_dashboard_page.context
        mock_context.expect_page.return_value = MockAsyncContextManager(new_page)
        
        result = await mock_handler.search_and_open_case_page(
            mock_dashboard_page, "Test Case", "12345"
        )
        
        # Verify extract methods were called
        mock_handler.extract_case_name_from_detail_page.assert_called_once_with(new_page, "12345")
        mock_handler.extract_case_number_from_detail_page.assert_called_once_with(new_page, "12345")
        
        # Verify returned values
        assert result[2] == "Test Case Name"
        assert result[3] == "12345"

    @pytest.mark.asyncio
    async def test_double_check_delay_for_no_results(self, mock_handler, mock_dashboard_page, mock_locator):
        """Test that double check with delay is performed when no initial results."""
        # Setup mocks
        mock_handler._perform_search_on_dashboard.side_effect = [
            (True, ""),  # Initial search success
            (True, "")   # Fallback search
        ]
        
        mock_dashboard_page.locator.return_value = mock_locator
        # First count returns 0, second count (after delay) also returns 0
        mock_locator.count.side_effect = [0, 0, 1]  # 0, then 0 after delay, then 1 from fallback
        
        # Mock the page opening process
        new_page = AsyncMock(spec=Page)
        new_page.url = "https://example.com/case/12345"
        new_page.wait_for_selector = AsyncMock()
        
        # Create proper context manager mock
        mock_context = mock_dashboard_page.context
        mock_context.expect_page.return_value = MockAsyncContextManager(new_page)
        
        result = await mock_handler.search_and_open_case_page(
            mock_dashboard_page, "Test Case", "12345"
        )
        
        # Verify count was called multiple times (initial, after delay, fallback)
        assert mock_locator.count.call_count >= 3


if __name__ == "__main__":
    pytest.main([__file__])
