"""The shared numbers: a spend adds up, a budget names what stopped a run, both survive a file."""

from __future__ import annotations

import pytest

from paper_obs.workflows.budget import Budget, Cost


def test_a_spend_counts_calls_and_leaves_an_unknown_price_unknown() -> None:
    total = Cost(llm_calls=1, tool_calls=3, seconds=0.5, tokens_in=100) + Cost(
        llm_calls=2, tool_calls=5, seconds=0.25, tokens_out=20
    )
    assert (total.llm_calls, total.tool_calls) == (3, 8)
    assert (total.tokens_in, total.tokens_out) == (100, 20)
    assert total.seconds == pytest.approx(0.75)
    assert total.cost is None
    assert (Cost(cost=0.25) + Cost(cost=0.10)).cost == pytest.approx(0.35)
    assert (Cost(cost=0.25) + Cost()).cost == pytest.approx(0.25)
    assert (Cost() + Cost(cost=0.25)).cost == pytest.approx(0.25)


def test_a_spend_round_trips_and_reads_an_older_document() -> None:
    spend = Cost(llm_calls=3, tool_calls=8, seconds=1.5, tokens_in=9, tokens_out=4, cost=0.02)
    assert Cost.from_dict(spend.to_dict()) == spend
    assert Cost.from_dict({"llm_calls": 2, "tool_calls": 5}) == Cost(llm_calls=2, tool_calls=5)


def test_a_budget_names_the_ceiling_that_stopped_the_run() -> None:
    budget = Budget(rounds=3, llm_calls=5, tool_calls=9, seconds=10.0)
    assert budget.stopped_by(Cost(), round=0) is None
    assert budget.stopped_by(Cost(), round=3) == "rounds"
    assert budget.stopped_by(Cost(llm_calls=5), round=0) == "llm_calls"
    assert budget.stopped_by(Cost(tool_calls=9), round=0) == "tool_calls"
    assert budget.stopped_by(Cost(seconds=10.0), round=0) == "seconds"
    assert Budget(max_cost=0.1).stopped_by(Cost(cost=0.1), round=0) == "max_cost"
    # A run out of turns says so, whatever else it still has.
    assert budget.stopped_by(Cost(), round=9) == "rounds"


def test_a_budget_refuses_a_ceiling_below_zero() -> None:
    for wrong in ({"rounds": -1}, {"llm_calls": -1}, {"tool_calls": -1}, {"seconds": -1.0}, {"max_cost": 0.0}):
        with pytest.raises(ValueError):
            Budget(**wrong)


def test_a_zero_ceiling_is_no_ceiling_at_all() -> None:
    """A dash in any count means "no ceiling", exactly as a zero clock already did."""
    unlimited = Budget(rounds=0, llm_calls=0, tool_calls=0, seconds=0.0)
    assert unlimited.stopped_by(
        Cost(llm_calls=10_000, tool_calls=10_000, seconds=99_999.0), round=500
    ) is None
    assert Budget(rounds=3).stopped_by(Cost(), round=3) == "rounds"


def test_zero_seconds_disables_only_the_clock() -> None:
    budget = Budget(rounds=4, llm_calls=9, tool_calls=12, seconds=0.0)
    assert budget.stopped_by(Cost(seconds=60), round=0) is None
    assert budget.stopped_by(Cost(llm_calls=9, seconds=60), round=0) == "llm_calls"


def test_a_budget_round_trips_and_takes_its_defaults() -> None:
    budget = Budget(rounds=4, llm_calls=9, tool_calls=12, seconds=30.0, max_cost=0.2)
    assert Budget.from_dict(budget.to_dict()) == budget
    assert Budget.from_dict({}) == Budget()


def test_cached_input_is_billed_at_its_own_price_or_else_as_any_input() -> None:
    from paper_obs.workflows.budget import Prices

    assert Prices(1.0, 2.0, 0.1).cost(1_000_000, 500_000, 800_000) == pytest.approx(0.2 + 0.08 + 1.0)
    assert Prices(1.0, 2.0).cost(1_000_000, 500_000, 800_000) == pytest.approx(2.0)


def test_the_cached_count_is_read_from_langchain_or_from_deepseeks_own_field() -> None:
    from types import SimpleNamespace

    from paper_obs.workflows.budget import usage

    standard = SimpleNamespace(usage_metadata={
        "input_tokens": 100, "output_tokens": 20, "input_token_details": {"cache_read": 60}})
    deepseek = SimpleNamespace(usage_metadata={"input_tokens": 100, "output_tokens": 20},
                               response_metadata={"token_usage": {"prompt_cache_hit_tokens": 70}})
    assert usage(standard) == (100, 20, 60)
    assert usage(deepseek) == (100, 20, 70)
    assert usage(SimpleNamespace()) == (0, 0, 0)
