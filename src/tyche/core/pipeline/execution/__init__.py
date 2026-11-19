"""Stage 6, execution: approved targets become orders (ADR-0022, ADR-0023).

Available now:

* ``ExecutionStage``: sizes approved weights into whole shares, crosses and nets them
  between sleeves, fits purchases to settled cash, and places market orders and
  protective stops. Accepts only ``ApprovedPortfolioEvent`` (ADR-0006).
* ``SleeveBook``: each strategy's own share of every position, with its resting stop.
  The signals stage reads it to show each strategy its positions (ADR-0021).
* ``AccountState``: Tyche's own view of the account, published as an ``AccountEvent``
  at every session close.
* ``split_pro_rata`` and ``fit_to_cash``: the allocation rules, pure functions.

Planned (Phase 2): the IBKR broker behind the same events, and reconciliation of
``AccountState`` against the broker's own record.
"""

from tyche.core.pipeline.execution.account import AccountState
from tyche.core.pipeline.execution.allocation import fit_to_cash, purchase_cost, split_pro_rata
from tyche.core.pipeline.execution.sleeves import RestingStop, SleeveBook, SleeveBookError
from tyche.core.pipeline.execution.stage import ExecutionError, ExecutionStage

__all__ = [
    "AccountState",
    "ExecutionError",
    "ExecutionStage",
    "RestingStop",
    "SleeveBook",
    "SleeveBookError",
    "fit_to_cash",
    "purchase_cost",
    "split_pro_rata",
]
