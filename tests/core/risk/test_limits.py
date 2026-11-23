"""Risk limits in three layers: each value valid on its own, each layer within the one above."""

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from tyche.core.domain import Currency, Money, MoneyLimits
from tyche.core.risk import (
    Guardrails,
    LimitBreach,
    RiskProfile,
    StrategyRiskLimits,
    require_risk_profile_name,
)


def usd(amount: str) -> Money:
    return Money(Decimal(amount), Currency.USD)


def guardrails(**changes: object) -> Guardrails:
    values: dict[str, object] = {
        "max_risk_per_trade": Decimal("0.02"),
        "max_open_positions": 10,
        "max_position_size": Decimal("0.25"),
        "max_daily_loss_limit": Decimal("0.05"),
        "max_drawdown_kill": Decimal("0.25"),
        "max_total_capital": (usd("700"),),
        "max_order_value": (usd("350"),),
    }
    values.update(changes)
    return Guardrails(**values)  # type: ignore[arg-type]


def profile(**changes: object) -> RiskProfile:
    values: dict[str, object] = {
        "name": "default",
        "risk_per_trade": Decimal("0.01"),
        "max_open_positions": 5,
        "max_position_size": Decimal("0.20"),
        "daily_loss_limit": Decimal("0.03"),
        "drawdown_kill": Decimal("0.15"),
    }
    values.update(changes)
    return RiskProfile(**values)  # type: ignore[arg-type]


class TestProfileName:
    @pytest.mark.parametrize("name", ["default", "test-a", "riskybusiness", "safe_cash2"])
    def test_accepts_the_briefs_kind_of_names(self, name: str) -> None:
        require_risk_profile_name(name)

    @pytest.mark.parametrize("name", ["", "Default", "../secrets", "a/b", "1st", "-a", "a b"])
    def test_refuses_anything_that_could_misbehave_as_a_file_name(self, name: str) -> None:
        with pytest.raises(ValueError, match="invalid risk profile name"):
            require_risk_profile_name(name)


class TestRiskProfile:
    def test_the_briefs_default_profile_is_valid(self) -> None:
        assert profile().max_open_positions == 5

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("risk_per_trade", Decimal(0)),
            ("risk_per_trade", Decimal("1.01")),
            ("max_position_size", Decimal("-0.1")),
            ("daily_loss_limit", Decimal(1)),
            ("drawdown_kill", Decimal(1)),
            ("drawdown_kill", Decimal("NaN")),
            ("max_open_positions", 0),
            ("max_open_positions", True),
        ],
    )
    def test_refuses_a_value_that_is_not_a_limit(self, key: str, value: object) -> None:
        with pytest.raises(ValueError, match=key):
            profile(**{key: value})

    def test_a_loss_limit_of_100_percent_is_refused_because_it_could_never_trigger(
        self,
    ) -> None:
        with pytest.raises(ValueError, match="below 1"):
            profile(daily_loss_limit=Decimal(1))

    def test_a_position_may_be_the_whole_account(self) -> None:
        assert profile(max_position_size=Decimal(1)).max_position_size == 1


class TestGuardrails:
    def test_a_profile_within_every_ceiling_has_no_breaches(self) -> None:
        assert guardrails().breaches(profile()) == ()

    def test_a_value_equal_to_its_ceiling_is_allowed(self) -> None:
        at_limit = profile(
            risk_per_trade=Decimal("0.02"),
            max_open_positions=10,
            max_position_size=Decimal("0.25"),
            daily_loss_limit=Decimal("0.05"),
            drawdown_kill=Decimal("0.25"),
        )

        assert guardrails().breaches(at_limit) == ()

    def test_every_breach_is_reported_with_its_ceiling(self) -> None:
        loose = profile(max_position_size=Decimal("0.30"), drawdown_kill=Decimal("0.40"))

        assert guardrails().breaches(loose) == (
            LimitBreach("max_position_size", "0.30", "max_position_size", "0.25"),
            LimitBreach("drawdown_kill", "0.40", "max_drawdown_kill", "0.25"),
        )

    def test_caps_are_looked_up_by_currency(self) -> None:
        rails = guardrails()

        assert rails.capital_cap(Currency.USD) == usd("700")
        assert rails.order_cap(Currency.USD) == usd("350")
        assert rails.capital_cap(Currency.CAD) is None

    def test_gives_both_money_caps_of_each_currency_as_money_limits(self) -> None:
        assert guardrails().money_limits() == {Currency.USD: MoneyLimits(usd("700"), usd("350"))}

    def test_lists_the_currencies_without_both_caps(self) -> None:
        rails = guardrails(
            max_total_capital=(usd("700"), Money(Decimal(1000), Currency.CAD)),
        )

        assert rails.uncapped([Currency.USD, Currency.CAD]) == (Currency.CAD,)

    def test_needs_at_least_one_cap(self) -> None:
        with pytest.raises(ValueError, match="at least one currency"):
            guardrails(max_total_capital=())

    def test_a_currency_is_capped_once(self) -> None:
        with pytest.raises(ValueError, match="more than once"):
            guardrails(max_total_capital=(usd("700"), usd("800")))

    def test_a_cap_is_above_zero(self) -> None:
        with pytest.raises(ValueError, match="above 0"):
            guardrails(max_order_value=(usd("0"),))

    def test_an_order_cap_is_at_most_the_capital_cap(self) -> None:
        with pytest.raises(ValueError, match="above max_total_capital"):
            guardrails(max_order_value=(usd("701"),))

    def test_an_order_cap_needs_a_capital_cap_in_its_currency(self) -> None:
        with pytest.raises(ValueError, match="no max_total_capital cap"):
            guardrails(max_order_value=(usd("350"), Money(Decimal(10), Currency.CAD)))


