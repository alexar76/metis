"""Map legacy env var prefixes to METIS_* before settings load."""

from __future__ import annotations

import os

_LEGACY_PREFIXES = ("SUPERBRAIN_", "COGNITIVE_")


def migrate_legacy_env() -> None:
    """Copy SUPERBRAIN_* and COGNITIVE_* into METIS_* when METIS_* is unset."""
    for key, value in list(os.environ.items()):
        for prefix in _LEGACY_PREFIXES:
            if not key.startswith(prefix):
                continue
            metis_key = "METIS_" + key[len(prefix) :]
            if metis_key not in os.environ:
                os.environ[metis_key] = value
            break
