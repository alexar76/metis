"""Agentic RAG — iterative retrieval with query decomposition."""

from __future__ import annotations

from metis.memory.store import VectorMemory
from metis.models.provider import LLMProvider, extract_json

DECOMPOSE_SYSTEM = """Break the query into 1-3 focused sub-queries for document retrieval.
Respond with JSON: {"sub_queries": ["...", "..."]}"""

SYNTHESIZE_SYSTEM = """Answer using ONLY the provided documents. Cite sources by number [1], [2].
If documents are insufficient, say what is missing."""


async def agentic_rag(
    provider: LLMProvider,
    query: str,
    memory: VectorMemory,
    *,
    top_k: int = 5,
    max_iterations: int = 2,
) -> tuple[str, list[str]]:
    """Decompose query, retrieve iteratively, synthesize with citations."""
    sub_queries = await _decompose(provider, query)
    all_docs: list[str] = []
    seen: set[str] = set()

    for _ in range(max_iterations):
        for sq in sub_queries:
            hits = memory.search(sq, top_k=top_k)
            for h in hits:
                if h.content not in seen:
                    seen.add(h.content)
                    all_docs.append(h.content)
        if len(all_docs) >= top_k:
            break
        sub_queries = [f"{query} additional context needed"]

    if not all_docs:
        return "", []

    # SECURITY: wrap retrieved documents as untrusted data — they come from
    # external sources (user input stored in vector store) and may contain
    # prompt-injection payloads.
    from metis.security.injection import wrap_untrusted
    doc_block = "\n\n".join(f"[{i+1}] {d}" for i, d in enumerate(all_docs[:top_k * 2]))
    doc_block = wrap_untrusted(doc_block, label="rag_retrieval")
    answer = await provider.complete_text(
        SYNTHESIZE_SYSTEM,
        f"Retrieved context:\n{doc_block}\n\nQuestion: {query}",
        temperature=0.3,
    )
    return answer, all_docs


async def _decompose(provider: LLMProvider, query: str) -> list[str]:
    raw = await provider.complete_text(DECOMPOSE_SYSTEM, query, temperature=0.2)
    try:
        data = extract_json(raw)
        return data.get("sub_queries", [query]) or [query]
    except (ValueError, KeyError):
        return [query]
