"""Test-only mock LLM provider — NOT for production use."""

from __future__ import annotations

import json

from metis.config import ModelSlot
from metis.models.provider import LLMProvider, LLMResponse, Message


class MockProvider(LLMProvider):
    """Deterministic provider for tests only."""

    def __init__(self, slot: ModelSlot):
        self.slot = slot

    async def complete(
        self,
        messages: list[Message],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        user = next((m.content for m in reversed(messages) if m.role == "user"), "")
        system = next((m.content for m in messages if m.role == "system"), "")

        if "IntentParser" in system or "intent" in system.lower():
            content = json.dumps({
                "goal": f"Understand and respond to: {user[:80]}",
                "assumptions": ["User wants a helpful answer"],
            }, ensure_ascii=False)
        elif "ConstraintExtractor" in system:
            content = json.dumps({
                "constraints": ["Be accurate and complete"],
                "non_goals": ["Over-engineering"],
            }, ensure_ascii=False)
        elif "AmbiguityHunter" in system:
            content = json.dumps({
                "ambiguities": [{"issue": "Scope unclear", "options": ["narrow", "broad"], "needs_user_input": False}],
            }, ensure_ascii=False)
        elif "planner" in system.lower():
            content = json.dumps({
                "plan": ["Analyze the task", "Execute solution", "Verify result"],
                "current_step": 0,
            }, ensure_ascii=False)
        elif "reflect" in system.lower():
            content = json.dumps({
                "assessment": "Progress made",
                "success": True,
                "next_action": "finish",
                "notes": "",
            }, ensure_ascii=False)
        elif "Classify" in system or "complexity" in system.lower():
            content = json.dumps({
                "mode": "council",
                "reason": "Mock routing",
                "scores": {"simplicity": 5, "ambiguity": 5, "tools_needed": 3},
            }, ensure_ascii=False)
        elif "RedTeam" in system or "red team" in system.lower():
            content = json.dumps({
                "wrong_readings": ["Alternative reading"],
                "traps": ["Over-engineering"],
            }, ensure_ascii=False)
        elif "TaskSynthesizer" in system or "synthesize" in system.lower():
            content = json.dumps({
                "goal": user[:200],
                "constraints": [],
                "non_goals": [],
                "ambiguities": [],
                "success_criteria": ["Answer addresses the user's question directly"],
                "required_tools": [],
                "confidence": 0.85,
            }, ensure_ascii=False)
        elif "Judge" in system or "verif" in system.lower():
            content = json.dumps({"pass": True, "feedback": "", "score": 0.9}, ensure_ascii=False)
        elif "extended thinking" in system.lower() or "chain of thought" in system.lower():
            content = "Let me reason step by step about this.\n\nBased on my analysis, here is the answer."
        elif "tool" in system.lower() and "json" in system.lower():
            content = json.dumps({"action": "answer", "content": f"Mock answer for: {user[:100]}"})
        else:
            content = f"[mock:{self.slot.name}] Response to: {user[:120]}"

        return LLMResponse(content=content, model=self.slot.model)
