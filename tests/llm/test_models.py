"""The model layer: the provider table, the configuration, and the role set.

These are contract tests: what a caller may rely on, never how it is implemented.
The one property that matters most is negative — a configuration is written to a run
file and returned by the API, so it must not be able to carry a secret.
"""

from __future__ import annotations

import json

import pytest

from paper_obs.llm import (
    ENVIRONMENT_KEY,
    PROVIDERS,
    ModelConfig,
    catalogue,
    key_present,
    provider,
)
from paper_obs.llm.models import DEFAULT_PROVIDER
from paper_obs.llm.redaction import redact


def test_the_default_provider_is_known_and_needs_a_key() -> None:
    assert DEFAULT_PROVIDER in PROVIDERS
    assert PROVIDERS[DEFAULT_PROVIDER].needs_key


def test_a_provider_names_a_variable_and_never_a_key() -> None:
    for item in PROVIDERS.values():
        assert item.api_key_env == item.api_key_env.upper()
        assert not item.api_key_env.startswith("sk-")


def test_a_configuration_cannot_hold_a_secret() -> None:
    document = ModelConfig(provider="deepseek", model="deepseek-chat").to_dict()
    assert set(document) == {
        "provider",
        "model",
        "base_url",
        "temperature",
        "max_tokens",
        "reasoning_effort",
        "cost_per_million_in",
        "cost_per_million_out",
        "cost_per_million_cached",
    }


def test_the_endpoint_falls_back_and_refuses_to_be_empty() -> None:
    assert ModelConfig(provider="deepseek").endpoint == "https://api.deepseek.com"
    assert ModelConfig(provider="deepseek", base_url="https://proxy/").endpoint == "https://proxy"
    with pytest.raises(ValueError):
        ModelConfig(provider="custom").endpoint


def test_a_configuration_round_trips_through_its_document() -> None:
    config = ModelConfig(provider="ollama", model="qwen2.5", temperature=0.7, max_tokens=512)
    document = config.to_dict()
    assert ModelConfig.from_dict(document).to_dict() == document


def test_an_unknown_provider_or_a_number_out_of_range_is_refused() -> None:
    with pytest.raises(KeyError):
        ModelConfig(provider="nope")
    with pytest.raises(KeyError):
        provider("nope")
    with pytest.raises(ValueError):
        ModelConfig(temperature=3.0)
    with pytest.raises(ValueError):
        ModelConfig(max_tokens=0)
    with pytest.raises(ValueError):
        ModelConfig(reasoning_effort="extreme")


def test_the_key_report_names_variables_and_never_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENVIRONMENT_KEY, raising=False)
    monkeypatch.delenv(PROVIDERS["deepseek"].api_key_env, raising=False)
    report = key_present()
    assert report["environment_key"] == ENVIRONMENT_KEY
    assert report["environment_key_set"] is False
    assert set(report["providers"]) == set(PROVIDERS)

    monkeypatch.setenv(PROVIDERS["deepseek"].api_key_env, "a-secret-value")
    after = key_present()
    assert after["providers"]["deepseek"] is True
    assert "a-secret-value" not in json.dumps(after)


def test_the_key_report_is_only_booleans_and_variable_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Key-shaped or not, an environment value is never part of the answer."""
    monkeypatch.delenv(ENVIRONMENT_KEY, raising=False)
    monkeypatch.setenv(PROVIDERS["openai"].api_key_env, "sk-should-never-be-returned-0002")
    report = key_present()
    assert report["environment_key"] == ENVIRONMENT_KEY
    assert isinstance(report["environment_key_set"], bool)
    assert all(isinstance(name, str) for name in report["providers"])
    assert all(isinstance(present, bool) for present in report["providers"].values())
    assert report["providers"]["openai"] is True
    text = json.dumps(report)
    assert "sk-should-never-be-returned-0002" not in text
    # The whole report is already redaction-clean: nothing in it is key-shaped.
    assert redact(text) == text


def test_the_catalogue_lists_every_provider_once_in_order() -> None:
    listed = catalogue()
    assert [item["name"] for item in listed] == sorted(PROVIDERS)
    assert len(listed) == len(PROVIDERS)
    assert all("needs_key" in item for item in listed)


def test_the_table_ships_every_endpoint_the_lab_promises() -> None:
    """The list of providers is a contract the interface and the documentation share."""
    assert set(PROVIDERS) == {
        "deepseek", "openai", "anthropic", "openrouter", "gemini", "xai",
        "mistral", "groq", "together", "ollama", "ollama-cloud", "claude-code", "codex", "custom",
    }
    for name, row in PROVIDERS.items():
        assert row.name == name
        assert row.note.strip(), name
    # The compatibility layers keep the trailing path their endpoint requires, and the
    # aggregator points at the host that is not deprecated.
    assert PROVIDERS["anthropic"].base_url == "https://api.anthropic.com/v1/"
    assert PROVIDERS["gemini"].base_url.endswith("/openai/")
    assert PROVIDERS["together"].base_url.startswith("https://api.together.ai/")
    assert "together.xyz" not in PROVIDERS["together"].base_url
    assert PROVIDERS["ollama"].needs_key is False
    assert PROVIDERS["ollama-cloud"].needs_key is True


def test_no_provider_row_carries_a_key_shaped_value() -> None:
    """Adding a row must not be a way to smuggle a key into a public answer."""
    for item in catalogue():
        text = json.dumps(item, ensure_ascii=False)
        assert redact(text) == text, f"provider {item['name']!r} carries a key-shaped value"
        assert item["api_key_env"] == item["api_key_env"].upper()
        assert not item["api_key_env"].startswith("sk-")
