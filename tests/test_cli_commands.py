"""CLI tests for metis logs and knowledge commands."""

import json
from pathlib import Path

from metis.knowledge.cli import run_knowledge_cli
from metis.knowledge.store import KnowledgeEntry, KnowledgeStore
from metis.observability.cli import run_logs_cli
from metis.observability.trace_store import TraceStore


def test_logs_trace_tail_stats(tmp_path, capsys):
    store = TraceStore(tmp_path)
    store.save({
        "trace_id": "cli-trace-1",
        "status": "success",
        "route": "council",
        "spans": [{"module_role": "judge", "endpoint": "api.example.com", "status": "ok"}],
    })

    assert run_logs_cli(["trace", "cli-trace-1", "--dir", str(tmp_path)]) == 0
    assert "cli-trace-1" in capsys.readouterr().out

    assert run_logs_cli(["tail", "-n", "5", "--dir", str(tmp_path)]) == 0
    line = capsys.readouterr().out.strip().splitlines()[0]
    assert json.loads(line)["trace_id"] == "cli-trace-1"

    assert run_logs_cli(["stats", "--dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "Total traces: 1" in out


def test_knowledge_export_cli(tmp_path):
    store = KnowledgeStore(tmp_path / "knowledge")
    store.add(KnowledgeEntry(
        id="e1",
        task_spec_json='{"goal": "test"}',
        query="export me",
        answer="done",
        verify_pass=True,
    ))
    out = tmp_path / "out.jsonl"
    rc = run_knowledge_cli(["export", "-o", str(out), "--store", str(tmp_path / "knowledge")])
    assert rc == 0
    assert "export me" in out.read_text()
