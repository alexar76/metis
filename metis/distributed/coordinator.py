"""Distributed coordinator — orchestrates council/MoA across worker nodes."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from metis.config import ModelSlot, RuntimeConfig
from metis.distributed.registry import NodeRegistry
from metis.distributed.remote_provider import RemoteLLMProvider
from metis.models.provider import LLMProvider, create_provider
from metis.schemas.task_spec import TaskSpec


class DistributedCoordinator:
    """
    Orchestrates heterogeneous agents across a mesh of worker nodes.

    The coordinator can run anywhere; agents communicate via secure RPC
    rather than direct model coupling.
    """

    def __init__(self, config: RuntimeConfig, registry: NodeRegistry):
        self.config = config
        self.registry = registry
        self._providers: Dict[str, LLMProvider] = {}

    def provider_for_slot(self, slot: ModelSlot) -> LLMProvider:
        cache_key = f"{slot.name}:{slot.node_id or ''}:{slot.model}"
        if cache_key in self._providers:
            return self._providers[cache_key]

        if self.config.distributed and self.registry:
            node = self.registry.resolve_for_slot(
                node_id=slot.node_id,
                role=slot.name,
                model=slot.model,
            )
            if node:
                prov = RemoteLLMProvider(
                    slot,
                    node,
                    registry=self.registry,
                    security=self.registry.cluster.security,
                )
                self._providers[cache_key] = prov
                return prov

        prov = create_provider(slot, config=self.config)
        self._providers[cache_key] = prov
        return prov

    async def dispatch_parallel(
        self,
        tasks: List[Dict[str, Any]],
    ) -> List[Any]:
        """
        Dispatch multiple agent calls to different nodes in parallel.

        Each task dict: {slot: ModelSlot, system: str, user: str, fn?: callable}
        """
        coros = []
        for task in tasks:
            slot: ModelSlot = task["slot"]
            prov = self.provider_for_slot(slot)
            if "fn" in task:
                coros.append(task["fn"](prov))
            else:
                coros.append(
                    prov.complete_text(
                        task["system"],
                        task["user"],
                        temperature=task.get("temperature", 0.3),
                    )
                )
        return await asyncio.gather(*coros, return_exceptions=True)

    async def run_moa_layer(
        self,
        task_spec: TaskSpec,
        user_query: str,
        *,
        feedback: str = "",
    ) -> str:
        """Run layered MoA with proposers on different nodes."""
        from metis.agents.moa import (
            AGGREGATOR_SYSTEM,
            PROPOSER_ROLES,
            REFINER_SYSTEM,
            _build_moa_prompt,
        )

        slots = self.config.resolved_council_models()
        base = self.config.base_slot()

        layer1_tasks = []
        for i, (role_name, role_desc) in enumerate(PROPOSER_ROLES):
            slot = slots[i % len(slots)]
            prov = self.provider_for_slot(slot)
            system = f"You are the {role_name} proposer. {role_desc}"
            user = _build_moa_prompt(task_spec, user_query, feedback)
            layer1_tasks.append(prov.complete_text(system, user, temperature=0.7))

        layer1_outputs = await asyncio.gather(*layer1_tasks, return_exceptions=True)

        layer1_block = "\n\n".join(
            f"--- Proposal {i + 1} ({PROPOSER_ROLES[i][0]}) ---\n{out if not isinstance(out, Exception) else f'[error: {type(out).__name__}]'}"
            for i, out in enumerate(layer1_outputs)
        )
        refiner_slot = slots[min(1, len(slots) - 1)]
        refiner = self.provider_for_slot(refiner_slot)
        layer2_input = f"TaskSpec:\n{task_spec.to_context()}\n\nProposals:\n{layer1_block}"
        layer2_output = await refiner.complete_text(REFINER_SYSTEM, layer2_input, temperature=0.5)

        aggregator = self.provider_for_slot(base)
        layer3_input = (
            f"TaskSpec:\n{task_spec.to_context()}\n\n"
            f"Original query: {user_query}\n\n"
            f"Refined synthesis:\n{layer2_output}"
        )
        if feedback:
            layer3_input += f"\n\nJudge feedback (fix these issues):\n{feedback}"

        return await aggregator.complete_text(AGGREGATOR_SYSTEM, layer3_input, temperature=0.3)

    async def ensure_cluster_ready(self) -> None:
        """Health-check all nodes before a distributed run."""
        await self.registry.check_health()
        healthy = self.registry.healthy_nodes()
        if not healthy and self.registry.all_nodes():
            raise RuntimeError("No healthy nodes in cluster")

    def node_assignments(self) -> Dict[str, str]:
        """Map council slot names to resolved node URLs (for diagnostics)."""
        out: Dict[str, str] = {}
        for slot in self.config.resolved_council_models():
            node = self.registry.resolve_for_slot(
                node_id=slot.node_id,
                role=slot.name,
                model=slot.model,
            )
            out[slot.name] = node.url if node else "local"
        return out

    async def aclose(self) -> None:
        for prov in self._providers.values():
            if hasattr(prov, "aclose"):
                await prov.aclose()
