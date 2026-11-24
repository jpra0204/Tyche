"""The IBKR broker adapter for the paper account (Phase 2, PR 11; ADR-0041, ADR-0042).

``IBKRBroker`` implements the ``Broker`` port. It talks to IB Gateway through the
small ``IBClient`` protocol: ``IbAsyncClient`` in real use, a fake in the tests.
"""

from tyche.adapters.brokers.ibkr.broker import (
    PRIMARY_EXCHANGES,
    SETTLED_CASH_TAG,
    IBKRBroker,
    IBKRBrokerError,
    OpenOrderStyle,
    SyncReport,
    Unaccounted,
)
from tyche.adapters.brokers.ibkr.client import (
    ContractQuery,
    GatewaySettings,
    IBClient,
    IBKRAccountError,
    IBKRConnectionError,
    IBKRContractError,
    IBKRError,
    OrderTicket,
    ReportedExecution,
    ReportedHolding,
    ReportedOrder,
    ReportedValue,
)
from tyche.adapters.brokers.ibkr.ib_async_client import IbAsyncClient

__all__ = [
    "PRIMARY_EXCHANGES",
    "SETTLED_CASH_TAG",
    "ContractQuery",
    "GatewaySettings",
    "IBClient",
    "IBKRAccountError",
    "IBKRBroker",
    "IBKRBrokerError",
    "IBKRConnectionError",
    "IBKRContractError",
    "IBKRError",
    "IbAsyncClient",
    "OpenOrderStyle",
    "OrderTicket",
    "ReportedExecution",
    "ReportedHolding",
    "ReportedOrder",
    "ReportedValue",
    "SyncReport",
    "Unaccounted",
]
