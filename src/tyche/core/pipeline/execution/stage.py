"""ExecutionStage: pipeline stage 6, approved weights become orders (ADR-0022, ADR-0023).

It acts on ``ApprovedPortfolioEvent`` only (ADR-0006). At each decision it:

1. **Reads each sleeve and instrument** the way ADR-0022 says: a contribution's weight,
   zero for an instrument decided on and not targeted, or keep what is held. When the
   approval carries the drawdown kill's halt, everything is kept and no order is sent
   (ADR-0035); stops already resting stay at the broker.
2. **Sizes** each weight in whole shares of the account's equity at the last close,
   rounding down. A holding within the rebalance band of its target is kept as it is;
   entries and exits always trade.
3. **Crosses** between sleeves first: shares one sleeve gives up and another wants
   move between them in the sleeve book at the last close, with no order and no
   commission. What is left is **netted** into one market order per instrument.
4. **Fits purchases to the guardrails' money caps**, when the run applies them
   (ADR-0034): each purchase within the order cap, and all of them within what is left
   under the capital cap after the cycle's sales, valued at the last close plus the
   price buffer. A purchase over a cap shrinks to the whole shares that fit, and each
   cut is published as a ``RiskEvent``; sales are never cut.
5. **Fits purchases to cash**: together they must be payable from the buying power at
   the next open, at the last close plus the price buffer, costs included; if not,
   every purchase shrinks in proportion.
6. **Publishes** an ``ExecutionPlanEvent``, then cancellations, then the orders: sales
   first, then purchases, then any stop that must be placed again.

With money caps, weights are sized on the account's equity or the capital cap,
whichever is lower: money above the cap, gains included, stays in cash until Pablo
raises the cap. Long only and no leverage hold in every run: sales and resting stops
never add up to more shares than the account holds, and purchases never cost more
than the buying power. Execution cannot break either by design, so a breach is a bug
and halts the run.

Fills come back as ``FillEvent``s. A sleeve's share of a netted fill is in proportion
to what each sleeve the order serves is still owed. When a purchase fills, each sleeve
that asked for a stop gets one protective stop for all its shares, placed then: it
works from the next session, so a stop can never sell shares bought the same day,
which would be free riding (ADR-0020).

Order ids are derived from the decision (its time, the instrument, the side or the
sleeve), or for a stop placed after a fill, from that fill: the same decision always
gives the same ids, and a decision handled once is not handled again.

A broken assumption (no account snapshot, a market order still open at a decision, the
sleeves not adding up to the account's positions, a sale that would go short, a
purchase the cash cannot pay for) is a bug, and halts the run.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from tyche.core.domain import (
    Account,
    Currency,
    ExecutionRules,
    Instrument,
    Money,
    MoneyLimits,
    Order,
    OrderAdjustment,
    OrderState,
    OrderType,
    PlanLine,
    PlanNote,
    RiskAction,
    RiskRule,
    Side,
    TimeInForce,
    TradingCosts,
    whole_shares,
)
from tyche.core.events import (
    KEEP,
    AccountEvent,
    ApprovedPortfolioEvent,
    BarEvent,
    CancelRequestEvent,
    Envelope,
    EventBus,
    ExecutionPlanEvent,
    FillEvent,
    OrderEvent,
    RiskEvent,
    SessionEvent,
    SessionPhase,
)
from tyche.core.pipeline.execution.allocation import (
    cap_order,
    fit_to_cash,
    fit_to_value,
    purchase_cost,
    split_pro_rata,
)
from tyche.core.pipeline.execution.sleeves import RestingStop, SleeveBook
from tyche.core.ports import Calendar, OutOfCalendarRangeError

SUBSCRIBER = "execution"


class ExecutionError(Exception):
    """Execution's inputs broke an assumption it relies on. A bug, not a market event."""


@dataclass(slots=True)
class _Tracked:
    """An order execution created, until it finishes.

    ``owed`` is, for a netted order, the shares still owed to each sleeve it serves;
    ``strategy_id`` is, for a stop, the sleeve whose shares it protects.
    """

    state: OrderState
    owed: dict[str, Decimal] = field(default_factory=dict)
    strategy_id: str | None = None

    @property
    def is_stop(self) -> bool:
        return self.state.order.order_type is OrderType.STOP


@dataclass(slots=True)
class _Plan:
    """One sleeve's plan for one instrument while a decision is worked out."""

    held: Decimal
    target: Decimal
    note: PlanNote | None = None
    crossed: Decimal = Decimal(0)
    ordered: Decimal = Decimal(0)


