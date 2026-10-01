"""Observable model replies and tool actions from a LangChain turn."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage, ToolMessage

from paper_obs.domain.serde import JSON


def tool_events(messages: list[Any], snapshots: dict[str, JSON], *, node_id: str = "turn") -> list[JSON]:
    """Pair tool requests with replies; attach candidates the engine actually produced.

    A reply is data the tool returned, never private model reasoning. The branch is the name
    of the agent that asked, where parallel agents are told apart by name.
    """
    events: list[JSON] = []
    by_call: dict[str, JSON] = {}
    for message_index, message in enumerate(messages):
        if isinstance(message, AIMessage):
            for call in message.tool_calls:
                event: JSON = {
                    "index": len(events),
                    "message_index": message_index,
                    "node_id": node_id,
                    "branch_id": message.name,
                    "tool": str(call["name"]),
                    "input": call.get("args", {}),
                    "result": None,
                    "candidate": None,
                    "status": "pending",
                }
                events.append(event)
                by_call[str(call["id"])] = event
        elif isinstance(message, ToolMessage):
            event = by_call.get(str(message.tool_call_id))
            if event is None:
                continue
            raw = message.content
            try:
                result = json.loads(raw) if isinstance(raw, str) else raw
            except (TypeError, ValueError):
                result = raw
            if isinstance(result, dict):
                candidate_id = result.get("candidate_id")
                if isinstance(candidate_id, str) and candidate_id in snapshots:
                    event["candidate"] = snapshots[candidate_id]
                # The candidate document already contains the same positions.
                result = {key: value for key, value in result.items() if key != "shapes"}
            event["result"] = result
            event["status"] = "error" if getattr(message, "status", "success") == "error" else "done"
    return events


def _text(value: Any) -> str:
    """Keep only provider-visible text, never an opaque or encrypted payload."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return _text(value.get("text", value.get("summary", "")))
    if isinstance(value, list):
        return "\n".join(part for item in value if (part := _text(item)))
    return ""


def model_messages(messages: list[Any]) -> list[JSON]:
    """Keep readable assistant text and reasoning explicitly returned by a provider.

    Each reply names the agent that wrote it, as a tool event does.
    """
    visible: list[JSON] = []
    for message_index, message in enumerate(messages):
        if not isinstance(message, AIMessage):
            continue
        blocks = message.content if isinstance(message.content, list) else []
        content = _text(message.content) if isinstance(message.content, str) else _text(
            [block for block in blocks if isinstance(block, str) or isinstance(block, dict) and block.get("type") == "text"]
        )
        reasoning = _text([
            block for block in blocks
            if isinstance(block, dict) and block.get("type") in {"reasoning", "reasoning_summary", "thinking"}
        ])
        extras = getattr(message, "additional_kwargs", {})
        if isinstance(extras, dict):
            reasoning = reasoning or _text(extras.get("reasoning_content", extras.get("reasoning_summary", "")))
        usage = getattr(message, "usage_metadata", None)
        visible.append({
            "index": len(visible),
            "message_index": message_index,
            "branch_id": message.name,
            "content": content,
            "reasoning": reasoning or None,
            "tool_calls": len(message.tool_calls),
            "tokens_in": None if not isinstance(usage, dict) else int(usage.get("input_tokens", 0) or 0),
            "tokens_out": None if not isinstance(usage, dict) else int(usage.get("output_tokens", 0) or 0),
        })
    return visible


__all__ = ["model_messages", "tool_events"]
