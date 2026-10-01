"""What a run may spend, and what it spent — the numbers every run file carries.

These two types are shared for one reason: they appear in a file the lab writes and reads
back, and two implementations of the same stored JSON would be two truths. Everything a
graph merely remembers stays in that workflow's own folder.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any, NamedTuple

from paper_obs.domain.serde import JSON, as_float, as_int, optional


class Prices(NamedTuple):
    """What a million tokens cost: in, out, and in when the provider read them from its cache.

    Without a cache price, a cached token is billed as any input token, which errs high.
    """

    input: float
    output: float
    cached: float | None = None

    def cost(self, tokens_in: int, tokens_out: int, tokens_cached: int = 0) -> float:
        """Return what these tokens cost; ``tokens_cached`` is the part of ``tokens_in`` cached."""
        cached = self.input if self.cached is None else self.cached
        fresh = tokens_in - tokens_cached
        return (fresh * self.input + tokens_cached * cached + tokens_out * self.output) / 1e6


def usage(message: Any) -> tuple[int, int, int]:
    """Return the input, output and cached input tokens a provider reported for one reply.

    The cached count is LangChain's ``cache_read``, or DeepSeek's own ``prompt_cache_hit_tokens``
    where that is missing. A reply that reports nothing counts zero: no money is invented.
    """
    report = getattr(message, "usage_metadata", None)
    if not isinstance(report, dict):
        return 0, 0, 0
    cached = (report.get("input_token_details") or {}).get("cache_read")
    if cached is None:
        raw = (getattr(message, "response_metadata", None) or {}).get("token_usage") or {}
        cached = raw.get("prompt_cache_hit_tokens")
    return (int(report.get("input_tokens", 0) or 0), int(report.get("output_tokens", 0) or 0),
            int(cached or 0))


@dataclass(frozen=True)
class Cost:
    """What one turn, or one run, spent.

    Counted in calls: how many times a model was asked, and how many tools were run.
    Tokens, seconds and money ride along as measurements. The optional money ceiling
    is checked between turns, after a provider has reported its token usage.
    """

    llm_calls: int = 0
    tool_calls: int = 0
    seconds: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    #: The part of ``tokens_in`` the provider read from its prompt cache.
    tokens_cached: int = 0
    cost: float | None = None

    def __add__(self, other: "Cost") -> "Cost":
        """Return the total of two spends, money included when both know a price."""
        if self.cost is None:
            money = other.cost
        elif other.cost is None:
            money = self.cost
        else:
            money = self.cost + other.cost
        return Cost(
            llm_calls=self.llm_calls + other.llm_calls,
            tool_calls=self.tool_calls + other.tool_calls,
            seconds=self.seconds + other.seconds,
            tokens_in=self.tokens_in + other.tokens_in,
            tokens_out=self.tokens_out + other.tokens_out,
            tokens_cached=self.tokens_cached + other.tokens_cached,
            cost=money,
        )

    def to_dict(self) -> JSON:
        """Return the JSON a run's trace keeps."""
        return {
            "llm_calls": self.llm_calls,
            "tool_calls": self.tool_calls,
            "seconds": self.seconds,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "tokens_cached": self.tokens_cached,
            "cost": self.cost,
        }

    @classmethod
    def from_dict(cls, data: JSON) -> "Cost":
        """Decode a spend, tolerating a document written before a field existed."""
        cost = data.get("cost")
        return cls(
            llm_calls=as_int(optional(data, "llm_calls", 0), "cost.llm_calls"),
            tool_calls=as_int(optional(data, "tool_calls", 0), "cost.tool_calls"),
            seconds=as_float(optional(data, "seconds", 0.0), "cost.seconds"),
            tokens_in=as_int(optional(data, "tokens_in", 0), "cost.tokens_in"),
            tokens_out=as_int(optional(data, "tokens_out", 0), "cost.tokens_out"),
            tokens_cached=as_int(optional(data, "tokens_cached", 0), "cost.tokens_cached"),
            cost=None if cost is None else as_float(cost, "cost.cost"),
        )


def field_names() -> tuple[str, ...]:
    """Return the names of the ceilings, for a caller splitting a flat record of parameters."""
    return tuple(item.name for item in fields(Budget))


@dataclass(frozen=True)
class Budget:
    """The ceilings a run may not cross.

    A run ends when one of them is reached. A ceiling of zero is no ceiling at all: the
    run then stops only on the others, and a run with none of them is bounded by the
    agent's own decision and by whoever is watching it. Stored JSON keeps them numeric.
    """

    rounds: int = 12
    llm_calls: int = 60
    tool_calls: int = 60
    #: Zero means no clock at all, which is the shipped default: a run stops on its own
    #: ceilings unless a caller asks for a deadline.
    seconds: float = 0.0
    max_cost: float | None = None

    def __post_init__(self) -> None:
        for name in ("rounds", "llm_calls", "tool_calls"):
            value = getattr(self, name)
            if value < 0:
                raise ValueError(f"{name} must be nonnegative, got {value!r}")
        if self.seconds < 0:
            raise ValueError(f"seconds must be nonnegative, got {self.seconds!r}")
        if self.max_cost is not None and self.max_cost <= 0:
            raise ValueError(f"max_cost must be positive, got {self.max_cost!r}")

    def stopped_by(self, spend: Cost, *, round: int) -> str | None:
        """Return the ceiling reached, or ``None`` while the run may go on.

        ``round`` is passed in rather than read from the spend: a round is a count of the
        state, not something a run pays.
        """
        if self.rounds > 0 and round >= self.rounds:
            return "rounds"
        if self.llm_calls > 0 and spend.llm_calls >= self.llm_calls:
            return "llm_calls"
        if self.tool_calls > 0 and spend.tool_calls >= self.tool_calls:
            return "tool_calls"
        if self.seconds > 0 and spend.seconds >= self.seconds:
            return "seconds"
        if self.max_cost is not None and spend.cost is not None and spend.cost >= self.max_cost:
            return "max_cost"
        return None

    def to_dict(self) -> JSON:
        """Return the JSON a run's manifest keeps."""
        return {
            "rounds": self.rounds,
            "llm_calls": self.llm_calls,
            "tool_calls": self.tool_calls,
            "seconds": self.seconds,
            "max_cost": self.max_cost,
        }

    @classmethod
    def from_dict(cls, data: JSON) -> "Budget":
        """Decode ceilings; a field the document omits takes its default."""
        return cls(
            rounds=as_int(optional(data, "rounds", cls.rounds), "budget.rounds"),
            llm_calls=as_int(optional(data, "llm_calls", cls.llm_calls), "budget.llm_calls"),
            tool_calls=as_int(optional(data, "tool_calls", cls.tool_calls), "budget.tool_calls"),
            seconds=as_float(optional(data, "seconds", cls.seconds), "budget.seconds"),
            max_cost=None if data.get("max_cost") is None else as_float(data["max_cost"], "budget.max_cost"),
        )


__all__ = ["Budget", "Cost", "Prices", "field_names", "usage"]
