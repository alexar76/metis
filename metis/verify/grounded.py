"""Grounded verifier — turns ``verify_score`` from opinion into evidence.

The base verifier (:mod:`metis.verify.critic`) is an LLM judge: another model's
*opinion* of whether an answer is right. This layer **grounds** that verdict by
*executing* the answer's code in the sandbox and folding the result into the
score:

* code that **fails to run** is strong negative evidence — the answer cannot be
  verified regardless of what the judge thinks, so the verdict is forced to
  fail with a low score;
* code that **runs clean** corroborates the judge and lifts the score.

This is the first slice of verifier-guided, tool-grounded evaluation ("VeriSearch"):
the value signal is grounded in reality, not another vibe. It is fully optional
(``config.enable_grounded_verify``, default on) and degrades to the plain LLM
judge when there is no executable code or no sandbox tool.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, List

from metis.config import RuntimeConfig
from metis.observability.logging.pipeline_events import PipelineEventKind, emit_pipeline_event
from metis.schemas.task_spec import TaskSpec
from metis.verify.critic import Verdict, verify_answer

# ```python … ``` or ``` … ``` fenced blocks.
_CODE_RE = re.compile(r"```(?:python|py)?[ \t]*\r?\n(.*?)```", re.DOTALL | re.IGNORECASE)
_MAX_BLOCKS = 3
_GROUNDED_FAIL_CEILING = 0.35  # a verdict whose code fails cannot score above this


@dataclass
class GroundedVerdict(Verdict):
    """A :class:`Verdict` enriched with execution evidence."""

    grounded: bool = False
    evidence: List[str] = field(default_factory=list)


def extract_code_blocks(answer: str) -> List[str]:
    """Return runnable code blocks from an answer (capped)."""
    blocks = [b.strip() for b in _CODE_RE.findall(answer or "") if b.strip()]
    return blocks[:_MAX_BLOCKS]


def _code_tool(tools: Any):
    try:
        return tools._tools.get("code_interpreter")  # type: ignore[attr-defined]
    except AttributeError:
        return None


async def grounded_verify(
    config: RuntimeConfig,
    task_spec: TaskSpec,
    answer: str,
    user_query: str,
    tools: Any = None,
) -> GroundedVerdict:
    """Verify ``answer`` with the LLM judge, then ground it by running its code."""
    base = await verify_answer(config, task_spec, answer, user_query)

    if not getattr(config, "enable_grounded_verify", True) or tools is None:
        return GroundedVerdict(base.passed, base.score, base.feedback, grounded=False, evidence=[])

    code_tool = _code_tool(tools)
    blocks = extract_code_blocks(answer)
    if code_tool is None or not blocks:
        return GroundedVerdict(
            base.passed, base.score, base.feedback,
            grounded=False, evidence=["no executable code to ground"],
        )

    evidence: List[str] = []
    errors = 0
    for i, code in enumerate(blocks):
        emit_pipeline_event(PipelineEventKind.TOOL_CALL, {"tool": "code_interpreter", "block": i + 1})
        res = await code_tool.run(code)
        if res.success:
            evidence.append(f"block {i + 1}: ran ✓ {res.output[:200].strip()}")
        else:
            errors += 1
            evidence.append(f"block {i + 1}: FAILED ✗ {(res.error or res.output)[:200].strip()}")

    if errors:
        # Executed and broke → the answer is not verifiable, whatever the judge said.
        score = min(base.score, _GROUNDED_FAIL_CEILING)
        detail = "; ".join(e for e in evidence if "✗" in e)
        feedback = (f"{base.feedback} | grounded: code failed — {detail}").strip(" |")
        return GroundedVerdict(False, score, feedback, grounded=True, evidence=evidence)

    # All blocks executed clean → corroborated. Blend judge + grounding.
    score = round(min(1.0, 0.6 * base.score + 0.4), 4)
    passed = bool(base.passed or score >= config.confidence_threshold)
    return GroundedVerdict(passed, score, base.feedback, grounded=True, evidence=evidence)
