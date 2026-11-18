"""Stage 1, universe: which instruments are eligible.

Available now: ``UniverseStage``, which applies the market profile's ``UniverseRules``
(profile membership, a current bar, clean recent data, enough history, a minimum price
and a minimum average dollar volume) at every ``DataReadyEvent`` and publishes a
``UniverseEvent`` listing every instrument as eligible or excluded with its reason.
"""

from tyche.core.pipeline.universe.stage import UniverseError, UniverseStage

__all__ = ["UniverseError", "UniverseStage"]
