"""Security audit logging — events without PII or prompt content."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("metis.security.audit")


def log_security_event(
    event: str,
    *,
    severity: str = "info",
    source: str = "metis",
    details: Optional[Dict[str, Any]] = None,
) -> None:
    entry: Dict[str, Any] = {
        "event": event,
        "severity": severity,
        "source": source,
    }
    if details:
        safe = {k: v for k, v in details.items() if k not in ("prompt", "content", "api_key", "secret")}
        entry["details"] = safe
    msg = json.dumps(entry, ensure_ascii=False, default=str)
    if severity == "critical":
        logger.critical(msg)
    elif severity == "warning":
        logger.warning(msg)
    else:
        logger.info(msg)
