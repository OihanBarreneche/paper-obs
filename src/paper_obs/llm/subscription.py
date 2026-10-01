"""A chat model answered by a subscription CLI on this machine: Claude Code or Codex.

Many people pay a monthly subscription rather than API credit. This adapter lets a workflow
run on one: each model call becomes one non-interactive CLI call (``claude -p``,
``codex exec``) with the CLI's own tools turned off where the CLI allows it. The CLI does not
receive the lab's tools as tools. The conversation and the tool schemas are written into the
prompt, and the CLI must answer JSON matching :data:`REPLY_SCHEMA` (a text and a list of tool
calls), which becomes the ``AIMessage`` LangChain expects. The agent loop, the tools and
structured output through ``ToolStrategy`` stay LangChain's.

This is a grey zone. A subscription is meant for interactive use, and its terms may not cover
driving it from a program. A call starts a process, so it is slower than an API. Tokens are
recorded, but no price: the subscription is paid by the month.

The executable is found on the ``PATH`` or named by ``PAPER_OBS_CLAUDE_CLI`` /
``PAPER_OBS_CODEX_CLI``, for example a Windows ``claude.exe`` reached from WSL.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import Field

#: The answer every call must give. Arguments travel as a JSON string, because a strict
#: schema (Codex's) cannot describe a free-form object.
REPLY_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["content", "tool_calls"],
    "properties": {
        "content": {"type": "string"},
        "tool_calls": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["name", "arguments"],
            "properties": {"name": {"type": "string"},
                           "arguments": {"type": "string", "description": "the arguments, a JSON object"}}}},
    },
}

PROTOCOL = """You are the model behind a program's chat API, not a coding assistant.
The conversation so far and the tools the program offers are given below. You cannot run
anything yourself: to use a tool, put it in tool_calls with its arguments as a JSON object
encoded in a string; the program runs it and shows you the result in the next message.
To answer without a tool, leave tool_calls empty. Reply only with the JSON the schema asks for."""

#: Where each CLI may be named explicitly.
EXECUTABLE_ENV = {"claude": "PAPER_OBS_CLAUDE_CLI", "codex": "PAPER_OBS_CODEX_CLI"}


class SubscriptionChat(BaseChatModel):
    """One model reached through ``claude -p`` or ``codex exec``."""

    cli: str
    model: str = ""
    reasoning_effort: str | None = None
    timeout: float = 900.0
    tools: list[dict[str, Any]] = Field(default_factory=list)
    must_call: bool = False

    @property
    def _llm_type(self) -> str:
        return f"{self.cli}-subscription"

    def bind_tools(self, tools: Any, *, tool_choice: Any = None, **_: Any) -> "SubscriptionChat":
        """Remember the tools; they are described in each prompt rather than sent as tools."""
        return self.model_copy(update={"tools": [convert_to_openai_tool(tool) for tool in tools],
                                       "must_call": tool_choice not in (None, "auto", "none", False)})

    def _generate(self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None,
                  **_: Any) -> ChatResult:
        prompt = _transcript(messages, self.tools, self.must_call)
        reply, usage = (_ask_claude if self.cli == "claude" else _ask_codex)(self, prompt)
        calls, invalid = [], []
        for call in reply.get("tool_calls") or []:
            try:
                calls.append({"name": call["name"], "args": json.loads(call["arguments"] or "{}"),
                              "id": f"call_{uuid.uuid4().hex[:12]}", "type": "tool_call"})
            except (KeyError, TypeError, ValueError) as error:
                invalid.append({"name": call.get("name"), "args": call.get("arguments"), "id": None,
                                "error": str(error), "type": "invalid_tool_call"})
        message = AIMessage(content=reply.get("content") or "", tool_calls=calls, invalid_tool_calls=invalid,
                            usage_metadata=usage)
        return ChatResult(generations=[ChatGeneration(message=message)])


def executable(cli: str) -> str:
    """Return the CLI's path, or raise naming how to provide it."""
    named = os.environ.get(EXECUTABLE_ENV[cli])
    found = named or shutil.which(cli) or shutil.which(f"{cli}.exe")
    if not found:
        raise ValueError(f"{cli} was not found: install it and sign in, or set {EXECUTABLE_ENV[cli]} to its path")
    return found


