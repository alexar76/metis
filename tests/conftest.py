"""Pytest configuration and markers."""

import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "benchmark: benchmark harness tests")
    config.addinivalue_line("markers", "requires_api_key: needs live API credentials")
