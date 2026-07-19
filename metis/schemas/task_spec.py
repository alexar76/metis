"""Task specification schema — contract between understanding and solving."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Ambiguity(BaseModel):
    issue: str
    resolution: str = ""
    needs_user_input: bool = False


class TaskSpec(BaseModel):
    """Explicit task understanding artifact from the Understanding Council."""

    goal: str
    constraints: list[str] = Field(default_factory=list)
    non_goals: list[str] = Field(default_factory=list)
    ambiguities: list[Ambiguity] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    raw_interpretations: dict[str, str] = Field(default_factory=dict)

    @property
    def requires_tools(self) -> bool:
        tools = {t.lower() for t in self.required_tools if t and t.lower() != "none"}
        return bool(tools)

    def needs_clarification(self, threshold: float = 0.7) -> bool:
        if self.confidence < threshold:
            return True
        return any(a.needs_user_input and not a.resolution for a in self.ambiguities)

    def clarification_questions(self) -> list[str]:
        questions = []
        for a in self.ambiguities:
            if a.needs_user_input and not a.resolution:
                questions.append(a.issue)
        if self.confidence < 0.7:
            questions.append("Could you clarify your goal and any constraints?")
        return questions

    def to_context(self) -> str:
        lines = [
            f"GOAL: {self.goal}",
            f"CONFIDENCE: {self.confidence}",
        ]
        if self.constraints:
            lines.append("CONSTRAINTS: " + "; ".join(self.constraints))
        if self.non_goals:
            lines.append("NON-GOALS: " + "; ".join(self.non_goals))
        if self.success_criteria:
            lines.append("SUCCESS CRITERIA: " + "; ".join(self.success_criteria))
        if self.required_tools:
            lines.append("TOOLS NEEDED: " + ", ".join(self.required_tools))
        return "\n".join(lines)
