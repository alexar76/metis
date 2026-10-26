"""Metis — multi-agent reasoning orchestrator for any LLM."""

# Before the imports below: submodules read it (`from metis import __version__`).
__version__ = "0.2.3"

from metis.exoskeleton import Metis, ExoskeletonResult, CognitiveExoskeleton, Superbrain
from metis.config import RuntimeConfig

__all__ = ["Metis", "Superbrain", "CognitiveExoskeleton", "ExoskeletonResult", "RuntimeConfig"]
