"""Configuration for metis."""

from __future__ import annotations

from metis.env_compat import migrate_legacy_env

migrate_legacy_env()

from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from metis.economy.config import EconomyConfig
from metis.knowledge.config import KnowledgeConfig
from metis.mcp.config import MCPServerConfig
from metis.observability.config import ObservabilityConfig
from metis.security.ratelimit import RateLimitConfig


class ProviderKind(str, Enum):
    OPENAI_COMPAT = "openai_compat"
    OLLAMA = "ollama"
    ANTHROPIC = "anthropic"
    MOCK = "mock"  # test-only — blocked unless allow_test_provider=true


class ModelSlot(BaseModel):
    name: str
    provider: ProviderKind = ProviderKind.OPENAI_COMPAT
    model: str
    base_url: str = "http://localhost:11434/v1"
    api_key: str = "ollama"
    temperature: float = 0.7
    max_tokens: int = 4096
    node_id: Optional[str] = None
    supports_vision: Optional[bool] = None  # None → auto-detect from model name
    extra_headers: dict = {}  # extra HTTP headers (e.g. OpenRouter HTTP-Referer / X-Title)


class ModuleSlotConfig(BaseModel):
    """Per-brain-module LLM endpoint configuration."""

    provider: Optional[ProviderKind] = None
    model: Optional[str] = None
    base_url: Optional[str] = None
    api_key_env: Optional[str] = None
    api_key: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    node_id: Optional[str] = None
    supports_vision: Optional[bool] = None
    extra_headers: Optional[dict] = None


class RouteMode(str, Enum):
    FAST = "fast"
    THINKING = "thinking"
    AGENT = "agent"
    COUNCIL = "council"


class DGPDConfig(BaseModel):
    """Disagreement-Gated Pipeline Depth — skip expensive layers on agreement."""

    enabled: bool = True
    agreement_threshold: float = 0.85
    force_full_depth_keywords: List[str] = Field(
        default_factory=lambda: [
            "delete",
            "execute",
            "password",
            "api key",
            "secret",
            "production",
            "deploy",
        ]
    )


class SecurityConfig(BaseModel):
    max_user_input_chars: int = 100_000
    max_tool_output_chars: int = 50_000
    max_request_body_bytes: int = 512_000
    enforce_injection_scan: bool = True
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)
    cors_origins: List[str] = Field(default_factory=list)
    mtls_cert_path: Optional[str] = None
    mtls_key_path: Optional[str] = None
    mtls_ca_path: Optional[str] = None


class RuntimeConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="METIS_", env_file=".env", extra="ignore")

    production: bool = False
    allow_test_provider: bool = False

    base_model: str = "qwen3:8b"
    base_url: str = "http://localhost:11434/v1"
    api_key: str = "ollama"
    provider: ProviderKind = ProviderKind.OLLAMA

    default_route: RouteMode = RouteMode.COUNCIL
    thinking_samples: int = 3
    thinking_temperature: float = 0.8
    max_agent_iterations: int = 5
    max_verify_retries: int = 3
    enable_grounded_verify: bool = True  # execute answer code to ground verify_score
    enable_multimodal: bool = True       # pass images to a vision-capable slot when present
    max_images: int = 5                  # hard cap on images accepted per request
    vision_timeout_seconds: float = 30.0  # hard cap on the perception call (fail over to text)
    vision_retries: int = 3               # retries within the budget (free vision endpoints are flaky)
    identity: str = ""                    # operator self-knowledge prepended to EVERY system prompt
    #                                       (who Metis is, its ecosystem, services, tools). "" → standalone,
    #                                       no injection. Set via METIS_IDENTITY env or the `identity:` YAML key.
    confidence_threshold: float = 0.7
    confidence_hard_floor: float = 0.35
    enforce_confidence_gate: bool = True

    council_models: List[ModelSlot] = Field(default_factory=list)
    modules: Dict[str, ModuleSlotConfig] = Field(default_factory=dict)
    enforce_heterogeneous_agents: bool = False
    min_unique_council_models: int = 2

    # Capability gate — keep a randomly-plugged-in weak model from dragging the council down.
    # High-leverage roles (aggregator/verifier/synthesizer) go to the strongest configured
    # model; models below the floor lose their vote as proposers. No-op for single-model
    # setups. See metis/agents/capability.py and docs/benchmarks/.
    enforce_capability_gate: bool = True
    council_capability_floor: float = 60.0     # below this a model can't be a proposer/parser
    min_aggregator_capability: float = 75.0    # advisory: warn if the strongest is still below this
    capability_file: Path = Path("data/capability.json")  # measured scores from `metis calibrate`

    memory_dir: Path = Path("data/memory")
    enable_long_term_memory: bool = True
    rag_top_k: int = 5

    enable_code_interpreter: bool = True
    enable_web_search: bool = True
    web_search_url: str = "https://html.duckduckgo.com/html/"
    code_timeout_seconds: int = 10
    sandbox_use_subprocess: bool = True

    enable_mcp_tools: bool = False
    mcp_servers: List[MCPServerConfig] = Field(default_factory=list)
    mcp_ecosystem_presets: List[str] = Field(default_factory=list)
    enable_ecosystem_invoke: bool = False  # let the agent pay-per-call AIMarket hub capabilities

    dgpd: DGPDConfig = Field(default_factory=DGPDConfig)
    economy: EconomyConfig = Field(default_factory=EconomyConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
    knowledge: KnowledgeConfig = Field(default_factory=KnowledgeConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)

    escalate_model: Optional[str] = None
    escalate_url: Optional[str] = None

    distributed: bool = False
    cluster_config: Optional[Path] = None

    def model_post_init(self, __context: Any) -> None:
        from metis.security.ssrf import validate_url
        self.web_search_url = validate_url(self.web_search_url)
        if self.production and not self.api_key_env_set():
            pass  # api_key from env in production via METIS_API_KEY

    def api_key_env_set(self) -> bool:
        import os
        return bool(
            os.environ.get("METIS_API_KEY")
            or os.environ.get("SUPERBRAIN_API_KEY")
            or os.environ.get("COGNITIVE_API_KEY")
        )

    @classmethod
    def from_yaml(cls, path: str | Path) -> RuntimeConfig:
        with open(path) as f:
            data: dict[str, Any] = yaml.safe_load(f) or {}
        dgpd = data.get("dgpd", {})
        if "enable_dgpd" in data:
            dgpd.setdefault("enabled", data.pop("enable_dgpd"))
        if "dgpd_agreement_threshold" in data:
            dgpd.setdefault("agreement_threshold", data.pop("dgpd_agreement_threshold"))
        if dgpd:
            data["dgpd"] = dgpd
        reliability = data.get("reliability")
        if reliability:
            data.setdefault("observability", {})["reliability"] = reliability
            data.pop("reliability", None)
        return cls(**data)

    def resolved_mcp_servers(self) -> List[MCPServerConfig]:
        from metis.mcp.discovery import ecosystem_presets
        servers = list(self.mcp_servers)
        if self.mcp_ecosystem_presets:
            servers.extend(ecosystem_presets([p for p in self.mcp_ecosystem_presets if p]))
        return servers

    def resolved_council_models(self) -> List[ModelSlot]:
        """Resolve council slots; enforce >=min_unique_council_models (Yang et al. 2026)."""
        from metis.agents.diversity import check_council_diversity, diversify_temperatures
        from metis.modules.registry import COUNCIL_ROLES, ModuleRegistry

        registry = ModuleRegistry(self)
        if self.modules or self.council_models:
            slots = [registry.resolve_slot(role) for role in COUNCIL_ROLES]
        else:
            slots = [
                ModelSlot(name="parser_a", provider=self.provider, model=self.base_model, base_url=self.base_url, api_key=self.api_key, temperature=0.5),
                ModelSlot(name="parser_b", provider=self.provider, model=self.base_model, base_url=self.base_url, api_key=self.api_key, temperature=0.7),
                ModelSlot(name="parser_c", provider=self.provider, model=self.base_model, base_url=self.base_url, api_key=self.api_key, temperature=0.9),
                ModelSlot(name="red_team", provider=self.provider, model=self.base_model, base_url=self.base_url, api_key=self.api_key, temperature=0.6),
                ModelSlot(name="synthesizer", provider=self.provider, model=self.base_model, base_url=self.base_url, api_key=self.api_key, temperature=0.3),
            ]
        check_council_diversity(slots, enforce=self.enforce_heterogeneous_agents, min_unique_models=self.min_unique_council_models)
        if not self.enforce_heterogeneous_agents:
            slots = diversify_temperatures(slots)
        return slots

    def base_slot(self) -> ModelSlot:
        return ModelSlot(name="base", provider=self.provider, model=self.base_model, base_url=self.base_url, api_key=self.api_key)
