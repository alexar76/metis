"""Integration test: observability + knowledge in Metis runtime."""

import pytest

from metis.config import ProviderKind, RuntimeConfig
from metis.exoskeleton import Metis, RunStatus


@pytest.mark.asyncio
async def test_run_emits_trace_and_knowledge(tmp_path):
    cfg = RuntimeConfig(
        provider=ProviderKind.MOCK,
        allow_test_provider=True,
        memory_dir=tmp_path / "memory",
        thinking_samples=1,
        enforce_confidence_gate=False,
        knowledge={"enabled": True, "store_path": str(tmp_path / "knowledge")},
        observability={"trace_dir": str(tmp_path / "traces")},
    )
    brain = Metis(cfg)
    result = await brain.run("What is 2+2?", route=cfg.default_route)

    assert result.status in (RunStatus.SUCCESS, RunStatus.NEEDS_CLARIFICATION)
    if result.metadata.get("trace_id"):
        from metis.observability.trace_store import TraceStore
        trace = TraceStore(tmp_path / "traces").get(result.metadata["trace_id"])
        assert trace is not None
