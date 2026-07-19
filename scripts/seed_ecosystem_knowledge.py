#!/usr/bin/env python3
"""Seed the KnowledgeStore with core, verified ecosystem facts about Metis.

Reproducible and idempotent (fixed ids + INSERT OR REPLACE), so any fresh deploy
gets grounded RAG knowledge instead of an empty store. These are curated TRUE facts
that mirror the operator `identity:` block and the docs — not learned experiences.

Usage (in the container, cwd=/app):  python3 seed_ecosystem_knowledge.py
Or with an explicit store dir:        python3 seed_ecosystem_knowledge.py data/knowledge
"""
from __future__ import annotations

import sys
from pathlib import Path

from metis.knowledge.store import KnowledgeEntry, KnowledgeStore

# (id, category, question, answer) — grounded, verified ecosystem knowledge.
FACTS = [
    ("eco-what-is-metis", "identity",
     "What is Metis?",
     "Metis is a standalone, API-only multi-agent reasoning and verification service. It wraps "
     "any underlying LLM in a full cognitive stack: an Understanding Council of six parallel "
     "isolated agents plus a synthesizer, a fail-closed confidence gate, a layered Mixture-of-"
     "Agents that proposes/refines/aggregates, and a grounded verifier that retries on judge "
     "feedback — governed by DGPD depth gating and backed by working, episodic and vector memory "
     "with agentic RAG."),
    ("eco-which-ecosystem", "identity",
     "Which ecosystem is Metis part of?",
     "Metis is the cognition and verification tier of the alexar76 AICOM / AIMarket AI-agent "
     "economy — a family of loosely-coupled peers including the AI-Factory, the AIMarket Protocol, "
     "SDKs and Hub, verifiable oracles, and sibling agents ARGUS, DIOSCURI, HELIOS, ACEX, "
     "ai-service-mesh and alien-monitor. Every ecosystem link is optional and fail-open; Metis "
     "also runs fully standalone."),
    ("eco-routes", "capabilities",
     "What route modes does Metis have?",
     "Four: fast (a single call), thinking (extended chain-of-thought), council (the full council "
     "plus Mixture-of-Agents plus verifier), and agent (a Plan-Act-Observe-Reflect loop with tools "
     "and MCP). The default is council: it deliberates and verifies before answering, and asks for "
     "clarification instead of guessing."),
    ("eco-factory-gate", "use-cases",
     "How is Metis used by the AICOM factory?",
     "The AICOM factory routes high-stakes autonomous decisions (e.g. its architect/methodologist "
     "stages) through POST /v1/verify to gain a machine-readable confidence signal it otherwise "
     "lacks. The gate is opt-in and fail-open: if Metis is slow, down, or absent the factory runs "
     "exactly as before. It catches confidently-wrong decisions before they compound through the "
     "downstream build — worth the extra seconds because a bad autonomous decision costs the whole "
     "pipeline plus rework."),
    ("eco-envelope", "capabilities",
     "What is the Metis verification envelope?",
     "A verification-envelope service (POST /v1/verify) returns an answer together with a machine-"
     "readable confidence score (verify_score), a verified flag, and — via /v1/verify/stream — a "
     "live streamed trace of Metis's own reasoning. It turns 'trust one answer' into a judgement a "
     "caller can threshold on, retry, or escalate."),
    ("eco-endpoints", "capabilities",
     "What API endpoints does Metis expose?",
     "An OpenAI-compatible chat API (/v1/chat/completions), the verification envelope "
     "(/v1/verify and the SSE /v1/verify/stream), an AIMarket Hub capability contract "
     "(/aimarket/invoke), plus health, feedback and trace endpoints."),
    ("eco-mnemosyne", "identity",
     "What is MNEMOSYNE and does Metis query it?",
     "MNEMOSYNE is the shared, GitHub-synced, AEGIS-firewalled knowledge base of the sibling "
     "satellite DIOSCURI, behind its CASTOR and POLLUX community twins. Metis knows about it but "
     "does NOT query it directly — it uses its own independent KnowledgeStore."),
    ("eco-tools", "capabilities",
     "What tools does Metis have?",
     "A sandboxed code interpreter and web search, vision/multimodal perception (any text inside "
     "an image is treated as untrusted data, never as instructions), grounded verification, and "
     "optional MCP tools and paid AIMarket capability calls (off by default)."),
    ("eco-confidence-gate", "capabilities",
     "What does the confidence gate do?",
     "After the Understanding Council reads a query, a fail-closed confidence gate scores whether "
     "the task is actually understood. Below threshold, Metis asks for clarification instead of "
     "guessing; above it, it proceeds to deliberate (MoA) and verify. This is the mechanism the "
     "factory relies on to avoid acting on a misunderstood instruction."),
    ("eco-vision", "capabilities",
     "How does Metis handle images?",
     "A vision-capable model perceives the image and produces an observation, which is treated as "
     "untrusted data and sanitized before feeding the reasoning council — text inside an image is "
     "never followed as an instruction. If the vision call is rate-limited or slow it retries "
     "within a bounded budget, then fails over to an honest 'couldn't read the image' note so the "
     "text pipeline is never blocked."),
]


def main() -> int:
    store_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/knowledge")
    store = KnowledgeStore(store_dir)
    for fid, category, q, a in FACTS:
        store.add(KnowledgeEntry(
            id=fid,
            task_spec_json="{\"goal\": %r}" % q,
            query=q,
            answer=a,
            category=category,
            metadata={"source": "ecosystem-seed", "curated": True},
            verify_pass=True,   # retrievable by RAG (search_similar defaults verify_pass_only=True)
            rating=5,
        ))
    print(f"seeded {len(FACTS)} ecosystem facts into {store_dir}; store now has {store.count()} entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
