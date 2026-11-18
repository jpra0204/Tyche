"""Stage 3, signals: the strategy plugin contract and the stage that calls plugins.

Available now (ADR-0021): the ``Strategy`` protocol and the ``StrategyContext`` it is
handed; ``HistoryView``, the read-only window of bars a strategy sees; ``BarWindows``,
which keeps those bars and fills them through the one warm-up path; the
``PositionBook`` protocol, empty (``NoPositions``) until execution exists; and
``SignalsStage``, which asks every strategy at each ``ScreeningEvent`` and publishes a
``SignalEvent`` per strategy and then a ``SignalsReadyEvent``.

The plugins themselves live in ``tyche.strategies``. Loading strategy instances and
their parameters from the workspace comes with per-strategy budgets (PR 13).
"""

from tyche.core.pipeline.signals.stage import SignalsError, SignalsStage, StrategyContractError
from tyche.core.pipeline.signals.strategy import (
    NoPositions,
    PositionBook,
    Strategy,
    StrategyContext,
)
from tyche.core.pipeline.signals.windows import BarWindows, HistoryError, HistoryView, WindowError

__all__ = [
    "BarWindows",
    "HistoryError",
    "HistoryView",
    "NoPositions",
    "PositionBook",
    "SignalsError",
    "SignalsStage",
    "Strategy",
    "StrategyContext",
    "StrategyContractError",
    "WindowError",
]
