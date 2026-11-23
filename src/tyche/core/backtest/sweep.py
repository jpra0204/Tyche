"""Parameter sweeps: a grid of parameter values, the pick, and how much to trust it (ADR-0030).

A sweep runs one strategy once for every combination of the values in a grid, each
combination a backtest over the same days. It picks the combination with the highest
Sharpe ratio. The best of many tries looks better than it is, even when no combination
has any edge, so the pick is reported with a **deflated Sharpe ratio**: the chance
that its true Sharpe ratio is above zero, once the number of trials behind it and the
shape of its returns are taken into account.

This module does no I/O and runs nothing. It expands a grid into combinations
(``combinations``), picks the best of the measured trials (``pick``), computes the
deflated Sharpe ratio (``deflated_sharpe``), fingerprints a trial so that it is counted
once however often it runs (``trial_key``), and lists what should make a reader wary of
the pick (``overfitting_warnings``).

**The deflated Sharpe ratio**, from Bailey and López de Prado, "The Deflated Sharpe
Ratio: Correcting for Selection Bias, Backtest Overfitting and Non-Normality" (Journal
of Portfolio Management, 2014), equations 1 and 2. Every Sharpe ratio here is per
session, not annualised: the mean daily return over its sample standard deviation.

* ``SR0 = sqrt(V) * ((1 - g) * Z^-1(1 - 1/N) + g * Z^-1(1 - 1/(N e)))``: the Sharpe
  ratio the best of ``N`` independent trials is expected to reach when none has any
  skill. ``V`` is the variance of the trials' Sharpe ratios, ``g`` the
  Euler-Mascheroni constant, ``Z^-1`` the standard normal quantile. With one trial,
  nothing was selected and ``SR0`` is zero.
* ``DSR = Z((SR - SR0) * sqrt(T - 1) / sqrt(1 - skew * SR + (kurtosis - 1) / 4 * SR^2))``:
  ``SR`` is the pick's Sharpe ratio, ``T`` its number of daily returns, ``skew`` and
  ``kurtosis`` theirs (kurtosis is 3 for normal returns, not 0).

The paper's own example (``N = 100``, an annualised variance of ``1/2``, ``T = 1250``,
an annualised Sharpe of 2.5, skewness -3, kurtosis 10) gives 0.9004; a test checks it.

How Tyche feeds it, chosen once so every sweep means the same thing:

* ``N`` is **every distinct trial of the plugin ever recorded in the workspace**,
  this sweep's included, not only this sweep's combinations. A trial is a plugin, its
  version and its full parameters; running the same one again adds nothing.
* ``V`` is the sample variance of **this sweep's** trials' Sharpe ratios: they are the
  only ones measured over the same days as the pick. Earlier trials ran over other
  ranges.
* Trials that halted or could not be measured count in ``N`` but have no Sharpe ratio
  to add to ``V``.
"""

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from itertools import pairwise, product
from statistics import NormalDist, median
from typing import Any

from tyche.core.backtest.metrics import BacktestMetrics, EquityPoint

EULER_MASCHERONI = 0.5772156649015329
"""The Euler-Mascheroni constant, in the expected maximum of ``N`` normal draws."""

CONFIDENCE = 0.95
"""A pick whose deflated Sharpe ratio is below this is not significant. The paper's
example uses 95%."""

NEIGHBOUR_SHARE = Decimal("0.5")
"""A pick is an isolated peak if the median Sharpe ratio of its neighbours on the grid
is below this share of its own. Tyche's choice, not the paper's (ADR-0030)."""

_NORMAL = NormalDist()


class SweepError(ValueError):
    """A sweep cannot be planned or measured as asked."""


@dataclass(frozen=True, slots=True)
class Grid:
    """The values a sweep tries, parameter by parameter, in the order written.

    Attributes:
        values: Parameter name to the values tried, each list in its own order. Values
            are what the strategy file would hold: numbers, strings, lists, tables.
    """

    values: Mapping[str, tuple[Any, ...]]

    def __post_init__(self) -> None:
        if not self.values:
            raise SweepError("the grid names no parameter")
        for name, values in self.values.items():
            if not values:
                raise SweepError(f"grid: {name} lists no value")
            seen = [_canonical(v) for v in values]
            if len(set(seen)) != len(seen):
                raise SweepError(f"grid: {name} lists a value more than once")

    @property
    def size(self) -> int:
        """How many combinations the grid holds."""
        return math.prod(len(v) for v in self.values.values())


@dataclass(frozen=True, slots=True)
class Combination:
    """One point of a grid.

    Attributes:
        number: From 1, in the grid's order: the last parameter changes fastest.
        values: Each swept parameter's value.
        position: Each value's index in its parameter's list, in the grid's order.
    """

    number: int
    values: Mapping[str, Any]
    position: tuple[int, ...]