class TestStrategyRiskLimits:
    def test_no_override_breaks_nothing(self) -> None:
        assert StrategyRiskLimits().breaches(profile()) == ()

    def test_stricter_or_equal_overrides_are_allowed(self) -> None:
        limits = StrategyRiskLimits(
            risk_per_trade=Decimal("0.005"), max_open_positions=5, max_position_size=Decimal("0.1")
        )

        assert limits.breaches(profile()) == ()

    def test_a_looser_override_is_a_breach(self) -> None:
        limits = StrategyRiskLimits(max_open_positions=6, max_position_size=Decimal("0.5"))

        assert limits.breaches(profile()) == (
            LimitBreach("max_open_positions", "6", "max_open_positions", "5"),
            LimitBreach("max_position_size", "0.5", "max_position_size", "0.20"),
        )

    def test_an_override_must_itself_be_a_valid_limit(self) -> None:
        with pytest.raises(ValueError, match="max_open_positions"):
            StrategyRiskLimits(max_open_positions=0)


# --- properties: a breach is reported exactly when a value is looser than its limit ---

fractions = st.decimals(min_value=Decimal("0.0001"), max_value=Decimal("0.9999"), places=4)
counts = st.integers(min_value=1, max_value=50)


PROFILE_KEYS = (
    "risk_per_trade",
    "max_open_positions",
    "max_position_size",
    "daily_loss_limit",
    "drawdown_kill",
)


@given(
    ceilings=st.tuples(fractions, counts, fractions, fractions, fractions),
    values=st.tuples(fractions, counts, fractions, fractions, fractions),
)
def test_a_profile_breaks_the_guardrails_exactly_where_a_value_is_above_its_ceiling(
    ceilings: tuple[Decimal, int, Decimal, Decimal, Decimal],
    values: tuple[Decimal, int, Decimal, Decimal, Decimal],
) -> None:
    rails = guardrails(
        max_risk_per_trade=ceilings[0],
        max_open_positions=ceilings[1],
        max_position_size=ceilings[2],
        max_daily_loss_limit=ceilings[3],
        max_drawdown_kill=ceilings[4],
    )
    candidate = profile(**dict(zip(PROFILE_KEYS, values, strict=True)))
    pairs: list[tuple[Decimal | int, Decimal | int]] = list(zip(values, ceilings, strict=True))

    breached = {breach.key for breach in rails.breaches(candidate)}

    expected = {
        key for key, (value, ceiling) in zip(PROFILE_KEYS, pairs, strict=True) if value > ceiling
    }
    assert breached == expected


@given(
    active=st.tuples(fractions, counts, fractions),
    override=st.tuples(st.none() | fractions, st.none() | counts, st.none() | fractions),
)
def test_an_override_breaks_the_profile_exactly_where_it_is_looser(
    active: tuple[Decimal, int, Decimal],
    override: tuple[Decimal | None, int | None, Decimal | None],
) -> None:
    current = profile(**dict(zip(PROFILE_KEYS[:3], active, strict=True)))
    limits = StrategyRiskLimits(
        risk_per_trade=override[0], max_open_positions=override[1], max_position_size=override[2]
    )
    pairs: list[tuple[Decimal | int | None, Decimal | int]] = list(
        zip(override, active, strict=True)
    )

    breached = {breach.key for breach in limits.breaches(current)}

    expected = {
        key
        for key, (value, limit) in zip(PROFILE_KEYS[:3], pairs, strict=True)
        if value is not None and value > limit
    }
    assert breached == expected
