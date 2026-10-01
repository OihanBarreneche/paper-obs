"""What a model is, and where it can be reached.

The lab speaks one wire format — the OpenAI chat-completions API — because every
provider worth reaching exposes it, DeepSeek and a local Ollama included. A
*provider* is therefore nothing more than a base URL, the name of the environment
variable holding its key, and the models it serves: adding one is a line in
:data:`PROVIDERS`, never a branch in the client.

Nothing here imports an HTTP library, so the API can list the providers with the
``llm`` extra absent.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field

from paper_obs.domain.serde import JSON, as_float, as_int, optional

#: Environment variable read after a per-request key and before the provider's.
#:
#: This is the *server operator's* key, and on a published deployment every visitor
#: spends the operator's credit with it. The published mode is therefore a per-request
#: key, which lives in memory for one run and is never written down; this variable is
#: kept for a local, single-user lab.
ENVIRONMENT_KEY = "PAPER_OBS_API_KEY"

#: Provider assumed when a caller names none.
DEFAULT_PROVIDER = "deepseek"

#: The values the wire format accepts for ``reasoning_effort``.
REASONING_EFFORTS = ("low", "medium", "high", "max")


@dataclass(frozen=True)
class Provider:
    """One reachable endpoint, and how to authenticate against it."""

    name: str
    base_url: str
    api_key_env: str
    models: tuple[str, ...]
    note: str
    needs_key: bool = True
    extra_body: dict[str, JSON] = field(default_factory=dict)
    """Parameters this endpoint needs in every request body, forwarded as they are.

    An endpoint that turns something on by default and cannot be talked out of it by a
    standard field needs one of these — DeepSeek's thinking mode is the case that made it
    necessary — and the client forwards it without knowing what it means.
    """

    extra_headers: dict[str, str] = field(default_factory=dict)
    """Headers every request carries, forwarded as ChatOpenAI's ``default_headers``.

    Empty for every endpoint but OpenRouter, whose attribution headers are the only use:
    they name the application, never authenticate it, and no key is ever written here.
    """

    reasoning_body: Callable[[str], dict[str, JSON]] | None = None
    """How this endpoint spells a requested reasoning effort, or ``None`` for "not at all".

    The shape is not shared: DeepSeek turns thinking on with a nested object, the
    OpenAI-compatible endpoints take a plain ``reasoning_effort``, and an endpoint that
    refuses an unknown field — Groq — must be handed nothing. Leaving this ``None`` is how
    a row says so, and the caller's effort is then simply not forwarded.
    """

    omit_temperature: bool = False
    """Whether a request to this endpoint must leave ``temperature`` out altogether.

    An endpoint that refuses the field does not ignore it: OpenAI's reasoning models answer
    400 for it. LangChain's own guard only recognises the ``o1`` and ``gpt-5`` families by
    name, so a newer id slips through — and this table exists precisely because the id is the
    caller's to choose. A row that says so here is handed the endpoint's own default instead
    of a number it would reject.
    """

    local_cli: str | None = None
    """The subscription CLI that answers instead of an endpoint, ``claude`` or ``codex``.

    Such a row has no URL and no key: :mod:`paper_obs.llm.subscription` runs the CLI on this
    machine, signed in to its owner's monthly subscription, and no per-token price applies.
    """

    def to_dict(self) -> JSON:
        """Return what a client needs to offer this provider.

        ``api_key_env`` is the *name* of a variable, never a key, and
        ``needs_key`` says whether a client has to ask for one at all.
        """
        return {
            "name": self.name,
            "base_url": self.base_url,
            "api_key_env": self.api_key_env,
            "models": list(self.models),
            "note": self.note,
            "needs_key": self.needs_key,
            "accepts_temperature": not self.omit_temperature,
            "subscription": self.local_cli is not None,
        }


def _deepseek_reasoning(effort: str) -> dict[str, JSON]:
    """Return DeepSeek's own spelling: a nested thinking switch plus the effort."""
    return {"thinking": {"type": "enabled"}, "reasoning_effort": effort}


def _standard_reasoning(effort: str) -> dict[str, JSON]:
    """Return the plain ``reasoning_effort`` the OpenAI-compatible endpoints take."""
    return {"reasoning_effort": effort}


