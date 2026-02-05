"""Pytest configuration and shared fixtures."""

import pytest


@pytest.fixture
def sample_device_key():
    """Provide a sample device key dictionary for testing."""
    return {
        "domain": 0,
        "bus": 3,
        "slot": 0,
        "function": 0,
        "vendor_id": 0x10B5,
        "device_id": 0xC040,
    }