def _transcript(messages: list[BaseMessage], tools: list[dict[str, Any]], must_call: bool) -> str:
    """The conversation as text, then the tools, as the CLI reads them."""
    parts = []
    for message in messages:
        text = message.content if isinstance(message.content, str) else "\n".join(
            block.get("text", "") for block in message.content if isinstance(block, dict))
        if isinstance(message, ToolMessage):
            parts.append(f"## Tool result ({message.name or 'tool'})\n{text}")
        elif isinstance(message, AIMessage):
            calls = [{"name": call["name"], "arguments": call["args"]} for call in message.tool_calls]
            parts.append(f"## Assistant\n{text}" + (f"\nTool calls: {json.dumps(calls)}" if calls else ""))
        else:
            parts.append(f"## {'System' if message.type == 'system' else 'User'}\n{text}")
    listed = [tool["function"] for tool in tools]
    parts.append("## Tools\n" + (json.dumps(listed, ensure_ascii=False) if listed else "none"))
    if must_call:
        parts.append("Call at least one tool in this answer.")
    return "\n\n".join(parts)


def _run(command: list[str], prompt: str, folder: str, timeout: float) -> str:
    completed = subprocess.run(command, input=prompt, capture_output=True, text=True, encoding="utf-8",
                               timeout=timeout, cwd=folder)
    if completed.returncode != 0:
        try:  # Claude Code explains a failure, such as an expired sign-in, in its JSON answer
            message = json.loads(completed.stdout).get("result")
        except (ValueError, AttributeError):
            message = None
        raise RuntimeError(f"{Path(command[0]).name} failed: {message or (completed.stderr or completed.stdout).strip()[:500]}")
    return completed.stdout


def _ask_claude(chat: SubscriptionChat, prompt: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """``claude -p`` with no tools, no session kept, and the reply schema as structured output."""
    command = [executable("claude"), "-p", "--output-format", "json", "--tools", "", "--no-session-persistence",
               "--strict-mcp-config", "--system-prompt", PROTOCOL, "--json-schema", json.dumps(REPLY_SCHEMA)]
    command += ["--model", chat.model] if chat.model else []
    command += ["--effort", chat.reasoning_effort] if chat.reasoning_effort else []
    # An empty working folder: no project instructions are discovered around the call.
    with tempfile.TemporaryDirectory() as folder:
        payload = json.loads(_run(command, prompt, folder, chat.timeout))
    if payload.get("is_error"):
        raise RuntimeError(f"claude answered an error: {payload.get('result')}")
    reply = payload.get("structured_output") or json.loads(payload.get("result") or "{}")
    used = payload.get("usage") or {}
    read, written = used.get("cache_read_input_tokens", 0), used.get("cache_creation_input_tokens", 0)
    tokens_in = used.get("input_tokens", 0) + read + written
    return reply, {"input_tokens": tokens_in, "output_tokens": used.get("output_tokens", 0),
                   "total_tokens": tokens_in + used.get("output_tokens", 0),
                   "input_token_details": {"cache_read": read, "cache_creation": written}}


def _ask_codex(chat: SubscriptionChat, prompt: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """``codex exec`` in a read-only sandbox on an empty folder, with the reply schema."""
    with tempfile.TemporaryDirectory() as folder:
        schema, answer = Path(folder, "reply.schema.json"), Path(folder, "reply.json")
        schema.write_text(json.dumps(REPLY_SCHEMA), encoding="utf-8")
        command = [executable("codex"), "exec", "--skip-git-repo-check", "--sandbox", "read-only", "--json",
                   "--output-schema", str(schema), "--output-last-message", str(answer)]
        command += ["--model", chat.model] if chat.model else []
        command += ["-c", f'model_reasoning_effort="{chat.reasoning_effort}"'] if chat.reasoning_effort else []
        events = _run(command + ["-"], f"{PROTOCOL}\n\n{prompt}", folder, chat.timeout)
        reply = json.loads(answer.read_text(encoding="utf-8"))
    used: dict[str, int] = {}
    for line in events.splitlines():
        event = json.loads(line) if line.startswith("{") else {}
        if event.get("type") == "turn.completed":
            used = event.get("usage") or {}
    tokens_in, tokens_out = used.get("input_tokens", 0), used.get("output_tokens", 0)
    return reply, {"input_tokens": tokens_in, "output_tokens": tokens_out, "total_tokens": tokens_in + tokens_out,
                   "input_token_details": {"cache_read": used.get("cached_input_tokens", 0)}}


__all__ = ["EXECUTABLE_ENV", "REPLY_SCHEMA", "SubscriptionChat", "executable"]
