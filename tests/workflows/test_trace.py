"""The run stores only text a model actually returned."""

from langchain_core.messages import AIMessage, ToolMessage

from paper_obs.workflows.trace import model_messages, tool_events


def test_model_messages_keep_visible_text_and_reasoning() -> None:
    messages = [
        AIMessage(content="", tool_calls=[{"id": "one", "name": "read_candidate", "args": {}}]),
        AIMessage(content=[{"type": "text", "text": "I will inspect the gap."}],
                  additional_kwargs={"reasoning_content": "The upper corner is free."}),
        AIMessage(content="I found a candidate.", name="explorer 1"),
    ]

    assert model_messages(messages) == [
        {"index": 0, "message_index": 0, "branch_id": None, "content": "", "reasoning": None,
         "tool_calls": 1, "tokens_in": None, "tokens_out": None},
        {"index": 1, "message_index": 1, "branch_id": None, "content": "I will inspect the gap.",
         "reasoning": "The upper corner is free.", "tool_calls": 0,
         "tokens_in": None, "tokens_out": None},
        {"index": 2, "message_index": 2, "branch_id": "explorer 1", "content": "I found a candidate.", "reasoning": None,
         "tool_calls": 0, "tokens_in": None, "tokens_out": None},
    ]


def test_model_and_tool_events_share_message_order() -> None:
    messages = [
        AIMessage(content="Checking the corner", tool_calls=[{"id": "one", "name": "inspect", "args": {"x": 1}}],
                  usage_metadata={"input_tokens": 50, "output_tokens": 8, "total_tokens": 58}),
        ToolMessage(content='{"valid": true}', tool_call_id="one"),
        AIMessage(content="That worked.", usage_metadata={"input_tokens": 60, "output_tokens": 4, "total_tokens": 64}),
    ]
    replies = model_messages(messages)
    calls = tool_events(messages, {})
    assert [(reply["message_index"], reply["tokens_out"]) for reply in replies] == [(0, 8), (2, 4)]
    assert calls[0]["message_index"] == 0
    assert calls[0]["result"] == {"valid": True}
