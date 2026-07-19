"""Targeted tests to raise core module coverage."""

import pytest

from metis.config import ProviderKind, RuntimeConfig
from metis.economy.tracked import TrackedProvider
from metis.models.provider import LLMResponse, Message
from metis.security.ssrf import validate_url, safe_get
from metis.tools.sandbox import execute_sandboxed
from metis.validation import validate_json_output, validate_task_spec_fields
from tests.support.mock_provider import MockProvider


@pytest.fixture
def mock_config(tmp_path):
    return RuntimeConfig(
        provider=ProviderKind.MOCK,
        allow_test_provider=True,
        memory_dir=tmp_path / "memory",
    )


def test_validate_json_invalid():
    result = validate_json_output("not json at all")
    assert not result.valid


def test_validate_task_spec_invalid_confidence():
    result = validate_task_spec_fields({"goal": "x", "confidence": 1.5})
    assert not result.valid


def test_validate_task_spec_missing_goal():
    result = validate_task_spec_fields({"confidence": 0.9})
    assert not result.valid


def test_ssrf_validate_url_blocks_private():
    with pytest.raises(ValueError):
        validate_url("http://169.254.169.254/latest/meta-data/")


def test_ssrf_validate_url_allows_public():
    url = validate_url("https://example.com/path")
    assert url.startswith("https://")


def test_sandbox_blocks_import_os():
    ok, out, err = execute_sandboxed("import os\nprint(os.getcwd())")
    assert not ok or "ImportError" in err or "not allowed" in err.lower()


def test_sandbox_allows_math():
    ok, out, err = execute_sandboxed("print(2 + 2)")
    assert ok
    assert "4" in out


@pytest.mark.asyncio
async def test_tracked_provider_records_usage(mock_config):
    from metis.config import ModelSlot
    from metis.economy.meter import UsageMeter, set_current_meter

    slot = mock_config.base_slot()
    inner = MockProvider(slot)
    meter = UsageMeter(route="test")
    set_current_meter(meter)
    try:
        tracked = TrackedProvider(inner, slot)
        await tracked.complete_text("system", "user")
        assert len(meter.events) >= 1
    finally:
        set_current_meter(None)


@pytest.mark.asyncio
async def test_agentic_rag(mock_config, tmp_path):
    from metis.exoskeleton import Metis
    from metis.memory.store import VectorMemory
    from metis.rag.agentic import agentic_rag
    from metis.models.provider import create_provider

    mem = VectorMemory(tmp_path / "rag.json")
    mem.add("Metis is a multi-agent orchestrator")
    provider = create_provider(mock_config.base_slot(), mock_config)
    answer, docs = await agentic_rag(provider, "What is Metis?", mem, top_k=3)
    assert isinstance(answer, str)
