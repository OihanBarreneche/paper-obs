"""The model a run talks to, as LangChain wants it.

One factory, because the provider is a configuration and the key is resolved in one
place. Everything else about a model — the loop, the retries, the tool protocol — is
LangChain's.
"""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from .models import PROVIDERS, ModelConfig, resolve_api_key


def chat_model(config: ModelConfig, *, api_key: str | None = None) -> BaseChatModel:
    """Return the chat model of a configuration.

    The key comes from the caller when it has one — the interface sends its own — and
    from the environment otherwise. It is never written anywhere else.

    A provider may declare body parameters it needs on every request, and the shape of a
    reasoning effort is *its* shape: DeepSeek turns thinking on with a nested object while
    the OpenAI-compatible endpoints take a plain field, and a provider that refuses an
    unknown one declares neither, so nothing DeepSeek-shaped ever reaches it. Attribution
    headers a row declares travel as the client's default headers. A row whose endpoint
    refuses ``temperature`` gets none: LangChain drops a ``None`` from the body, so the
    endpoint's own default applies rather than a number it answers 400 for.
    """
    row = PROVIDERS[config.provider]
    body = dict(row.extra_body)
    if config.reasoning_effort is not None and row.reasoning_body is not None:
        body.update(row.reasoning_body(config.reasoning_effort))
    return ChatOpenAI(
        model=config.model,
        base_url=config.endpoint,
        api_key=resolve_api_key(config, provided=api_key),
        temperature=None if row.omit_temperature else config.temperature,
        max_tokens=config.max_tokens,
        extra_body=body or None,
        default_headers=dict(row.extra_headers) or None,
    )


__all__ = ["chat_model"]
