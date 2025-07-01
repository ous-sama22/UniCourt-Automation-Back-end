import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services.unicourt_handler import UnicourtHandler
from app.core.config import get_app_settings

@pytest.mark.asyncio
async def test_close_worker_browser_resources():
    # Setup mocks
    mock_browser = AsyncMock()
    mock_browser.is_connected = MagicMock(return_value=True)
    mock_browser.close = AsyncMock()

    mock_context = AsyncMock()
    mock_context.close = AsyncMock()

    mock_page = AsyncMock()
    mock_page.is_closed = MagicMock(return_value=False)
    mock_page.close = AsyncMock()

    # Create handler with mocked page
    settings = get_app_settings()
    handler = UnicourtHandler(None, settings, dashboard_page_for_worker=mock_page)

    # Test closing resources
    await handler.close_worker_browser_resources(mock_browser, mock_context)

    # Verify all resources were closed in correct order
    mock_page.close.assert_called_once()
    mock_context.close.assert_called_once()
    mock_browser.close.assert_called_once()
    assert handler.dashboard_page_for_worker is None

@pytest.mark.asyncio
async def test_close_worker_browser_resources_with_already_closed():
    # Setup mocks with already closed states
    mock_browser = AsyncMock()
    mock_browser.is_connected = MagicMock(return_value=False)
    mock_browser.close = AsyncMock()

    mock_context = AsyncMock()
    mock_context.close = AsyncMock()

    mock_page = AsyncMock()
    mock_page.is_closed = MagicMock(return_value=True)
    mock_page.close = AsyncMock()

    # Create handler with mocked page
    settings = get_app_settings()
    handler = UnicourtHandler(None, settings, dashboard_page_for_worker=mock_page)

    # Test closing already closed resources
    await handler.close_worker_browser_resources(mock_browser, mock_context)

    # Verify behavior with already closed resources
    mock_page.close.assert_not_called()
    mock_context.close.assert_called_once()  # Still try to close context
    mock_browser.close.assert_not_called()  # Browser was not connected
    assert handler.dashboard_page_for_worker is None

@pytest.mark.asyncio
async def test_close_worker_browser_resources_with_exceptions():
    # Setup mocks that raise exceptions
    mock_browser = AsyncMock()
    mock_browser.is_connected = MagicMock(return_value=True)
    mock_browser.close = AsyncMock(side_effect=Exception("Browser close error"))

    mock_context = AsyncMock()
    mock_context.close = AsyncMock(side_effect=Exception("Context close error"))

    mock_page = AsyncMock()
    mock_page.is_closed = MagicMock(return_value=False)
    mock_page.close = AsyncMock(side_effect=Exception("Page close error"))

    # Create handler with mocked page
    settings = get_app_settings()
    handler = UnicourtHandler(None, settings, dashboard_page_for_worker=mock_page)

    # Test closing resources with exceptions
    # This should not raise any exceptions
    await handler.close_worker_browser_resources(mock_browser, mock_context)

    # Verify all close methods were called despite exceptions
    mock_page.close.assert_called_once()
    mock_context.close.assert_called_once()
    mock_browser.close.assert_called_once()
    assert handler.dashboard_page_for_worker is None
