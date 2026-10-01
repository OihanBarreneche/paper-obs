"""The one factory: the key in one place, and the provider's own shapes on the wire.

Both structural promises of the provider table are checked here — the reasoning body is the
provider's and never DeepSeek's, and a row's attribution headers reach the client — by
replacing LangChain's client with a recorder, so nothing leaves the process.
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("langchain_openai")

from paper_obs.llm import chat  # noqa: E402
from paper_obs.llm.models import ModelConfig  # noqa: E402


class _Recorder:
    """Stands in for ChatOpenAI and keeps the keywords it was built with."""

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> type[_Recorder]:
    monkeypatch.setattr(chat, "ChatOpenAI", _Recorder)
    return _Recorder


def test_a_reasoning_effort_is_spelled_by_the_provider(recorder: type[_Recorder]) -> None:
    """DeepSeek's thinking switch must not be handed to an endpoint that never declared it."""
    deepseek = chat.chat_model(
        ModelConfig(provider="deepseek", model="deepseek-flash", reasoning_effort="high"),
        api_key="a-key",
    )
    assert deepseek.kwargs["extra_body"] == {
        "thinking": {"type": "enabled"},
        "reasoning_effort": "high",
    }

    gemini = chat.chat_model(
        ModelConfig(provider="gemini", model="gemini-3.8-flash", reasoning_effort="high"),
        api_key="a-key",
    )
    assert gemini.kwargs["extra_body"] == {"reasoning_effort": "high"}

    xai = chat.chat_model(
        ModelConfig(provider="xai", model="grok-4.7", reasoning_effort="low"), api_key="a-key"
    )
    assert xai.kwargs["extra_body"] == {"reasoning_effort": "low"}

    # Groq refuses an unknown field with a 400, so an effort it cannot take is not sent.
    groq = chat.chat_model(
        ModelConfig(provider="groq", model="openai/gpt-oss-120b", reasoning_effort="high"),
        api_key="a-key",
    )
    assert groq.kwargs["extra_body"] is None

    # No effort asked for: DeepSeek still needs its thinking turned off, nobody else speaks.
    plain = chat.chat_model(ModelConfig(provider="openai", model="gpt-6-luna"), api_key="a-key")
    assert plain.kwargs["extra_body"] is None


def test_deepseek_still_turns_thinking_off_when_no_effort_is_asked(
    recorder: type[_Recorder],
) -> None:
    model = chat.chat_model(ModelConfig(provider="deepseek", model="deepseek-flash"), api_key="a-key")
    assert model.kwargs["extra_body"] == {"thinking": {"type": "disabled"}}


def test_an_endpoint_that_refuses_temperature_is_never_sent_one(
    recorder: type[_Recorder],
) -> None:
    """OpenAI's reasoning models answer 400 for the field, and LangChain only knows o1/gpt-5."""
    openai = chat.chat_model(
        ModelConfig(provider="openai", model="gpt-6-luna", temperature=0.0), api_key="a-key"
    )
    assert openai.kwargs["temperature"] is None

    deepseek = chat.chat_model(
        ModelConfig(provider="deepseek", model="deepseek-flash", temperature=0.0), api_key="a-key"
    )
    assert deepseek.kwargs["temperature"] == 0.0


def test_attribution_headers_are_off_for_every_row_but_openrouter(
    recorder: type[_Recorder],
) -> None:
    """extra_headers is empty by default, so only the row that opts in sends anything."""
    openrouter = chat.chat_model(ModelConfig(provider="openrouter", model="openai/gpt-6-luna"), api_key="a-key")
    assert openrouter.kwargs["default_headers"] == {"X-OpenRouter-Title": "Paper Obs"}

    for name in ("openai", "gemini", "xai", "mistral", "groq", "together", "ollama", "ollama-cloud"):
        model = chat.chat_model(ModelConfig(provider=name, model="a-model"), api_key="a-key")
        assert model.kwargs["default_headers"] is None, name
