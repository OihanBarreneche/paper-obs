"""Subscription CLIs as chat models: the reply contract, checked against stand-in executables."""

from __future__ import annotations

import json
import sys

import pytest

pytest.importorskip("langchain")

from langchain.agents import create_agent  # noqa: E402
from langchain_core.tools import tool  # noqa: E402

from paper_obs.llm.chat import chat_model  # noqa: E402
from paper_obs.llm.models import PROVIDERS, ModelConfig  # noqa: E402
from paper_obs.llm.subscription import SubscriptionChat  # noqa: E402

#: A stand-in for `claude -p`: it asks for the tool once, then answers once it sees the result.
FAKE_CLAUDE = """
import json, sys
prompt = sys.stdin.read()
seen = "## Tool result" in prompt and "Measured 4" in prompt
reply = {"content": "the side is 4" if seen else "",
         "tool_calls": [] if seen else [{"name": "measure", "arguments": json.dumps({"side": 2})}]}
print(json.dumps({"type": "result", "is_error": False, "result": "", "structured_output": reply,
                  "usage": {"input_tokens": 10, "cache_read_input_tokens": 5, "output_tokens": 3}}))
"""

#: A stand-in for `codex exec`: the reply goes to --output-last-message, the usage to JSON lines.
FAKE_CODEX = """
import json, sys
sys.stdin.read()
path = sys.argv[sys.argv.index("--output-last-message") + 1]
open(path, "w").write(json.dumps({"content": "", "tool_calls": [{"name": "measure", "arguments": "{\\"side\\": 3}"}]}))
print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 7, "cached_input_tokens": 2, "output_tokens": 1}}))
"""


@tool
def measure(side: float) -> str:
    """Measure a square of the given side."""
    return f"Measured {side * side:g}"


def _stand_in(tmp_path, monkeypatch, name: str, body: str) -> None:
    script = tmp_path / name
    script.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
    script.chmod(0o755)
    monkeypatch.setenv(f"PAPER_OBS_{name.upper()}_CLI", str(script))


def test_a_subscription_provider_needs_no_key_and_lists_no_price() -> None:
    row = PROVIDERS["claude-code"].to_dict()
    assert row["subscription"] and not row["needs_key"] and not row["accepts_temperature"]
    assert isinstance(chat_model(ModelConfig(provider="claude-code", model="sonnet")), SubscriptionChat)


def test_an_agent_runs_its_tool_loop_through_claude_code(tmp_path, monkeypatch) -> None:
    _stand_in(tmp_path, monkeypatch, "claude", FAKE_CLAUDE)
    agent = create_agent(chat_model(ModelConfig(provider="claude-code", model="sonnet")), tools=[measure])
    messages = agent.invoke({"messages": [("user", "How large is a square of side 2?")]})["messages"]
    assert [message.type for message in messages] == ["human", "ai", "tool", "ai"]
    assert messages[1].tool_calls[0]["args"] == {"side": 2}
    assert messages[-1].content == "the side is 4"
    assert messages[1].usage_metadata["input_tokens"] == 15
    assert messages[1].usage_metadata["input_token_details"]["cache_read"] == 5


def test_codex_answers_tool_calls_and_usage(tmp_path, monkeypatch) -> None:
    _stand_in(tmp_path, monkeypatch, "codex", FAKE_CODEX)
    model = chat_model(ModelConfig(provider="codex", model="gpt-6-luna")).bind_tools([measure])
    reply = model.invoke("Measure a square of side 3.")
    assert reply.tool_calls[0]["name"] == "measure" and reply.tool_calls[0]["args"] == {"side": 3}
    assert reply.usage_metadata["output_tokens"] == 1


def test_a_missing_cli_is_named(monkeypatch) -> None:
    monkeypatch.setenv("PATH", "")
    monkeypatch.delenv("PAPER_OBS_CODEX_CLI", raising=False)
    with pytest.raises(ValueError, match="PAPER_OBS_CODEX_CLI"):
        SubscriptionChat(cli="codex").invoke("hello")


def test_the_reply_schema_is_strict() -> None:
    from paper_obs.llm.subscription import REPLY_SCHEMA

    item = REPLY_SCHEMA["properties"]["tool_calls"]["items"]
    assert REPLY_SCHEMA["additionalProperties"] is False and item["additionalProperties"] is False
    assert set(item["required"]) == set(item["properties"]) and json.dumps(REPLY_SCHEMA)
