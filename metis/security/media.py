"""Validation for image inputs — the multimodal attack surface.

Images are a prompt-injection and SSRF vector: a remote ``image_url`` can point
at internal metadata endpoints, and text baked into an image can try to hijack
the reasoning. This module enforces the *transport* half of the defense:

* remote URLs must be ``http(s)`` to a public host (SSRF-blocked via
  :func:`metis.security.ssrf.validate_url` — localhost / 169.254.169.254 /
  private ranges are rejected);
* inline ``data:`` URIs must be ``image/*`` and within a size cap;
* the total number of images is hard-capped.

The *semantic* half (treating what the vision model extracts as untrusted) is
handled where the observation is produced (canary-wrapped + sanitized).
"""

from __future__ import annotations

from typing import List

from metis.security.ssrf import validate_url

# ~8 MB of base64 ≈ 11M chars; cap a little above that per image.
_MAX_DATA_URI_CHARS = 12_000_000
_ALLOWED_DATA_PREFIXES = ("data:image/png", "data:image/jpeg", "data:image/jpg",
                          "data:image/webp", "data:image/gif")


def validate_image_url(url: str) -> str:
    """Return a safe image URL or raise ``ValueError``."""
    if not isinstance(url, str) or not url.strip():
        raise ValueError("empty image url")
    u = url.strip()
    if u.startswith("data:"):
        low = u[:32].lower()
        if not any(low.startswith(p) for p in _ALLOWED_DATA_PREFIXES):
            raise ValueError("data URI must be an image/* type")
        if len(u) > _MAX_DATA_URI_CHARS:
            raise ValueError("inline image too large")
        return u
    # Remote URL — SSRF-validate (blocks private/reserved hosts + bad schemes).
    return validate_url(u, allowed_schemes={"http", "https"})


def validate_images(urls: List[str], *, max_images: int = 5) -> List[str]:
    """Validate + de-dupe + cap a list of image URLs. Invalid entries are dropped."""
    out: List[str] = []
    seen = set()
    for raw in urls or []:
        try:
            safe = validate_image_url(raw)
        except ValueError:
            continue
        if safe in seen:
            continue
        seen.add(safe)
        out.append(safe)
        if len(out) >= max_images:
            break
    return out