def _key(instrument: Instrument) -> tuple[str, str]:
    return instrument.symbol, instrument.exchange


def _label(instrument: Instrument) -> str:
    return f"{instrument.symbol}.{instrument.exchange}"


class ExecutionStage:
    """Pipeline stage 6. Turns every ``ApprovedPortfolioEvent`` into orders.

    Subscribe it after the account state, so that each decision finds the snapshot of
    the same close.

    Args:
        bus: The run's event bus.
        book: The sleeve book, shared with the signals stage. Starts empty.
        costs: Slippage, commission and fees, to size purchases the cash can pay for.
        calendars: A calendar for every calendar code the traded instruments use, to
            know when cash settles.
        rules: The market profile's execution rules.
        money: The guardrails' money caps by currency, or ``None`` for a run that does
            not apply them: research backtests keep their own starting cash (ADR-0034).
    """

    def __init__(
        self,
        bus: EventBus,
        book: SleeveBook,
        costs: TradingCosts,
        calendars: Mapping[str, Calendar],
        rules: ExecutionRules,
        money: Mapping[Currency, MoneyLimits] | None = None,
    ) -> None:
        self._bus = bus
        self._book = book
        self._costs = costs
        self._calendars = dict(calendars)
        self._rules = rules
        self._money = dict(money) if money is not None else {}

        self._account: AccountEvent | None = None
        self._closes: dict[Instrument, Money] = {}
        self._days: dict[str, date] = {}
        self._orders: dict[str, _Tracked] = {}
        self._wanted_stops: dict[tuple[str, Instrument], Money] = {}
        self._handled: set[datetime] = set()

        bus.subscribe(SessionEvent, self._on_session, name=SUBSCRIBER)
        bus.subscribe(BarEvent, self._on_bar, name=SUBSCRIBER)
        bus.subscribe(AccountEvent, self._on_account, name=SUBSCRIBER)
        bus.subscribe(ApprovedPortfolioEvent, self._on_approved, name=SUBSCRIBER)
        bus.subscribe(FillEvent, self._on_fill, name=SUBSCRIBER)
        bus.subscribe(OrderEvent, self._on_order, name=SUBSCRIBER)

    # --- what the stage is told ------------------------------------------------------

    def _on_session(self, envelope: Envelope[SessionEvent]) -> None:
        if envelope.event.phase is SessionPhase.OPEN:
            session = envelope.event.session
            self._days[session.calendar] = session.day

    def _on_bar(self, envelope: Envelope[BarEvent]) -> None:
        bar = envelope.event.bar
        self._closes[bar.instrument] = Money(Decimal(repr(bar.close)), bar.instrument.currency)

    def _on_account(self, envelope: Envelope[AccountEvent]) -> None:
        self._account = envelope.event

    def _on_order(self, envelope: Envelope[OrderEvent]) -> None:
        state = envelope.event.state
        order_id = state.order.client_order_id
        tracked = self._orders.get(order_id)
        if tracked is None:
            return
        tracked.state = state
        if not state.status.is_terminal:
            return
        del self._orders[order_id]
        if tracked.strategy_id is not None:
            instrument = state.order.instrument
            resting = self._book.stop(tracked.strategy_id, instrument)
            if resting is not None and resting.client_order_id == order_id:
                self._book.set_stop(tracked.strategy_id, instrument, None)

    def _on_fill(self, envelope: Envelope[FillEvent]) -> None:
        fill = envelope.event.fill
        tracked = self._orders.get(fill.client_order_id)
        if tracked is None:
            raise ExecutionError(f"fill {fill.fill_id} is for {fill.client_order_id}, not ours")
        instrument = fill.instrument

        if tracked.strategy_id is not None:  # a stop: all its shares are its sleeve's
            self._book.remove(tracked.strategy_id, instrument, fill.quantity)
            return

        shares = split_pro_rata(fill.quantity, tracked.owed)
        for strategy_id, quantity in shares.items():
            if quantity == 0:
                continue
            tracked.owed[strategy_id] -= quantity
            if tracked.owed[strategy_id] == 0:
                del tracked.owed[strategy_id]
            if fill.side is Side.BUY:
                self._book.add(strategy_id, instrument, quantity, fill.price, fill.trade_date)
            else:
                self._book.remove(strategy_id, instrument, quantity)

        if fill.side is Side.BUY:
            for strategy_id, quantity in sorted(shares.items()):
                wanted = self._wanted_stops.get((strategy_id, instrument))
                if quantity and wanted is not None:
                    self._replace_stop(
                        strategy_id,
                        instrument,
                        wanted,
                        self._book.held(strategy_id, instrument),
                        order_id=f"{fill.fill_id}-stop-{strategy_id}",
                        at=envelope.occurred_at,
                        reason=f"protective stop for {strategy_id} after fill {fill.fill_id}",
                    )

    # --- a decision ------------------------------------------------------------------

    def _on_approved(self, envelope: Envelope[ApprovedPortfolioEvent]) -> None:
        approved = envelope.event
        if approved.as_of in self._handled:
            return  # the same decision again: its orders already exist
        self._handled.add(approved.as_of)
        account = self._snapshot(approved.as_of)
        self._require_no_open_market_orders()
        self._require_book_matches(account)

        stamp = approved.as_of.strftime("%Y%m%dT%H%M%SZ")
        at = envelope.occurred_at
        sleeve_ids = {s.strategy_id for s in approved.sleeves}
        instruments = sorted(
            {t.instrument for t in approved.targets} | set(self._book.instruments), key=_key
        )

        plans: dict[tuple[str, Instrument], _Plan] = {}
        purchases: dict[Instrument, Decimal] = {}
        owed_on_purchase: dict[Instrument, dict[str, Decimal]] = {}
        sales: dict[Instrument, dict[str, Decimal]] = {}

        for instrument in instruments:
            mine = self._plan_instrument(approved, account, instrument, sleeve_ids)
            plans.update({(s, instrument): p for s, p in mine.items()})
            buyers = {s: p.target - p.held for s, p in mine.items() if p.target > p.held}
            sellers = {s: p.held - p.target for s, p in mine.items() if p.target < p.held}
            crossing = min(
                sum(buyers.values(), start=Decimal(0)), sum(sellers.values(), start=Decimal(0))
            )
            if crossing > 0:
                out = split_pro_rata(crossing, sellers)
                into = split_pro_rata(crossing, buyers)
                day = self._day(instrument)
                for strategy_id, quantity in out.items():
                    if quantity:
                        self._book.remove(strategy_id, instrument, quantity)
                        mine[strategy_id].crossed = -quantity
                        sellers[strategy_id] -= quantity
                for strategy_id, quantity in into.items():
                    if quantity:
                        self._book.add(
                            strategy_id, instrument, quantity, self._close(instrument), day
                        )
                        mine[strategy_id].crossed = quantity
                        buyers[strategy_id] -= quantity
            buyers = {s: q for s, q in buyers.items() if q > 0}
            sellers = {s: q for s, q in sellers.items() if q > 0}
            if buyers:
                purchases[instrument] = sum(buyers.values(), start=Decimal(0))
                owed_on_purchase[instrument] = buyers
            elif sellers:
                sales[instrument] = sellers
                for strategy_id, quantity in sellers.items():
                    mine[strategy_id].ordered = -quantity

        fitted, cuts = self._fit_purchases(purchases, account, sales)
        capped = {cut.instrument for cut in cuts}
        for instrument, wanted_total in purchases.items():
            owed = owed_on_purchase[instrument]
            quantity = fitted[instrument]
            if quantity < wanted_total:
                note = PlanNote.CAPPED if instrument in capped else PlanNote.CASH_LIMITED
                given = split_pro_rata(quantity, owed)
                for strategy_id, wanted in owed.items():
                    if given[strategy_id] < wanted:
                        plans[(strategy_id, instrument)].note = note
                owed = {s: q for s, q in given.items() if q > 0}
                owed_on_purchase[instrument] = owed
            for strategy_id, owed_quantity in owed.items():
                plans[(strategy_id, instrument)].ordered = owed_quantity

        for cut in cuts:
            self._bus.publish(RiskEvent(approved.as_of, approved.profile, cut))
        sized_on = tuple(
            self._trading_equity(account, currency)
            for currency in sorted({i.currency for i in instruments})
        )
        self._bus.publish(ExecutionPlanEvent(approved.as_of, _lines(plans), sized_on))

        if approved.halt is not None:
            # Everything was kept, so there is nothing to send; resting stops stay as
            # they are, not even placed again (ADR-0035).
            if sales or owed_on_purchase:
                raise ExecutionError("a halted decision planned an order")
            return
        for instrument, owed in sorted(sales.items(), key=lambda item: _key(item[0])):
            self._send_market(instrument, Side.SELL, owed, stamp, at)
        self._update_stops(sales, stamp, at)
        for instrument in sorted(owed_on_purchase, key=_key):
            owed = owed_on_purchase[instrument]
            if owed:
                self._send_market(instrument, Side.BUY, owed, stamp, at)
        self._require_long_only(account, sales)

    def _plan_instrument(
        self,
        approved: ApprovedPortfolioEvent,
        account: Account,
        instrument: Instrument,
        sleeve_ids: set[str],
    ) -> dict[str, _Plan]:
        """Each sleeve's target for one instrument, in whole shares, after the band."""
        plans: dict[str, _Plan] = {}
        for strategy_id in sorted(sleeve_ids | set(self._book.holders(instrument))):
            held = self._book.held(strategy_id, instrument)
            wanted = approved.wanted(strategy_id, instrument) if strategy_id in sleeve_ids else KEEP
            if wanted is KEEP:
                if held:
                    kept = PlanNote.HALTED if approved.halt is not None else PlanNote.KEEP
                    plans[strategy_id] = _Plan(held, held, kept)
                continue

            weight = wanted.weight if wanted is not None else Decimal(0)
            note: PlanNote | None = None
            target = Decimal(0)
            if weight > 0:
                equity = self._trading_equity(account, instrument.currency)
                target = whole_shares(equity * weight, self._close(instrument))
                if target == 0:
                    note = PlanNote.BELOW_ONE_SHARE
                elif self._rules.within_band(held, target):
                    target, note = held, PlanNote.WITHIN_BAND

            stop = wanted.stop_price if wanted is not None and target > 0 else None
            if stop is None:
                self._wanted_stops.pop((strategy_id, instrument), None)
            else:
                self._wanted_stops[(strategy_id, instrument)] = stop
            if held or target or note:
                plans[strategy_id] = _Plan(held, target, note)
        return plans

    def _fit_purchases(
        self,
        purchases: Mapping[Instrument, Decimal],
        account: Account,
        sales: Mapping[Instrument, Mapping[str, Decimal]],
    ) -> tuple[dict[Instrument, Decimal], list[OrderAdjustment]]:
        """The cycle's purchases within the money caps, then the buying power at the next open.

        Returns the shares to buy of each instrument, and every cut the caps made.
        """
        fitted: dict[Instrument, Decimal] = {}
        cuts: list[OrderAdjustment] = []
        for currency in sorted({i.currency for i in purchases}):
            wanted = {i: q for i, q in purchases.items() if i.currency is currency}
            buffer = 1 + self._rules.price_buffer
            references = {i: self._close(i) * buffer for i in wanted}
            limits = self._money.get(currency)
            if limits is not None:
                wanted = self._fit_caps(wanted, references, account, sales, limits, cuts)
            settles_by = min(self._next_session(i.calendar) for i in wanted)
            cash = account.cash(currency).buying_power(settles_by)
            plan = fit_to_cash(wanted, references, self._costs, cash)
            spent = Money.zero(currency)
            for instrument, quantity in plan.items():
                spent += purchase_cost(quantity, references[instrument], self._costs)
            if spent > cash:  # no leverage: fit_to_cash makes this impossible
                raise ExecutionError(
                    f"purchases would cost {spent}, more than the buying power of {cash}"
                )
            fitted.update(plan)
        return fitted, cuts

    def _fit_caps(
        self,
        wanted: Mapping[Instrument, Decimal],
        references: Mapping[Instrument, Money],
        account: Account,
        sales: Mapping[Instrument, Mapping[str, Decimal]],
        limits: MoneyLimits,
        cuts: list[OrderAdjustment],
    ) -> dict[Instrument, Decimal]:
        """Each purchase within the order cap, then all within the capital cap (ADR-0034)."""
        capped: dict[Instrument, Decimal] = {}
        for instrument in sorted(wanted, key=_key):
            before = wanted[instrument]
            reference = references[instrument]
            after = cap_order(before, reference, limits.order)
            if after < before:
                cuts.append(
                    _cut(
                        RiskRule.MAX_ORDER_VALUE,
                        instrument,
                        before,
                        after,
                        limits.order,
                        f"max_order_value is {limits.order}: {before} shares at "
                        f"{reference.round_to(2)} (the last close plus the price buffer) "
                        f"are worth {(reference * before).round_to(2)}; {after} fit",
                    )
                )
            capped[instrument] = after

        currency = limits.capital.currency
        invested = Money.zero(currency)
        for position in account.positions:
            instrument = position.instrument
            if instrument.currency is currency:
                selling = sum(sales.get(instrument, {}).values(), start=Decimal(0))
                invested += self._close(instrument) * (position.quantity - selling)
        room = limits.capital - invested
        fitted = fit_to_value(capped, references, room)
        for instrument in sorted(fitted, key=_key):
            before, after = capped[instrument], fitted[instrument]
            if after < before:
                cuts.append(
                    _cut(
                        RiskRule.MAX_TOTAL_CAPITAL,
                        instrument,
                        before,
                        after,
                        limits.capital,
                        f"max_total_capital is {limits.capital}: {invested.round_to(2)} stays "
                        f"invested after this cycle's sales, leaving {room.round_to(2)} for "
                        "purchases at the last close plus the price buffer; every purchase "
                        "shrinks in proportion",
                    )
                )
        return fitted

    def _trading_equity(self, account: Account, currency: Currency) -> Money:
        """The equity weights are sized on: the account's, or the capital cap if lower."""
        equity = account.equity(currency)
        limits = self._money.get(currency)
        return limits.trading_equity(equity) if limits is not None else equity

    def _update_stops(
        self, sales: Mapping[Instrument, Mapping[str, Decimal]], stamp: str, at: datetime
    ) -> None:
        """Bring every sleeve's resting stop in line with what it wants and will hold.

        A stop covers the shares the sleeve holds now, less any it is selling at the next
        open. A stop whose price or size is wrong is cancelled and placed again; one no
        longer wanted is cancelled. Shares still to be bought get their stop when they
        fill, never before.
        """
        keys = {(s, i) for s, i, _ in self._book.stops} | set(self._wanted_stops)
        for strategy_id, instrument in sorted(keys, key=lambda k: (k[0], *_key(k[1]))):
            selling = sales.get(instrument, {}).get(strategy_id, Decimal(0))
            protect = self._book.held(strategy_id, instrument) - selling
            self._replace_stop(
                strategy_id,
                instrument,
                self._wanted_stops.get((strategy_id, instrument)),
                protect,
                order_id=f"{stamp}-{_label(instrument)}-stop-{strategy_id}",
                at=at,
                reason=f"protective stop for {strategy_id}",
            )

    # --- sending -----------------------------------------------------------------------

    def _send_market(
        self,
        instrument: Instrument,
        side: Side,
        owed: Mapping[str, Decimal],
        stamp: str,
        at: datetime,
    ) -> None:
        quantity = sum(owed.values(), start=Decimal(0))
        served = ", ".join(f"{s} {q}" for s, q in sorted(owed.items()))
        order = Order(
            client_order_id=f"{stamp}-{_label(instrument)}-{side}",
            instrument=instrument,
            side=side,
            quantity=quantity,
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
            created_at=at,
            reason=f"{side} {quantity} {instrument} for {served}",
        )
        self._submit(_Tracked(OrderState(order), owed=dict(owed)))

    def _replace_stop(
        self,
        strategy_id: str,
        instrument: Instrument,
        wanted: Money | None,
        quantity: Decimal,
        *,
        order_id: str,
        at: datetime,
        reason: str,
    ) -> None:
        """Make the sleeve's resting stop ``wanted`` for ``quantity`` shares, or none."""
        resting = self._book.stop(strategy_id, instrument)
        if resting is not None:
            tracked = self._orders.get(resting.client_order_id)
            remaining = tracked.state.remaining if tracked else Decimal(0)
            if wanted is not None and resting.price == wanted and remaining == quantity:
                return  # already right
            self._bus.publish(CancelRequestEvent(resting.client_order_id, f"replaced: {reason}"))
            self._book.set_stop(strategy_id, instrument, None)
        if wanted is None or quantity <= 0:
            return
        order = Order(
            client_order_id=order_id,
            instrument=instrument,
            side=Side.SELL,
            quantity=quantity,
            order_type=OrderType.STOP,
            time_in_force=TimeInForce.GTC,
            created_at=at,
            reason=f"{reason}: {quantity} shares at {wanted}",
            stop_price=wanted,
        )
        self._submit(_Tracked(OrderState(order), strategy_id=strategy_id))
        self._book.set_stop(strategy_id, instrument, RestingStop(order_id, wanted))

    def _submit(self, tracked: _Tracked) -> None:
        order_id = tracked.state.order.client_order_id
        if order_id in self._orders:
            raise ExecutionError(f"order id {order_id} is already in use")
        tracked.state = tracked.state.submit()
        self._orders[order_id] = tracked
        self._bus.publish(OrderEvent(tracked.state))

    # --- what a decision needs -----------------------------------------------------------

    def _snapshot(self, as_of: datetime) -> Account:
        if self._account is None or self._account.as_of != as_of:
            seen = self._account.as_of.isoformat() if self._account else "none"
            raise ExecutionError(
                f"the decision at {as_of.isoformat()} has no account snapshot from the same "
                f"close (latest: {seen})"
            )
        return self._account.account

    def _require_no_open_market_orders(self) -> None:
        open_orders = sorted(o for o, t in self._orders.items() if not t.is_stop)
        if open_orders:
            raise ExecutionError(
                f"market orders still open at a decision: {', '.join(open_orders)}; a day "
                "order should have filled or expired at the close"
            )

    def _require_long_only(
        self, account: Account, sales: Mapping[Instrument, Mapping[str, Decimal]]
    ) -> None:
        """No instrument may have more shares to sell than the account holds (long only).

        Counts this cycle's market sales and every stop left resting for the next
        session. Execution sizes stops to what each sleeve keeps, so this cannot fail
        unless something is wrong.
        """
        held = {p.instrument: p.quantity for p in account.positions}
        selling = {i: sum(owed.values(), start=Decimal(0)) for i, owed in sales.items()}
        for _, instrument, stop in self._book.stops:
            tracked = self._orders.get(stop.client_order_id)
            remaining = tracked.state.remaining if tracked else Decimal(0)
            selling[instrument] = selling.get(instrument, Decimal(0)) + remaining
        for instrument in sorted(selling, key=_key):
            have = held.get(instrument, Decimal(0))
            if selling[instrument] > have:
                raise ExecutionError(
                    f"long only: sales and resting stops would sell {selling[instrument]} "
                    f"{instrument}, but the account holds {have}"
                )

    def _require_book_matches(self, account: Account) -> None:
        held = {p.instrument: p.quantity for p in account.positions}
        for instrument in sorted(set(held) | set(self._book.instruments), key=_key):
            in_book = self._book.total(instrument)
            in_account = held.get(instrument, Decimal(0))
            if in_book != in_account:
                raise ExecutionError(
                    f"the sleeves hold {in_book} {instrument}, the account {in_account}"
                )

    def _close(self, instrument: Instrument) -> Money:
        close = self._closes.get(instrument)
        if close is None:
            raise ExecutionError(f"no closing price seen for {instrument}")
        return close

    def _day(self, instrument: Instrument) -> date:
        day = self._days.get(instrument.calendar)
        if day is None:
            raise ExecutionError(f"no {instrument.calendar} session seen yet")
        return day

    def _next_session(self, calendar: str) -> date:
        """The day of the next session, when today's due cash will have settled.

        At the end of a calendar's loaded range there is no next session to look up;
        then only cash already settled today counts, the stricter reading.
        """
        today = self._days.get(calendar)
        if today is None:
            raise ExecutionError(f"no {calendar} session seen yet")
        try:
            return self._calendars[calendar].next_session(today).day
        except OutOfCalendarRangeError:
            return today


def _lines(plans: Mapping[tuple[str, Instrument], _Plan]) -> tuple[PlanLine, ...]:
    ordered = sorted(plans, key=lambda k: (k[0], *_key(k[1])))
    return tuple(
        PlanLine(
            strategy_id=strategy_id,
            instrument=instrument,
            held=plans[(strategy_id, instrument)].held,
            target=plans[(strategy_id, instrument)].target,
            crossed=plans[(strategy_id, instrument)].crossed,
            ordered=plans[(strategy_id, instrument)].ordered,
            note=plans[(strategy_id, instrument)].note,
        )
        for strategy_id, instrument in ordered
    )


def _cut(
    rule: RiskRule,
    instrument: Instrument,
    before: Decimal,
    after: Decimal,
    limit: Money,
    reason: str,
) -> OrderAdjustment:
    action = RiskAction.BLOCK if after == 0 else RiskAction.SHRINK
    return OrderAdjustment(rule, action, instrument, before, after, limit, reason)
