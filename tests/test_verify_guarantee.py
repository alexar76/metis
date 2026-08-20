"""The /v1/verify **verification guarantee** — the signal a money gate reads.

Metis's `fast` and `thinking` routes are a single provider call and run no verifier,
so they leave `verify_score` at its 0.0 default. The AIMarket hub's Pay-on-Verified
escrow used to read that as "the delivery scored 0.0", i.e. a provider failure:
every invoke priced $0.05–$0.50 is clamped to `fast`, so every one of them was
refunded, given a signed rejection receipt, a `verify_failed` reputation event and a
step up the slash ladder — for work nothing had ever looked at.

The endpoints therefore promise two things, and this module is what holds them:

  1. **/v1/verify really verifies.** On a route that ran no verifier of its own, the
     real critic scores the produced answer before the envelope is returned, and
     `verify_performed` says truthfully whether that happened.
  2. **/aimarket/invoke does not.** It is a billed capability invoke whose cost the
     hub priced at one cognition pass; silently adding a second LLM call would change
     what the operator is charged. Its envelope stays honest instead
     (`verify_performed: false`), which the escrow classifies as indeterminate.

Both are asserted against the *provider call count*, because that — not a return
value — is what an operator pays for, and a stub that invents a score is exactly how
the original bug stayed green.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from metis.api import ecosystem
from metis.api.app import create_app
from metis.config import ProviderKind, RuntimeConfig
from metis.models.provider import LLMProvider


@pytest.fixture
def cfg(tmp_path):
    """Standalone MOCK-provider config — the package's own test convention."""
    return RuntimeConfig(
        provider=ProviderKind.MOCK,
        allow_test_provider=True,
        memory_dir=tmp_path / "memory",
        thinking_samples=1,
    )


@pytest.fixture
def calls(monkeypatch):
    """Count every provider completion, from anywhere in the stack.

    Wraps the base class rather than MockProvider so the critic's own `judge` slot is
    counted too — the whole question here is whether a SECOND call happened.
    """
    counter = {"n": 0}
    original = LLMProvider.complete_text

    async def counting(self, system, user, **kwargs):
        counter["n"] += 1
        return await original(self, system, user, **kwargs)

    monkeypatch.setattr(LLMProvider, "complete_text", counting)
    return counter


@pytest.fixture
def critic_pass(monkeypatch):
    """Count the FORCED critic pass specifically (the guarantee's extra call).

    Only the endpoint's own reference is wrapped, so the council's internal verifier —
    a different call site — is untouched and the two are told apart.
    """
    counter = {"n": 0}
    original = ecosystem.verify_answer

    async def counting(*args, **kwargs):
        counter["n"] += 1
        return await original(*args, **kwargs)

    monkeypatch.setattr(ecosystem, "verify_answer", counting)
    return counter


@pytest.fixture
def client(cfg, monkeypatch):
    # API auth is env-driven and process-global: a key or prod flag left behind by an
    # earlier test would 401 these endpoints and make the result depend on collection
    # order rather than on the code under test.
    for var in ("METIS_API_KEY", "SUPERBRAIN_API_KEY", "COGNITIVE_API_KEY",
                "METIS_PRODUCTION", "SUPERBRAIN_PRODUCTION", "COGNITIVE_PRODUCTION",
                "AIFACTORY_PROD", "AIFACTORY_PRODUCTION", "AIFACTORY_ENV"):
        monkeypatch.delenv(var, raising=False)
    return TestClient(create_app(cfg))


def _post(client, calls, path, body):
    calls["n"] = 0
    r = client.post(path, json=body)
    assert r.status_code == 200, r.text
    return r.json(), calls["n"]


# ── 1. The guarantee: a non-scoring route still gets verified ────────────────


@pytest.mark.parametrize("route", ["fast", "thinking"])
def test_verify_performs_a_real_verification_on_a_non_scoring_route(
    client, calls, critic_pass, route,
):
    env, _ = _post(client, calls, "/v1/verify", {"input": "audit this delivery", "route": route})
    assert env["status"] == "success"
    assert env["verify_performed"] is True
    # A REAL score from the critic, not the unscored default that started all this.
    assert env["verify_score"] > 0.0
    assert env["verified"] is True
    # …bought by exactly one extra judge pass, not zero and not a retry storm.
    assert critic_pass["n"] == 1


