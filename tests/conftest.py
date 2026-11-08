"""Shared pytest fixtures: real-HTML fixtures + network lockdown."""

from pathlib import Path

import pytest
import pytest_socket

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def search_html() -> str:
    """Real kleinanzeigen search-result page (trimmed)."""
    return (FIXTURES_DIR / "search.html").read_text(encoding="utf-8")


@pytest.fixture
def detail_html() -> str:
    """Real kleinanzeigen ad-detail page (trimmed)."""
    return (FIXTURES_DIR / "detail.html").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _block_network():
    """Disable all network access in tests."""
    pytest_socket.disable_socket()
    yield
    pytest_socket.enable_socket()
