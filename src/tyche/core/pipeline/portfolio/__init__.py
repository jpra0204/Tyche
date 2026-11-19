"""Stage 4, portfolio construction: every strategy's wishes as one proposed portfolio.

Available now (ADR-0022): ``PortfolioStage``, which turns each cycle's signals into a
``TargetPortfolioEvent``: one sleeve per strategy with its budget, and per instrument
the sum of each strategy's ``budget * weight``, each contribution keeping its own
stop. Weights are fractions of account equity; execution sizes them in shares
(ADR-0023).
"""

from tyche.core.pipeline.portfolio.stage import PortfolioError, PortfolioStage

__all__ = ["PortfolioError", "PortfolioStage"]
