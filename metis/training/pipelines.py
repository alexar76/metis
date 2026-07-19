"""Optional training pipelines — SFT and GRPO/DPO stubs."""

from __future__ import annotations

from pathlib import Path


def export_sft_dataset(trajectories_dir: Path, output_path: Path) -> int:
    """
    Export agent trajectories to LLaMA-Factory / Unsloth chat format.

    Expected trajectory JSONL per line:
    {"messages": [{"role": "system", ...}, {"role": "user", ...}, {"role": "assistant", ...}]}
    """
    import json

    records = []
    if not trajectories_dir.exists():
        return 0

    for path in trajectories_dir.glob("*.jsonl"):
        for line in path.read_text().splitlines():
            if line.strip():
                records.append(json.loads(line))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records))
    return len(records)


def grpo_training_config(
    base_model: str = "Qwen/Qwen3-8B",
    dataset_path: str = "data/sft/train.jsonl",
    output_dir: str = "checkpoints/grpo",
) -> dict:
    """
    Return config dict for OpenRLHF / verl GRPO training on verifiable tasks.

    Use for: math, code, structured JSON output where reward is automatic.
    """
    return {
        "model": base_model,
        "dataset": dataset_path,
        "output_dir": output_dir,
        "algorithm": "grpo",
        "reward_type": "verifiable",
        "notes": (
            "Train on tasks with automatic verification: code execution, "
            "math answer checking, JSON schema validation. "
            "Process-supervised DPO (ReasonRAG-style) recommended for agentic RAG."
        ),
    }


def dpo_training_config(
    base_model: str = "Qwen/Qwen3-8B",
    preference_dataset: str = "data/dpo/preferences.jsonl",
    output_dir: str = "checkpoints/dpo",
) -> dict:
    """DPO config for process-level preferences (chosen vs rejected reasoning paths)."""
    return {
        "model": base_model,
        "dataset": preference_dataset,
        "output_dir": output_dir,
        "algorithm": "dpo",
        "beta": 0.1,
        "notes": "Use RAG-ProGuide-style process preferences for agentic behaviour.",
    }
