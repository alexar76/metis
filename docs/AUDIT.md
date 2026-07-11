# Security & Quality Audit Report

**Date:** 2026-07-09  
**Scope:** Full codebase audit — security, connectivity, bugs, documentation  
**Test result:** 25 passed

## Summary

A comprehensive audit was conducted across security, connectivity, correctness, and documentation. Ten issues were identified and fixed. Trilingual documentation (EN/RU/ES) was added.

---

## Findings → Fixes

### Security

| # | Finding | Severity | Fix |
|---|---------|----------|-----|
| S1 | Code interpreter ran unrestricted Python via `subprocess -c` (os/subprocess escape) | **Critical** | Added `metis/tools/sandbox.py` with blocked imports and safe builtins; interpreter now runs via `python -m metis.tools.sandbox` in isolated subprocess |
| S2 | Web search tool had no SSRF protection on `search_url` | **High** | Added `metis/security.py` with `validate_public_http_url()` blocking private IPs, localhost, and non-HTTP(S) schemes; applied in `WebSearchTool` and `RuntimeConfig` |
| S3 | Bearer token comparison used `!=` (timing attack) | **Medium** | Changed to `hmac.compare_digest()` in `server.py` |
| S4 | `/metis/health` endpoint was unauthenticated | **Medium** | Health endpoint now calls `_check_auth()` when API key is configured |
| S5 | HMAC replay protection existed but was untested | **Low** | Verified implementation (5-minute window); added `test_hmac_replay_rejected` |
| S6 | RPC input had no size/count limits | **Medium** | Added Pydantic Field constraints on `InvokeRequest`/`MessagePayload` (max 100 messages, 100KB content, bounded temperature/tokens) |
| S7 | Verifier failed open on parse error (`passed=True`) | **Medium** | Changed to `passed=False, score=0.0` in `verify/critic.py` |

### Connectivity

| # | Finding | Severity | Fix |
|---|---------|----------|-----|
| C1 | `RemoteLLMProvider` had `aclose()` but no lifecycle hook in exoskeleton | **Low** | Documented as known limitation; `DistributedCoordinator.aclose()` exists for explicit cleanup |
| C2 | Health check and RPC error handling | **OK** | Already marks nodes unhealthy on failure; failover chain works (tested) |

### Bugs / Quality

| # | Finding | Severity | Fix |
|---|---------|----------|-----|
| B1 | Unused `subprocess` import in `tools/registry.py` | **Low** | Removed during sandbox refactor |
| B2 | Python 3.9 compatibility | **OK** | All modules use `from __future__ import annotations` |
| B3 | JSON brace escaping in `.format()` prompts | **OK** | All prompts use `{{` / `}}` correctly |
| B4 | Missing security test coverage | **Medium** | Added `tests/test_security.py` (10 tests) |

---

## Already Correct (no fix needed)

- API keys in cluster config use `api_key_env` (env vars only)
- HMAC signing uses `hmac.compare_digest` for signature verification
- TLS verify defaults to `true` in `SecuritySettings`
- Audit log excludes prompt content by default
- `asyncio.gather` in council uses `return_exceptions=True` with explicit error handling
- Registry health probes use `async with httpx.AsyncClient` (proper cleanup)
- Distributed failover tested and working

---

## Tests Added

```
tests/test_security.py
  test_hmac_replay_rejected
  test_hmac_fresh_request_accepted
  test_ssrf_blocks_localhost
  test_ssrf_blocks_private_ip
  test_ssrf_allows_public_url
  test_web_search_rejects_private_url
  test_sandbox_blocks_os_import
  test_sandbox_allows_math
  test_code_interpreter_sandboxed
  test_code_interpreter_blocks_subprocess
```

**Final count:** 25 tests, all passing.

---

## Documentation Created

| File | Language |
|------|----------|
| `docs/en/README.md` | English |
| `docs/ru/README.md` | Russian |
| `docs/es/README.md` | Spanish |
| `docs/en/DISTRIBUTED.md` | English |
| `docs/ru/DISTRIBUTED.md` | Russian |
| `docs/es/DISTRIBUTED.md` | Spanish |
| `docs/AUDIT.md` | English (this file) |

Root `README.md` updated as a short index linking to all language docs.

---

## Remaining Known Limitations

1. **Code interpreter sandbox** — Blocks dangerous imports but runs in a subprocess with the same user privileges; not full VM/container isolation. A determined attacker with allowed imports (e.g. `ctypes` is blocked but creative bytecode tricks may exist) could potentially escape. For production untrusted code, use an external sandbox (Docker, gVisor, WASM).

2. **Anonymous node access in dev** — When no `api_key_env` is set, nodes accept unauthenticated requests. This is intentional for local development but must not be used in production.

3. **HTTP client lifecycle** — `Metis` creates providers per-call without automatic `aclose()`. Long-running processes should call `DistributedCoordinator.aclose()` explicitly or rely on process exit.

4. **Web search redirect SSRF** — `follow_redirects=True` could theoretically follow a redirect to a private IP. Mitigation: validate final URL after redirect (not yet implemented).

5. **Prompt injection** — User queries flow into agent prompts without sanitization. This is inherent to LLM agent architectures; mitigation is model-level and policy-level, not code-level.

6. **Local `api_key` in config.yaml** — `RuntimeConfig.api_key` defaults to `"ollama"` for local Ollama compatibility. Production deployments should use env vars.

7. **No rate limiting** — Node server has no request rate limiting or IP allowlisting.

8. **Registry cache** — `_registry_cache` in `models/provider.py` persists across calls without TTL; acceptable for long-lived coordinators but not ideal for dynamic cluster reconfiguration.

---

## Recommendations for Production

1. Always set `api_key_env` on every node
2. Enable `tls_verify: true` and `request_signing: true`
3. Use HTTPS with valid certificates
4. Sync clocks (NTP) for HMAC timestamp validation
5. Run nodes behind a reverse proxy with rate limiting
6. Disable `enable_code_interpreter` for untrusted workloads
7. Monitor audit logs (`metis.distributed.audit` logger)