def test_fast_route_costs_exactly_two_provider_passes(client, calls):
    """Pinned absolutely, not just relatively: `fast` is the price-clamped route the
    hub sends $0.05–$0.50 invokes to, so its bill is the one that matters. The run,
    then the critic — two completions, no more."""
    _, n = _post(client, calls, "/v1/verify", {"input": "audit this delivery", "route": "fast"})
    assert n == 2


def test_council_already_verifies_and_pays_nothing_extra(client, calls, critic_pass):
    """The council path runs its own critic, so the guarantee must be a no-op there —
    the forced pass keys off the ARTIFACT (a judged TaskSpec), not the route name, and
    must not double-judge an answer a verifier already scored."""
    env, _ = _post(client, calls, "/v1/verify",
                   {"input": "audit this delivery", "route": "council"})
    assert env["verify_performed"] is True  # a verifier had already run…
    assert critic_pass["n"] == 0            # …so the endpoint added nothing


# ── 2. The cost profile of the billed invoke is unchanged ────────────────────


def test_aimarket_invoke_did_not_gain_the_critic_pass(client, calls, critic_pass):
    """The hub priced this capability at one cognition pass. The envelope must stay
    honest about it rather than quietly buying a verdict on the operator's tab."""
    body, n = _post(client, calls, "/aimarket/invoke",
                    {"input": "audit this delivery", "route": "fast"})
    env = body["result"]
    assert n == 1 and critic_pass["n"] == 0
    assert env["verify_performed"] is False
    assert env["verify_score"] == 0.0
    # …and therefore not "verified" — an unscored run is never a clean bill of health.
    assert env["verified"] is False


def test_sandbox_invoke_also_stays_one_pass(client, calls):
    """Catalog probes are forced onto `fast`; they must not become the expensive path."""
    calls["n"] = 0
    r = client.post("/aimarket/invoke", json={"input": "probe"},
                    headers={"X-AIMarket-Sandbox": "1"})
    assert r.status_code == 200
    assert r.json()["result"]["route"] == "fast"
    assert calls["n"] == 1


# ── 3. A critic outage is reported, never invented ───────────────────────────


def test_critic_outage_yields_an_honest_not_performed_envelope(client, calls, monkeypatch, caplog):
    """If the judge cannot run, the endpoint must say so. Inventing a score here would
    be worse than the original bug: the hub moves money on this number."""

    async def _boom(*a, **k):
        raise RuntimeError("judge down sk-secret-should-not-leak")

    monkeypatch.setattr(ecosystem, "verify_answer", _boom)
    with caplog.at_level("WARNING"):
        env, _ = _post(client, calls, "/v1/verify",
                       {"input": "audit this delivery", "route": "fast"})

    assert env["status"] == "success"       # the RUN succeeded…
    assert env["verify_performed"] is False  # …but nothing verified it
    assert env["verify_score"] == 0.0
    assert env["verified"] is False
    assert env["answer"]                     # the caller still gets the work
    # A provider error can embed credentials: neither the wire nor the log may carry it.
    assert "sk-secret" not in json.dumps(env)
    assert "sk-secret" not in caplog.text


def test_critic_timeout_is_not_a_score(cfg, monkeypatch):
    """The forced pass is time-boxed. A judge that never returns must resolve to
    "not performed", not to a default number — a hung verifier is the same evidence
    as a crashed one: none."""
    import asyncio
    from types import SimpleNamespace

    async def _hang(*a, **k):
        await asyncio.sleep(30)

    monkeypatch.setattr(ecosystem, "verify_answer", _hang)
    monkeypatch.setattr(ecosystem, "_VERIFY_PASS_MIN_BUDGET_S", 0.05)
    result = SimpleNamespace(answer="an answer worth judging")
    score, performed = asyncio.run(
        ecosystem._score_unverified(cfg, result, "the query", budget_s=0.05)
    )
    assert (score, performed) == (0.0, False)