#: Every endpoint the lab can reach, in the order this table documents them.
#:
#: The model ids below are a *default that drifts*: they were the current names when the
#: row was written, nothing more. A client may type any id, and
#: ````POST /api/providers/models```` asks the endpoint itself, so a stale default is never
#: the only option. A provider that cannot be one row — Azure, Bedrock, Vertex: OAuth,
#: SigV4 or ADC and a base URL that belongs to one account — is deliberately absent, and
#: so are the second-order aggregators; ````custom```` covers a local vLLM or LM Studio.
PROVIDERS: dict[str, Provider] = {
    "deepseek": Provider(
        name="deepseek",
        base_url="https://api.deepseek.com",
        api_key_env="DEEPSEEK_API_KEY",
        models=("deepseek-flash", "deepseek-v4-pro"),
        note=(
            "OpenAI-compatible. 'deepseek-flash' is DeepSeek-V4.1-Flash and 'deepseek-v4-pro' "
            "is DeepSeek-V4-Pro; the retired names 'deepseek-chat' and 'deepseek-reasoner' "
            "still answer but no longer name a model of their own."
        ),
        # Thinking is on by default on these models, at high effort, and it is billed as
        # output: an agent that calls tools turn after turn wants it off. Set
        # reasoning_effort on the configuration to turn it back on.
        extra_body={"thinking": {"type": "disabled"}},
        reasoning_body=_deepseek_reasoning,
    ),
    "openai": Provider(
        name="openai",
        base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
        models=("gpt-6-luna", "gpt-6-sol"),
        note=(
            "The reference implementation of the wire format. The two ids are a default that "
            "will drift; type any id, or list the endpoint's own with the discovery route."
        ),
        reasoning_body=_standard_reasoning,
        # Its reasoning models answer 400 for a `temperature` field, and LangChain only strips
        # it for the `o1` and `gpt-5` families it knows by name.
        omit_temperature=True,
    ),
    "anthropic": Provider(
        name="anthropic",
        base_url="https://api.anthropic.com/v1/",
        api_key_env="ANTHROPIC_API_KEY",
        models=("claude-sonnet-5", "claude-opus-5-5"),
        note=(
            "Anthropic's OpenAI *compatibility shim*, not their native Messages API: it ignores "
            "strict tool schemas and prompt caching, and hoists system messages to the top of "
            "the conversation. There is no native Messages client here by design."
        ),
    ),
    "openrouter": Provider(
        name="openrouter",
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
        models=("openai/gpt-6-luna", "anthropic/claude-opus-5.5"),
        note=(
            "An aggregator, so model ids are namespaced 'owner/model' and the catalogue moves "
            "daily. The X-OpenRouter-Title header is attribution only, never authentication; "
            "it is the only use of extra_headers today."
        ),
        extra_headers={"X-OpenRouter-Title": "Paper Obs"},
    ),
    "gemini": Provider(
        name="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        api_key_env="GEMINI_API_KEY",
        models=("gemini-3.8-flash", "gemini-2.5-pro"),
        note=(
            "Google's OpenAI compatibility layer: the trailing '/openai/' is mandatory, and "
            "there is no /models on that path, so this row cannot be discovered. Reasoning "
            "cannot be disabled on recent Gemini models."
        ),
        reasoning_body=_standard_reasoning,
    ),
    "xai": Provider(
        name="xai",
        base_url="https://api.x.ai/v1",
        api_key_env="XAI_API_KEY",
        models=("grok-4.7", "grok-4"),
        note=(
            "Grok. The reasoning models take a plain reasoning_effort; the non-reasoning ones "
            "ignore it, so it is only ever sent when a caller asks for one."
        ),
        reasoning_body=_standard_reasoning,
    ),
    "mistral": Provider(
        name="mistral",
        base_url="https://api.mistral.ai/v1",
        api_key_env="MISTRAL_API_KEY",
        models=("mistral-large-latest", "mistral-large-3-25-12"),
        note=(
            "A '-latest' alias moves under you, so a pinned id is kept beside it; the pinned id "
            "ages too, which is why the field accepts any id."
        ),
    ),
    "groq": Provider(
        name="groq",
        base_url="https://api.groq.com/openai/v1",
        api_key_env="GROQ_API_KEY",
        models=("openai/gpt-oss-120b", "llama-3.3-70b-versatile"),
        note=(
            "A field this endpoint does not know — logprobs, logit_bias, messages[].name, n>1 — "
            "comes back as a 400, so the client never sends one: no reasoning_body, and nothing "
            "beyond the fields every OpenAI-compatible call carries."
        ),
    ),
    "together": Provider(
        name="together",
        base_url="https://api.together.ai/v1",
        api_key_env="TOGETHER_API_KEY",
        models=("deepseek-ai/DeepSeek-V4-Pro-0813", "Qwen/Qwen3.8-Flash"),
        note=(
            "Model ids are namespaced 'owner/model'. Use api.together.ai: the old .xyz host is "
            "deprecated."
        ),
    ),
    "ollama": Provider(
        name="ollama",
        base_url="http://localhost:11434/v1",
        api_key_env="OLLAMA_API_KEY",
        models=("llama3.1", "qwen2.5"),
        note="A local server. It accepts any key, so none is required.",
        needs_key=False,
    ),
    "ollama-cloud": Provider(
        name="ollama-cloud",
        base_url="https://ollama.com/v1",
        api_key_env="OLLAMA_API_KEY",
        models=("gpt-oss:120b", "deepseek-v4-pro:0813"),
        note=(
            "Ollama's hosted models: the same ids as a local server, but a real key is needed. "
            "Its /models answers without one, so this row can be discovered."
        ),
    ),
    # A subscription instead of API credit: a grey zone, documented in the README.
    "claude-code": Provider(
        name="claude-code",
        base_url="cli://claude",
        api_key_env="",
        models=("sonnet", "opus", "haiku"),
        note=(
            "The Claude Code CLI on this machine, signed in to a Claude subscription: each call "
            "runs 'claude -p' with its own tools off. Slower than an API and paid by the month; "
            "PAPER_OBS_CLAUDE_CLI names the executable when it is not on the PATH."
        ),
        needs_key=False,
        omit_temperature=True,
        local_cli="claude",
    ),
    "codex": Provider(
        name="codex",
        base_url="cli://codex",
        api_key_env="",
        models=("gpt-6-luna", "gpt-6-sol"),
        note=(
            "The Codex CLI on this machine, signed in to a ChatGPT subscription: each call runs "
            "'codex exec' read-only in an empty folder. Slower than an API and paid by the month; "
            "PAPER_OBS_CODEX_CLI names the executable when it is not on the PATH."
        ),
        needs_key=False,
        omit_temperature=True,
        local_cli="codex",
    ),
    "custom": Provider(
        name="custom",
        base_url="",
        api_key_env=ENVIRONMENT_KEY,
        models=(),
        note="Any OpenAI-compatible endpoint: give base_url and model.",
    ),
}


