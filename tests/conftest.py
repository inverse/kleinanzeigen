"""Shared pytest fixture for network lockdown."""

import pytest
import pytest_socket


@pytest.fixture(autouse=True)
def _block_network():
    """Disable all network access in tests."""
    pytest_socket.disable_socket()
    yield
    pytest_socket.enable_socket()
