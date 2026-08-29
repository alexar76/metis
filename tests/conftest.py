"""Pytest configuration and markers."""

import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "benchmark: benchmark harness tests")
    config.addinivalue_line("markers", "requires_api_key: needs live API credentials")


@pytest.fixture(autouse=True)
def _let_metis_logs_reach_caplog():
    """Keep ``metis.*`` log records visible to ``caplog``.

    ``setup_logging`` installs a JSON handler on the ``metis`` logger and sets
    ``propagate = False`` so production logs are emitted once, in one format. It is
    process-global and runs on first use, so the moment ANY test initialises logging,
    every later ``caplog`` assertion against a ``metis.*`` logger silently sees an empty
    string — the record never reaches the root handler caplog installs. The test does not
    error; it just stops testing anything, and only when run after its neighbours.

    Restoring propagation for the duration of each test costs nothing (pytest owns the
    root handlers) and makes a caplog assertion mean what it appears to mean.
    """
    import logging

    metis_logger = logging.getLogger("metis")
    previous = metis_logger.propagate
    metis_logger.propagate = True
    try:
        yield
    finally:
        metis_logger.propagate = previous