# ── 4. The cost knob ─────────────────────────────────────────────────────────


def test_guarantee_can_be_switched_off_and_then_reports_the_truth(client, calls, monkeypatch):
    """Two LLM calls per verify is a deliberate, documented decision — an operator may
    decline it. Declining must not fabricate a verdict: the envelope then reports the
    unscored run honestly, which a money gate reads as indeterminate, never as a fault."""
    monkeypatch.setenv("METIS_VERIFY_GUARANTEE", "0")
    env, n = _post(client, calls, "/v1/verify", {"input": "audit this delivery", "route": "fast"})
    assert n == 1                            # the saving is real
    assert env["verify_performed"] is False  # and it is declared
    assert env["verify_score"] == 0.0
    assert env["verified"] is False


@pytest.mark.parametrize("value", ["1", "true", "ON", "", "disabled", "2", "'0'"])
def test_only_an_explicit_boolean_disarms_the_guarantee(monkeypatch, value):
    """Fail-closed knob convention: a value that parses as NEITHER boolean is a typo,
    and a typo must not silently return /v1/verify to answering "nothing verified"."""
    monkeypatch.setenv("METIS_VERIFY_GUARANTEE", value)
    assert ecosystem.verify_guarantee_enabled() is True


@pytest.mark.parametrize("value", ["0", "false", "no", " OFF "])
def test_explicit_opt_out_is_honoured(monkeypatch, value):
    monkeypatch.setenv("METIS_VERIFY_GUARANTEE", value)
    assert ecosystem.verify_guarantee_enabled() is False


def test_guarantee_is_on_when_the_knob_is_unset(monkeypatch):
    monkeypatch.delenv("METIS_VERIFY_GUARANTEE", raising=False)
    assert ecosystem.verify_guarantee_enabled() is True


# ── 5. The threshold the verdict was decided at is echoed back ───────────────


def test_envelope_echoes_the_bar_it_judged_against(client, calls):
    """The hub sends its own AIMARKET_VERIFY_SCORE_THRESHOLD as `min_verify_score` and
    then re-applies it to the returned score. Echoing the bar makes a verifier judging
    at a DIFFERENT one detectable instead of silently authoritative."""
    env, _ = _post(client, calls, "/v1/verify",
                   {"input": "audit this", "route": "fast", "min_verify_score": 0.85})
    assert env["threshold"] == pytest.approx(0.85)
    default, _ = _post(client, calls, "/v1/verify", {"input": "audit this", "route": "fast"})
    assert default["threshold"] == pytest.approx(ecosystem.DEFAULT_VERIFY_PASS)


def test_engine_error_envelope_still_carries_the_bar(client, calls, monkeypatch):
    """The error envelope is the one an operator reads when settlements go
    indeterminate — it must not be the one shape that hides the threshold."""

    async def _boom(self, *a, **k):
        raise RuntimeError("simulated provider outage")

    monkeypatch.setattr("metis.api.ecosystem.Metis.run", _boom)
    env, _ = _post(client, calls, "/v1/verify",
                   {"input": "x", "route": "fast", "min_verify_score": 0.6})
    assert env["status"] == "error" and env["threshold"] == pytest.approx(0.6)


# ── 6. The stream tells the same story as the plain endpoint ─────────────────


def _sse_frames(text: str) -> list[tuple[str, dict]]:
    frames = []
    for block in text.split("\n\n"):
        event = payload = None
        for line in block.splitlines():
            if line.startswith("event: "):
                event = line[len("event: "):]
            elif line.startswith("data: "):
                payload = line[len("data: "):]
        if event and payload is not None:
            frames.append((event, json.loads(payload)))
    return frames


