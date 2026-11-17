"""Ports: the interfaces the core uses to reach the outside world.

Planned (Phase 1 onward): ``Clock``, ``Calendar``, ``DataProvider``, ``Broker``,
``Notifier``, ``LLMProvider`` and the storage ports. Each is a ``typing.Protocol``;
concrete implementations live in ``tyche.adapters`` (or ``tyche.core.sim`` for the
simulated ones).
"""
