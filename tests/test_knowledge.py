"""Tests for knowledge store, experience replay, failure patterns."""

import json
from pathlib import Path

import pytest

from metis.knowledge.experience import ExperienceReplay
from metis.knowledge.failures import FailurePatterns
from metis.knowledge.store import KnowledgeEntry, KnowledgeStore
from metis.observability.reliability.detector import FailureKind
from metis.schemas.task_spec import TaskSpec


@pytest.fixture
def store(tmp_path):
    return KnowledgeStore(tmp_path)


def test_knowledge_add_and_search(store):
    entry = KnowledgeEntry(
        id="e1",
        task_spec_json='{"goal": "explain python decorators"}',
        query="How do Python decorators work?",
        answer="Decorators wrap functions...",
        verify_pass=True,
    )
    store.add(entry)
    hits = store.search_similar("python decorator explain")
    assert len(hits) >= 1
    assert hits[0].id == "e1"


def test_context_for_council(store):
    store.add(KnowledgeEntry(
        id="e2",
        task_spec_json='{"goal": "write fibonacci"}',
        query="Write a fibonacci function in Python",
        answer="def fib(n): ...",
        verify_pass=True,
    ))
    ctx = store.context_for_council("fibonacci python code")
    assert "fibonacci" in ctx.lower() or "Python" in ctx


def test_experience_replay(store):
    replay = ExperienceReplay(store)
    spec = TaskSpec(goal="test", confidence=0.9)
    eid = replay.maybe_save(
        query="test query",
        answer="test answer",
        task_spec=spec,
        verify_pass=True,
        trace_id="trace-1",
    )
    assert eid == "trace-1"
    assert store.count() == 1

    skipped = replay.maybe_save(
        query="q", answer="a", task_spec=spec, verify_pass=False,
    )
    assert skipped is None


def test_failure_patterns(tmp_path):
    fp = FailurePatterns(tmp_path)
    fp.record("implement python function", FailureKind.TIMEOUT)
    fp.record("implement python function", FailureKind.TIMEOUT)
    hint = fp.hint_for_query("write a python function")
    assert "timeout" in hint.lower()
    summary = fp.summary()
    assert "coding" in summary


def test_feedback_and_export(store):
    store.add_feedback("trace-abc", 5, "great answer")
    store.add(KnowledgeEntry(
        id="e3",
        task_spec_json='{"goal": "g"}',
        query="q",
        answer="a",
        verify_pass=True,
    ))
    records = store.export_jsonl()
    assert any(r.get("type") == "feedback" for r in records)
    assert any("task_spec" in r for r in records)


def test_knowledge_cli_export(tmp_path, capsys):
    from metis.knowledge.cli import run_knowledge_cli

    store = KnowledgeStore(tmp_path / "knowledge")
    store.add(KnowledgeEntry(
        id="e4",
        task_spec_json='{"goal": "g"}',
        query="export test",
        answer="exported",
        verify_pass=True,
    ))
    out = tmp_path / "out.jsonl"
    rc = run_knowledge_cli(["export", "-o", str(out), "--store", str(tmp_path / "knowledge")])
    assert rc == 0
    lines = out.read_text().strip().splitlines()
    assert len(lines) >= 1
    assert json.loads(lines[0])["query"] == "export test"
