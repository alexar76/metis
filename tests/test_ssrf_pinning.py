import socket

import httpx
import pytest

from metis.security import ssrf


def _dns(address):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]


@pytest.mark.asyncio
async def test_transport_dials_validated_ip_preserving_host_and_tls_name(monkeypatch):
    calls = []
    lookups = []

    def resolve(host, *args, **kwargs):
        lookups.append(host)
        # A third lookup during the real connection would now rebind locally.
        return _dns("93.184.216.34" if len(lookups) <= 2 else "127.0.0.1")

    async def handle(request):
        calls.append(request)
        return httpx.Response(200, text="public result")

    real_client = httpx.AsyncClient
    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    monkeypatch.setattr(ssrf.httpx, "AsyncClient", lambda **kwargs:
                        real_client(transport=httpx.MockTransport(handle), **kwargs))
    response = await ssrf.safe_get("https://search.example/result")
    assert response.text == "public result"
    assert calls[0].url.host == "93.184.216.34"
    assert calls[0].headers["Host"] == "search.example"
    assert calls[0].extensions["sni_hostname"] == "search.example"
    assert len(lookups) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("rebound", ["127.0.0.1", "100.64.0.1", "224.0.0.1"])
async def test_rebinding_between_validation_and_pinning_is_refused(monkeypatch, rebound):
    answers = iter(("93.184.216.34", rebound))
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: _dns(next(answers)))
    with pytest.raises(ValueError, match="non-public"):
        await ssrf.safe_get("https://search.example/result")


@pytest.mark.asyncio
async def test_redirect_uses_original_hostname_and_drops_cross_origin_credentials(monkeypatch):
    requests = []
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: _dns("93.184.216.34"))

    async def handle(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(302, headers={"Location": "/next"})
        if len(requests) == 2:
            return httpx.Response(302, headers={"Location": "https://other.example/final"})
        return httpx.Response(200, text="done")

    real_client = httpx.AsyncClient
    monkeypatch.setattr(ssrf.httpx, "AsyncClient", lambda **kwargs:
                        real_client(transport=httpx.MockTransport(handle), **kwargs))
    await ssrf.safe_get("https://search.example/start", headers={"Authorization": "Bearer local-test",
                        "X-Future-Credential": "local-test", "Accept": "text/html"})
    assert requests[1].headers["Host"] == "search.example"
    assert requests[1].headers["Authorization"] == "Bearer local-test"
    assert requests[2].headers["Host"] == "other.example"
    assert "Authorization" not in requests[2].headers
    assert "X-Future-Credential" not in requests[2].headers


@pytest.mark.asyncio
async def test_post_preserving_cross_origin_redirect_is_refused(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: _dns("93.184.216.34"))
    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request:
                                   httpx.Response(307, headers={"Location": "https://other.example/"}))
    monkeypatch.setattr(ssrf.httpx, "AsyncClient", lambda **kwargs: real_client(transport=transport, **kwargs))
    with pytest.raises(ValueError, match="another origin"):
        await ssrf.safe_post("https://search.example/", data={"private-query": "local test"})