def provider(name: str) -> Provider:
    """Return the named provider, or raise ``KeyError`` listing the known ones."""
    try:
        return PROVIDERS[name]
    except KeyError as error:
        known = ", ".join(sorted(PROVIDERS))
        raise KeyError(f"unknown provider {name!r}; known providers: {known}") from error


def endpoint_for(config: "ModelConfig") -> str:
    """Return the base URL a configuration's requests go to.

    A provider with no base URL of its own — ``custom`` — must be given one, and is
    refused here rather than halfway through a request.
    """
    base = config.base_url or PROVIDERS[config.provider].base_url
    if not base:
        raise ValueError(
            f"provider {config.provider!r} has no base_url of its own; "
            "a configuration must carry one"
        )
    return base.rstrip("/")


@dataclass(frozen=True)
class ModelConfig:
    """Everything needed to reach one model, and to account for what it cost.

    There is deliberately **no key field**. A configuration is written to a run
    file, returned by the API and stored beside a candidate, so a secret must not
    be able to travel inside one; the key is resolved when a call is made and
    lives only in the client that makes it.

    ``cost_per_million_*`` are optional and no price list ships with the lab: a
    price ages badly, and a stale dollar figure is worse than none. A caller that
    knows the price supplies it; otherwise a run records tokens and no money.
    """

    provider: str = DEFAULT_PROVIDER
    model: str = ""
    base_url: str = ""
    temperature: float = 0.0
    max_tokens: int | None = None
    reasoning_effort: str | None = None
    cost_per_million_in: float | None = None
    cost_per_million_out: float | None = None
    #: The price of an input token the provider read from its prompt cache; without one, a
    #: cached token is billed at ``cost_per_million_in``.
    cost_per_million_cached: float | None = None

    def __post_init__(self) -> None:
        provider(self.provider)
        if not 0.0 <= self.temperature <= 2.0:
            raise ValueError(f"temperature must lie within [0, 2], got {self.temperature!r}")
        if self.max_tokens is not None and self.max_tokens < 1:
            raise ValueError(f"max_tokens must be at least 1, got {self.max_tokens!r}")
        if self.reasoning_effort is not None and self.reasoning_effort not in REASONING_EFFORTS:
            known = ", ".join(REASONING_EFFORTS)
            raise ValueError(
                f"reasoning_effort must be one of {known}, got {self.reasoning_effort!r}"
            )

    @property
    def endpoint(self) -> str:
        """Return the base URL this configuration's requests go to."""
        return endpoint_for(self)

    def to_dict(self) -> JSON:
        """Return the JSON representation — which cannot hold a secret."""
        return {
            "provider": self.provider,
            "model": self.model,
            "base_url": self.endpoint,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "reasoning_effort": self.reasoning_effort,
            "cost_per_million_in": self.cost_per_million_in,
            "cost_per_million_out": self.cost_per_million_out,
            "cost_per_million_cached": self.cost_per_million_cached,
        }

    @classmethod
    def from_dict(cls, data: JSON) -> "ModelConfig":
        """Decode a configuration.

        A stored document carries the *resolved* endpoint, so ``base_url`` reads as an
        override and resolves to the provider's own value when the two agree: a
        configuration written and read back writes the same document again.
        """
        return cls(
            provider=str(data.get("provider", DEFAULT_PROVIDER)),
            model=str(data.get("model", "")),
            base_url=str(data.get("base_url", "")),
            temperature=as_float(optional(data, "temperature", 0.0), "model.temperature"),
            max_tokens=_optional_int(data.get("max_tokens"), "model.max_tokens"),
            reasoning_effort=(
                None if data.get("reasoning_effort") is None else str(data["reasoning_effort"])
            ),
            cost_per_million_in=_optional_float(
                data.get("cost_per_million_in"), "model.cost_per_million_in"
            ),
            cost_per_million_out=_optional_float(
                data.get("cost_per_million_out"), "model.cost_per_million_out"
            ),
            cost_per_million_cached=_optional_float(
                data.get("cost_per_million_cached"), "model.cost_per_million_cached"
            ),
        )