def test_streamed_done_frame_agrees_with_the_plain_endpoint(client, calls, critic_pass):
    """The landing panel and the reactive star read the streamed `done` frame. If it
    could disagree with /v1/verify about whether anything was verified, the two
    surfaces would be telling different stories about the same run."""
    body = {"input": "audit this delivery", "route": "fast"}
    plain, _ = _post(client, calls, "/v1/verify", body)
    assert critic_pass["n"] == 1

    r = client.post("/v1/verify/stream", json=body)
    assert r.status_code == 200
    assert critic_pass["n"] == 2  # the stream paid for its own guarantee, once
    done = [payload for event, payload in _sse_frames(r.text) if event == "done"]
    assert len(done) == 1, r.text[:400]
    env = done[0]

    assert env["verify_performed"] is plain["verify_performed"] is True
    assert env["verify_score"] > 0.0
    assert env["verified"] is plain["verified"]
    assert env["threshold"] == plain["threshold"]


def test_streamed_done_frame_respects_the_knob(client, calls, critic_pass, monkeypatch):
    monkeypatch.setenv("METIS_VERIFY_GUARANTEE", "0")
    calls["n"] = 0
    r = client.post("/v1/verify/stream", json={"input": "audit this", "route": "fast"})
    done = [p for e, p in _sse_frames(r.text) if e == "done"]
    assert len(done) == 1
    assert done[0]["verify_performed"] is False
    assert calls["n"] == 1 and critic_pass["n"] == 0


# ── 7. The judge's own number is bounded before anyone banks on it ───────────


def test_out_of_range_judge_score_cannot_inflate_the_envelope(client, calls, monkeypatch):
    """A judge answering `"score": 95` (meaning 95%) would clear every downstream
    `>= threshold` comparison trivially.

    Bounding it into [0, 1] is not enough on its own: folding 95 DOWN to 1.0 keeps the
    number on-scale and still hands the maximum possible confidence to a judge that
    just proved it is not answering on the demanded scale — the hub would capture on
    it. An unreadable number is refused (0.0), the same as `null`, and the direction
    matters more than the range.
    """
    from metis.verify import critic

    async def _overscored(*a, **k):
        return critic.Verdict(passed=True, score=95.0, feedback="")

    # The bound lives in the critic's parser, so drive it through the parser itself…
    assert critic.clamp_score(95.0) == 0.0       # off the scale is not "very confident"
    assert critic.clamp_score(float("inf")) == 0.0
    assert critic.clamp_score(1.0) == 1.0        # …and the top of the scale still works
    assert critic.clamp_score(1.0 + 1e-12) == 1.0   # float-repr slack, not an off-scale value
    assert critic.clamp_score(-3) == 0.0
    assert critic.clamp_score("nan") == 0.0
    assert critic.clamp_score(None) == 0.0       # a null score is not a score
    assert critic.clamp_score("0.42") == pytest.approx(0.42)

    # …and prove the envelope can never carry an out-of-scale score either, nor call
    # one a pass: `verified` is what the hub's escrow reads as "the audit vouches".
    monkeypatch.setattr(ecosystem, "verify_answer", _overscored)
    env, _ = _post(client, calls, "/v1/verify", {"input": "audit this", "route": "fast"})
    assert env["verify_score"] == 0.0
    assert env["verified"] is False


def test_judge_returning_a_null_score_is_a_zero_not_a_crash():
    """`float(None)` raises TypeError, which the parser's `except ValueError` never
    caught — on the council path that escaped as a 500 instead of a failed verdict."""
    import asyncio

    from metis.verify import critic
    from metis.schemas.task_spec import TaskSpec

    cfg = RuntimeConfig(provider=ProviderKind.MOCK, allow_test_provider=True)

    class _NullScoreProvider:
        async def complete_text(self, system, user, **kwargs):
            return json.dumps({"pass": True, "score": None, "feedback": None})

    class _Registry:
        def __init__(self, _cfg):
            pass

        def get_provider_for_role(self, _role):
            return _NullScoreProvider()

    original = critic.ModuleRegistry
    critic.ModuleRegistry = _Registry
    try:
        verdict = asyncio.run(critic.verify_answer(
            cfg, TaskSpec(goal="g", success_criteria=["c"], confidence=1.0), "answer", "query",
        ))
    finally:
        critic.ModuleRegistry = original
    assert verdict.score == 0.0 and verdict.feedback == ""


