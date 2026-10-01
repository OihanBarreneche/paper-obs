"""Asking a provider which models it serves, without keeping the answer.

Model ids drift within weeks, so a hardcoded list can only ever be a suggestion. This is
the one path that asks the endpoint itself, with the caller's key, and returns the ids:
nothing is cached, nothing is written down, and the key travels in request headers only,
never in the URL, the answer or a log line.

Only the standard library is imported, so the API can offer discovery with the agents
extra absent.
"""

from __future__ import annotations

import json
import urllib.request
from typing import Any

from paper_obs.llm.models import PROVIDERS, ModelConfig

#: Seconds before a discovery request is abandoned. A catalogue answers quickly or not at
#: all, and a browser waiting on it should not wait longer than this.
TIMEOUT = 15.0

#: The client a request names. Cloudflare turns Python's default ("Python-urllib/3.x") away
#: with its error 1010 before the endpoint sees the key: Groq and Together did.
USER_AGENT = "paper-obs"


def _identifiers(payload: Any) -> list[str]:
    """Read a model list out of either spelling an OpenAI-compatible endpoint uses.

    The compatibility layer answers with "data": [{"id": ...}] and a native Google route
    with "models": [{"name": "models/..."}]; accepting both costs three lines and lets a
    caller point the route at a local server that imitates one of them.
    """
    items = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        items = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise ValueError("the endpoint answered without a model list")
    names: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("id") or item.get("name")
        if isinstance(name, str) and name:
            names.append(name.removeprefix("models/"))
    return sorted(set(names))


def models_for(config: ModelConfig, *, api_key: str, timeout: float = TIMEOUT) -> list[str]:
    """Return the model ids the endpoint serves, for one configuration and one key.

    Both credential headers travel together: every endpoint ignores the one it does not
    know, and Anthropic's native models route — the one reachable from its compatibility
    base URL — wants x-api-key rather than a bearer token.
    """
    if PROVIDERS[config.provider].local_cli is not None:
        return list(PROVIDERS[config.provider].models)  # a CLI lists nothing; any id may be typed
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        headers["x-api-key"] = api_key
    request = urllib.request.Request(f"{config.endpoint}/models", headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return _identifiers(payload)


__all__ = ["TIMEOUT", "USER_AGENT", "models_for"]