def _optional_int(value: object, where: str) -> int | None:
    """Return a JSON integer, or ``None`` when the field is absent."""
    return None if value is None else as_int(value, where)


def _optional_float(value: object, where: str) -> float | None:
    """Return a JSON number, or ``None`` when the field is absent."""
    return None if value is None else as_float(value, where)


def catalogue() -> list[JSON]:
    """Return every provider a client may choose from, sorted by name."""
    return [PROVIDERS[name].to_dict() for name in sorted(PROVIDERS)]


def key_present() -> JSON:
    """Return where a key is already configured — never a key itself.

    A client needs to know whether to ask for one, not what it is, so this is the
    only thing the API ever says about a secret.
    """
    return {
        "environment_key": ENVIRONMENT_KEY,
        "environment_key_set": bool(os.environ.get(ENVIRONMENT_KEY)),
        "providers": {
            name: bool(item.api_key_env and os.environ.get(item.api_key_env))
            for name, item in PROVIDERS.items()
        },
    }


def resolve_api_key(config: "ModelConfig", *, provided: str | None = None) -> str:
    """Return the key to authenticate with, or raise naming where one may come from.

    The order is deliberate: what the caller supplies wins, then the lab's own variable,
    then the provider's. A provider that needs no key — a local Ollama — returns the
    empty string rather than raising.
    """
    if provided:
        return provided.strip()
    for name in (ENVIRONMENT_KEY, PROVIDERS[config.provider].api_key_env):
        value = os.environ.get(name) if name else None
        if value:
            return value.strip()
    if not PROVIDERS[config.provider].needs_key:
        return ""
    raise ValueError(
        f"no key for provider {config.provider!r}: set {ENVIRONMENT_KEY} or "
        f"{PROVIDERS[config.provider].api_key_env}, or send one with the request"
    )


__all__ = [
    "DEFAULT_PROVIDER",
    "ENVIRONMENT_KEY",
    "PROVIDERS",
    "REASONING_EFFORTS",
    "ModelConfig",
    "Provider",
    "catalogue",
    "endpoint_for",
    "key_present",
    "provider",
    "resolve_api_key",
]
