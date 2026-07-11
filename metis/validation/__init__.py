"""Structured output validation — deterministic schema checks."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class ValidationResult:
    valid: bool
    errors: List[str]
    parsed: Optional[Dict[str, Any]] = None


def validate_json_output(raw: str, required_keys: List[str] | None = None) -> ValidationResult:
    """Parse and validate JSON output from an agent."""
    errors: List[str] = []
    try:
        data = _extract_json_object(raw)
    except ValueError as e:
        return ValidationResult(False, [str(e)])

    if not isinstance(data, dict):
        return ValidationResult(False, ["Output must be a JSON object"])

    if required_keys:
        for key in required_keys:
            if key not in data:
                errors.append(f"Missing required key: {key}")

    return ValidationResult(len(errors) == 0, errors, data)


def validate_task_spec_fields(data: Dict[str, Any]) -> ValidationResult:
    """Validate synthesizer output before building TaskSpec."""
    required = ["goal", "confidence"]
    errors = [f"Missing {k}" for k in required if k not in data]
    conf = data.get("confidence")
    if conf is not None:
        try:
            c = float(conf)
            if not 0.0 <= c <= 1.0:
                errors.append("confidence must be 0.0-1.0")
        except (TypeError, ValueError):
            errors.append("confidence must be numeric")
    return ValidationResult(len(errors) == 0, errors, data)


def _extract_json_object(raw: str) -> Dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("No JSON object found in output")
    return json.loads(text[start : end + 1])
