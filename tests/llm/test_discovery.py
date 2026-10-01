"""Discovery asks the endpoint itself and keeps the key out of the URL.

The route is the only place a caller's key is forwarded to a third party, so the request it
builds is part of the contract: the base URL is the provider's, the key travels in headers,
and the ids come back parsed from either spelling an endpoint uses.
"""

from __future__ import annotations

from typing import Any

import pytest

from paper_obs.llm import discovery
from paper_obs.llm.models import ModelConfig


class _Response:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *arguments: Any) -> bool:
        return False

    def read(self) -> bytes:
        return self.body


def _capture(monkeypatch: pytest.MonkeyPatch, body: bytes) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    def fake_urlopen(request: Any, timeout: float) -> _Response:
        seen["url"] = request.full_url
        seen["headers"] = {name.lower(): value for name, value in request.headers.items()}
        seen["timeout"] = timeout
        return _Response(body)

    monkeypatch.setattr(discovery.urllib.request, "urlopen", fake_urlopen)
    return seen


def test_discovery_reads_a_data_list_and_never_puts_the_key_in_the_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _capture(monkeypatch, b'{"data": [{"id": "gpt-b"}, {"id": "gpt-a"}]}')
    models = discovery.models_for(ModelConfig(provider="openai"), api_key="sk-the-key")
    assert models == ["gpt-a", "gpt-b"]
    assert seen["url"] == "https://api.openai.com/v1/models"
    assert "sk-the-key" not in seen["url"]
    assert seen["headers"]["authorization"] == "Bearer sk-the-key"
    # Python's default client name is refused by Cloudflare-fronted endpoints.
    assert seen["headers"]["user-agent"] == discovery.USER_AGENT


def test_discovery_reads_a_native_models_list_and_drops_its_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _capture(monkeypatch, b'{"models": [{"name": "models/gemini-x"}, {"name": "models/gemini-y"}]}')
    models = discovery.models_for(ModelConfig(provider="gemini"), api_key="a-key")
    assert models == ["gemini-x", "gemini-y"]
    assert seen["url"].endswith("/v1beta/openai/models")


def test_discovery_refuses_an_answer_without_a_list(monkeypatch: pytest.MonkeyPatch) -> None:
    _capture(monkeypatch, b'{"object": "list"}')
    with pytest.raises(ValueError):
        discovery.models_for(ModelConfig(provider="openai"), api_key="a-key")