# ── 5. The guarantee lives inside the wall-clock the caller was promised ──────
#
# `request_timeout_seconds` is the deadline /v1/verify advertises. The forced critic
# pass used to be granted `max(floor, remaining)`, i.e. its full floor even when the
# run had already eaten the entire budget — so the response could land past the
# deadline for reasons nothing in the code stated or bounded. It is now explicit:
# inside the budget when the budget covers it, a BOUNDED borrow past the deadline
# when it does not, and a refusal (honest "nothing verified") once the borrow is
# spent.


@pytest.mark.parametrize("remaining", [300.0, 60.0, 10.0, 9.99, 3.0, 0.0, -4.0, -9.99, -10.0, -25.0])
def test_forced_critic_budget_never_breaks_the_declared_overrun_bound(remaining):
    """The one invariant a caller can rely on:

        elapsed + granted <= timeout + _VERIFY_PASS_MAX_OVERRUN_S

    Expressed in terms of what this helper sees (remaining = timeout - elapsed):
    granted <= remaining + ceiling.
    """
    granted = ecosystem._verify_pass_budget(remaining)
    assert granted >= 0.0
    assert granted <= max(0.0, remaining + ecosystem._VERIFY_PASS_MAX_OVERRUN_S) + 1e-9
    if remaining >= ecosystem._VERIFY_PASS_MIN_BUDGET_S:
        # Comfortable budget: the pass finishes strictly inside the deadline.
        assert granted == remaining


def test_forced_critic_is_refused_outright_once_the_overrun_is_spent(cfg, monkeypatch):
    """Budget gone AND the borrow gone: no provider call at all.

    Before this was bounded, a request already past its deadline still bought a
    fresh 10-second judge call. The caller had stopped waiting; the operator paid
    for it anyway.
    """
    import asyncio
    from types import SimpleNamespace

    called = {"n": 0}

    async def _judge(*a, **k):
        called["n"] += 1
        raise AssertionError("the critic must not be invoked past the overrun bound")

    monkeypatch.setattr(ecosystem, "verify_answer", _judge)
    result = SimpleNamespace(answer="an answer worth judging")
    score, performed = asyncio.run(
        ecosystem._score_unverified(cfg, result, "the query", budget_s=-30.0)
    )
    assert called["n"] == 0
    assert (score, performed) == (0.0, False)   # honest, not invented


def test_a_run_that_ate_the_whole_budget_still_gets_a_bounded_critic_pass(cfg, monkeypatch):
    """Exactly at the deadline the guarantee is still honoured — but with the
    declared borrow, not with an unbounded floor."""
    import asyncio
    from types import SimpleNamespace

    granted = ecosystem._verify_pass_budget(0.0)
    assert 0.0 < granted <= ecosystem._VERIFY_PASS_MAX_OVERRUN_S

    result = SimpleNamespace(answer="an answer worth judging")
    score, performed = asyncio.run(
        ecosystem._score_unverified(cfg, result, "the query", budget_s=0.0)
    )
    assert performed is True
    assert 0.0 <= score <= 1.0


def test_the_endpoint_reports_an_exhausted_budget_as_unverified(client, calls, monkeypatch):
    """End to end: a run that overruns the request deadline returns the work with an
    honest `verify_performed: false` rather than a late, invented verdict."""
    # Only the endpoint module's clock is faked (a stand-in for `time`, not a patch of
    # the real module), so the run appears to have consumed 10_000s of a 600s budget —
    # far past both the deadline and the overrun allowance.
    class _FakeTime:
        @staticmethod
        def monotonic():
            _FakeTime.n = getattr(_FakeTime, "n", 0) + 1
            return 0.0 if _FakeTime.n == 1 else 10_000.0

    monkeypatch.setattr(ecosystem, "time", _FakeTime)
    env, n = _post(client, calls, "/v1/verify", {"input": "audit this delivery", "route": "fast"})
    assert n == 1                            # the critic was never bought
    assert env["status"] == "success"
    assert env["answer"]                     # the caller still gets the work
    assert env["verify_performed"] is False
    assert env["verify_score"] == 0.0
    assert env["verified"] is False
