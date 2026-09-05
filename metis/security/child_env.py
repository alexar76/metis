"""Scrub the environment handed to the code-interpreter subprocess.

METIS runs UNTRUSTED, model-emitted Python (see ``metis.tools.sandbox`` — the in-process
screen is defence-in-depth, not a boundary). The child used to inherit ``os.environ``
wholesale: the service's LLM provider keys, its Ed25519 signing seed, the hub/admin tokens,
and ``DOCKER_HOST``. A screen escape — three were demonstrated in the 2026-09 re-audit — then
read all of it straight out of the environment. Scrubbing the child's environment turns "RCE
that walks off with every credential the service holds" into "code running in an ephemeral
worker that holds none".

This is a self-contained copy of the monorepo's ``core.child_env`` idea rather than an import
of it: METIS is published as the standalone ``aimarket-metis`` wheel, which does not ship
``core``. The two must stay aligned by hand.

Denylist by design: a secret added to the deployment next month must be dropped by DEFAULT,
never opted in by whoever remembers to edit this file. What survives is only what a Python
child needs to start and import METIS — PATH, PYTHONPATH, HOME, the venv markers.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

#: Exact names dropped even though they carry no give-away substring.
_DROP_EXACT: frozenset[str] = frozenset({
    "DOCKER_HOST",
    "DOCKER_CERT_PATH",
    "DOCKER_TLS_VERIFY",
    "DOCKER_CONFIG",
    "SSH_AUTH_SOCK",
    "GIT_ASKPASS",
    "DATABASE_URL",
    "REDIS_URL",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
})

#: Substring match against the upper-cased variable name. Deliberately broad.
_DROP_SUBSTRINGS: tuple[str, ...] = (
    "SECRET", "TOKEN", "PASSWORD", "PASSWD", "APIKEY", "API_KEY", "_KEY", "KEYFILE",
    "PRIVKEY", "PRIVATE", "CREDENTIAL", "MNEMONIC", "SEED", "SIGNING", "WEBHOOK",
    "SENTRY_DSN", "AWS_", "VERCEL", "GITHUB", "GH_PAT", "GITEA", "OPENROUTER",
    "DEEPSEEK", "ANTHROPIC", "OPENAI", "OLLAMA_KEY", "TELEGRAM", "DISCORD", "SMTP",
    "TWILIO", "STRIPE", "INFURA", "ALCHEMY", "RPC_URL", "METIS_ADMIN", "OPERATOR",
)


def is_sensitive(name: str) -> bool:
    """Would exposing this variable to untrusted code leak a credential or a capability?"""
    upper = name.upper()
    if upper in _DROP_EXACT:
        return True
    return any(fragment in upper for fragment in _DROP_SUBSTRINGS)


def scrub_child_env(source: Mapping[str, str], *, keep: Iterable[str] = ()) -> dict[str, str]:
    """A copy of ``source`` with everything sensitive removed.

    ``keep`` re-admits specific names by EXACT match, for the rare child that genuinely needs
    one — pass it at the call site so the exception is visible and reviewable.
    """
    keep_set = set(keep)
    return {
        name: value
        for name, value in source.items()
        if name in keep_set or not is_sensitive(name)
    }