def combinations(grid: Grid) -> tuple[Combination, ...]:
    """Every combination of the grid, the last parameter changing fastest."""
    names = tuple(grid.values)
    ranges = [range(len(grid.values[name])) for name in names]
    return tuple(
        Combination(
            number=number,
            values={name: grid.values[name][i] for name, i in zip(names, position, strict=True)},
            position=tuple(position),
        )
        for number, position in enumerate(product(*ranges), start=1)
    )


def trial_key(plugin: str, version: str, parameters: Mapping[str, Any]) -> str:
    """A trial's fingerprint: the plugin, its version and its full parameters.

    Two runs with the same key are the same trial, wherever they were recorded.
    Parameter order and formatting do not matter; any change of value does.
    """
    payload = {"plugin": plugin, "version": version, "parameters": parameters}
    return "sha256:" + hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


# --- trials and the pick --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Trial:
    """One combination, run.

    Attributes:
        combination: What was tried.
        metrics: The run measured against the benchmark; ``None`` if it halted or
            could not be measured.
        session_sharpe: The Sharpe ratio per session; ``None`` if it cannot be computed.
        failure: Why there are no metrics, or ``None``.
    """

    combination: Combination
    metrics: BacktestMetrics | None
    session_sharpe: float | None
    failure: str | None = None

    @property
    def sharpe(self) -> Decimal | None:
        """The annualised Sharpe ratio, as every report shows it."""
        return self.metrics.strategy.sharpe if self.metrics is not None else None


def pick(trials: Sequence[Trial]) -> Trial | None:
    """The trial with the highest Sharpe ratio; the first in the grid's order on a tie.

    A trial without a Sharpe ratio is never picked. ``None`` if no trial has one.
    """
    best: Trial | None = None
    best_sharpe: Decimal | None = None
    for trial in trials:
        sharpe = trial.sharpe
        if sharpe is not None and (best_sharpe is None or sharpe > best_sharpe):
            best, best_sharpe = trial, sharpe
    return best


# --- the deflated Sharpe ratio --------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReturnMoments:
    """The daily returns of an equity series, summarised.

    Attributes:
        count: How many daily returns (``T``).
        sharpe: Mean over sample standard deviation, per session.
        skewness: Third standardised moment.
        kurtosis: Fourth standardised moment; 3 for normal returns.
    """

    count: int
    sharpe: float
    skewness: float
    kurtosis: float


def return_moments(points: Sequence[EquityPoint]) -> ReturnMoments | None:
    """Summarise the daily returns of ``points``; ``None`` with fewer than three
    returns or no variation."""
    if len(points) < 4:
        return None
    returns = [float(b.equity / a.equity - 1) for a, b in pairwise(points)]
    count = len(returns)
    mean = math.fsum(returns) / count
    deviations = [r - mean for r in returns]
    m2 = math.fsum(d * d for d in deviations) / count
    if m2 <= 0:
        return None
    m3 = math.fsum(d**3 for d in deviations) / count
    m4 = math.fsum(d**4 for d in deviations) / count
    sample_sd = math.sqrt(m2 * count / (count - 1))
    return ReturnMoments(
        count=count,
        sharpe=mean / sample_sd,
        skewness=m3 / m2**1.5,
        kurtosis=m4 / m2**2,
    )


def session_sharpe(points: Sequence[EquityPoint]) -> float | None:
    """The Sharpe ratio per session of ``points``, or ``None`` if it cannot be computed."""
    moments = return_moments(points)
    return moments.sharpe if moments is not None else None


def expected_max_sharpe(trials: int, variance: float) -> float:
    """``SR0``: what the best of ``trials`` independent trials is expected to reach
    with no skill, given the variance of their Sharpe ratios (equation 1)."""
    if trials < 1:
        raise SweepError(f"the number of trials must be at least 1, got {trials}")
    if variance < 0:
        raise SweepError(f"a variance cannot be negative, got {variance}")
    if trials == 1:
        return 0.0
    z = (1 - EULER_MASCHERONI) * _NORMAL.inv_cdf(1 - 1 / trials) + EULER_MASCHERONI * (
        _NORMAL.inv_cdf(1 - 1 / (trials * math.e))
    )
    return math.sqrt(variance) * z


def probabilistic_sharpe(moments: ReturnMoments, threshold: float) -> float:
    """The chance that the true Sharpe ratio is above ``threshold``, both per session,
    given the sample length and the shape of the returns (equation 2's ``Z[...]``)."""
    sr = moments.sharpe
    spread = 1 - moments.skewness * sr + (moments.kurtosis - 1) / 4 * sr * sr
    if spread <= 0:
        raise SweepError("the returns' skewness and kurtosis leave no spread to measure")
    return _NORMAL.cdf((sr - threshold) * math.sqrt(moments.count - 1) / math.sqrt(spread))


@dataclass(frozen=True, slots=True)
class DeflatedSharpe:
    """The pick's Sharpe ratio, deflated for the trials behind it.

    Attributes:
        trials: ``N``: every distinct trial of the plugin counted.
        variance: ``V``: the sample variance of the sweep's Sharpe ratios, per session.
        threshold: ``SR0``, per session: what the best of ``N`` trials reaches by luck.
        moments: The pick's daily returns: ``T``, its Sharpe ratio, skewness, kurtosis.
        probability: The deflated Sharpe ratio: the chance that the pick's true Sharpe
            ratio is above zero.
    """

    trials: int
    variance: float
    threshold: float
    moments: ReturnMoments
    probability: float

    @property
    def significant(self) -> bool:
        """True if the probability reaches ``CONFIDENCE``."""
        return self.probability >= CONFIDENCE


def deflated_sharpe(
    moments: ReturnMoments, sharpes: Sequence[float], trials: int
) -> DeflatedSharpe:
    """Deflate the pick's Sharpe ratio for ``trials`` trials, ``sharpes`` being the
    per-session Sharpe ratios measured over the same days (the pick's among them).

    Raises:
        SweepError: Fewer trials counted than measured, or more than one trial counted
            but fewer than two Sharpe ratios to take a variance from.
    """
    if trials < len(sharpes):
        raise SweepError(f"{trials} trials counted, but {len(sharpes)} were measured")
    if trials > 1 and len(sharpes) < 2:
        raise SweepError(
            f"{trials} trials are counted, but fewer than two Sharpe ratios were measured "
            "over these days, so their variance is unknown"
        )
    variance = _sample_variance(sharpes) if len(sharpes) >= 2 else 0.0
    threshold = expected_max_sharpe(trials, variance)
    return DeflatedSharpe(
        trials=trials,
        variance=variance,
        threshold=threshold,
        moments=moments,
        probability=probabilistic_sharpe(moments, threshold),
    )


def _sample_variance(values: Sequence[float]) -> float:
    mean = math.fsum(values) / len(values)
    return math.fsum((v - mean) ** 2 for v in values) / (len(values) - 1)


# --- warnings -------------------------------------------------------------------------


def overfitting_warnings(
    grid: Grid,
    trials: Sequence[Trial],
    best: Trial | None,
    deflated: DeflatedSharpe | None,
    deflation_error: str | None,
) -> tuple[str, ...]:
    """What should make a reader wary of the pick, one plain sentence each.

    * The deflated Sharpe ratio is below ``CONFIDENCE``, or could not be computed.
    * The pick sits at the end of a parameter's list of three values or more: the best
      value may lie beyond the grid, and widening it adds trials.
    * The pick is an isolated peak: its neighbours' median Sharpe ratio is below
      ``NEIGHBOUR_SHARE`` of its own.
    * Some trials halted or could not be measured.
    """
    warnings: list[str] = []
    if best is None:
        return ("No trial has a Sharpe ratio, so nothing was picked.",)
    if deflated is None:
        warnings.append(f"The deflated Sharpe ratio could not be computed: {deflation_error}.")
    elif not deflated.significant:
        warnings.append(
            f"After {deflated.trials} trials, the chance that the pick's true Sharpe ratio "
            f"is above zero is {deflated.probability:.1%}, below {CONFIDENCE:.0%}: the pick "
            "is not distinguishable from the best of that many tries with no edge."
        )
    names = tuple(grid.values)
    for name, index in zip(names, best.combination.position, strict=True):
        count = len(grid.values[name])
        if count >= 3 and index in (0, count - 1):
            end = "first" if index == 0 else "last"
            warnings.append(
                f"The pick's {name} is the {end} value of the grid "
                f"({_shown(grid.values[name][index])}): the best value may lie beyond it, "
                "and widening the grid adds trials."
            )
    neighbours = [t.sharpe for t in trials if _adjacent(t, best) and t.sharpe is not None]
    best_sharpe = best.sharpe
    if neighbours and best_sharpe is not None and best_sharpe > 0:
        middle = median(neighbours)
        if middle < best_sharpe * NEIGHBOUR_SHARE:
            warnings.append(
                f"The pick is an isolated peak: its {len(neighbours)} neighbours on the grid "
                f"have a median Sharpe ratio of {middle:.2f} against its {best_sharpe:.2f}. "
                "A small change of parameters loses most of the result."
            )
    failed = [t for t in trials if t.metrics is None]
    if failed:
        warnings.append(
            f"{len(failed)} of {len(trials)} trials halted or could not be measured; they "
            "count as trials but add nothing to the variance."
        )
    return tuple(warnings)


def _adjacent(trial: Trial, best: Trial) -> bool:
    """True if ``trial`` differs from ``best`` by one step of one parameter."""
    pairs = zip(trial.combination.position, best.combination.position, strict=True)
    return sum(abs(a - b) for a, b in pairs) == 1


def _shown(value: Any) -> str:
    return value if isinstance(value, str) else _canonical(value)
