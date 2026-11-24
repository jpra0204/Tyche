# IBKR: the API, orders and the paper account

**Checked on 2026-11-23** against the pages listed under [Sources](#sources), for Phase 2, PR 10. Nothing here is from memory. Where IBKR's own pages disagree, or say nothing, the page says so, and [section 10](#10-to-confirm-on-the-paper-account) lists what to confirm on the paper account. Re-check before PR 11 if a month has passed, and before going live.

Section 12 adds what PR 11 read on 2026-11-24, section 13 what PR 13 read the same day. This page records facts. The choices built on them are in [ADR-0041](../adr/0041-orders-and-identity-at-ibkr.md), accepted on 2026-11-24, and [ADR-0042](../adr/0042-ibkr-paper-adapter-at-most-once-orders.md), the adapter itself. Costs, settlement and fractional shares are on the companion page, [IBKR Canada: costs and settlement](ibkr-canada-costs-and-settlement.md).

## 1. The client library: `ib_async`

| Fact | Source |
|---|---|
| Latest release **2.1.0**, published 2025-12-08. Earlier: 2.0.1 (2025-06-22), 1.0.3 (2024-07-06) | PyPI |
| Licence **BSD 2-Clause** (the `LICENSE` file's first line: "BSD 2-Clause License"). PyPI's metadata says only "BSD", with the classifier "Other/Proprietary License" | GitHub `LICENSE`; PyPI |
| Requires Python 3.10 or later. PyPI's classifiers list 3.14; the repository's own `pyproject.toml` lists 3.10 to 3.13 | PyPI; GitHub `pyproject.toml` |
| Its CI runs Python 3.10 to 3.14, but **only mypy and ruff**, not the tests. That 2.1.0 works on 3.14 is not shown by its CI | GitHub workflow `test.yml` |
| Runtime dependencies: `aeventkit` (>=2.1.0, <3.0.0; BSD), `nest_asyncio` (any; BSD-2-Clause), **`tzdata` (>=2025.2, <2026.0)** | PyPI metadata; `pyproject.toml` |
| `nest_asyncio`'s repository is **archived**; its last release, 1.6.0, is from 2024-01-21 | GitHub API; PyPI |
| Maintained by Matt Stancliff under the `ib-api-reloaded` organisation. It is the renamed `ib_insync`: its author, Ewald de Wit, died in early 2024, and the project moved because the original repositories could no longer be changed | README, History section |
| "This project is not affiliated with Interactive Brokers Group, Inc." It implements IBKR's binary protocol itself; IBKR's `ibapi` package is not needed | README |
| No minimum TWS or IB Gateway version is stated | README |
| The README's example ports are 7497 for TWS and **4001 for IB Gateway, which is the live Gateway's default** (section 2) | README |

**Checked in this repository on 2026-11-23**, in a scratch copy of the project: `uv add ib_async` resolves to 2.1.0 and **moves `tzdata` from 2026.6 down to 2025.3**, because of the `<2026.0` bound. Today `tzdata` comes from `exchange_calendars` and `python-dateutil` with no upper bound. PR 11 decides what to do about it ([ADR-0041](../adr/0041-orders-and-identity-at-ibkr.md)).

## 2. IB Gateway: ports, sessions and restarts

| Fact | Source |
|---|---|
| Default socket ports: **TWS live 7496, TWS paper 7497, IB Gateway live 4001, IB Gateway paper 4002.** All can be changed in the API settings; the client must use the port the gateway listens on | IBKR Excel RTD docs, *Connection parameters* |
| A port is therefore **not proof of paper or live**: a gateway can be set to any port | Same |
| The API needs "ActiveX and Socket Clients" on and "Read-Only API" off | TWS API, *TWS configuration for API use* |
| Up to 32 API clients per TWS or Gateway session, told apart by client id. A second connection with a client id in use fails (error 326) | TWS API, *Connectivity behavior*; error codes |
| On connection the gateway sends **the account number(s) of the session**, the next valid order id and the time | TWS API, *Establishing an API connection* |
| The user must type the username and password into a login window; "a headless session of TWS or IBGW without a GUI is not supported" | TWS API, *Download TWS or IB Gateway* |
| Both are designed to restart daily. From version 974, an auto-restart lets them run Sunday to Sunday; after the Saturday-night server reset the credentials must be entered again. The reauthentication page says the weekly cycle "starts on every Monday" | Same; *Daily & weekly reauthentication* |
| 2FA is required for every user. The API supports IB Key, a smartphone app, SMS and the Digital Security Card+; not the paper code cards | TWS API, *Supported 2FA* |
| "Maintain and resubmit orders when connection is restored" is **on by default**: orders received while the gateway's own connection to IBKR was lost are kept and resubmitted when it returns. If the gateway itself is closed, they are deleted | TWS API, *Intelligent order resubmission* |
| Errors 1100, 1101 and 1102: the gateway lost its connection to IBKR, then got it back with or without the market-data requests | TWS API, error codes |

The gateway's supervision (IBC, the 2FA wait, restarts) is PR 17's subject; this table records only what PR 11 needs.

## 3. Paper and live accounts

| Fact | Source |
|---|---|
| **A paper account is opened only once the live account is funded.** "Client Portal Settings will not be available until your account has an active deposit on record" | *What is a Paper account?* FAQ; *About Paper Trading Accounts* |
| The paper username and account number are shown in Client Portal: user menu, Settings, Account Configuration, **Paper Trading Account**, with a link to reset the paper password separately | *Step five: review your paper credentials*; Web API, *Using a paper account* |
| **Paper credentials are different from the live ones**, says the paper-account FAQ. A mobile FAQ says "both versions of your account use the same login credentials". The pages disagree; what Client Portal shows for your account decides it | *What is a Paper account?*; *Live vs paper* FAQ |
| **Account-number format: not stated** on any IBKR page read. Third-party guides say paper accounts start with `DU` and live ones with `U`. Tyche does not rely on a prefix ([ADR-0041](../adr/0041-orders-and-identity-at-ibkr.md)) | Not found at IBKR |
| Paper starts with USD 1,000,000 of equity with loan value; it can be reset to up to five times the live account's value, requested before 16:00 ET for the next business day | *About Paper Trading Accounts* |
| "Trading permissions, market data subscriptions, base currency, and other account configurations are the same as specified for your regular account" | Same |
| Paper trades "will not actually execute on any exchange **or settle at a clearing house**"; prices come from real market prices and sizes | Same |
| Paper simulates "margin functionality, leverage, and maintenance margin requirements" | Same |
| Limits: no VWAP, Auction, RFQ or Pegged-to-Market orders; fills from the top of the book only; "**Stops and other complex order types are always simulated in paper trading**"; the remainder of a partly filled exchange-directed market order is rejected; a market order with no opposite quote is held until the first partial fill; default settings may restrict orders to regular hours | Same; *What is a Paper account?* |
| Paper accounts may be closed for inactivity | *About Paper Trading Accounts* |
| Error 10197: logged into paper and live at once, market data goes to live | TWS API, error codes |

**Consequence:** paper is a good test of the API, order types and Tyche's own bookkeeping. It is **not** a test of cash-account settlement (section 8), of fills in the opening auction, or of exactly how a stop fills.

## 4. Orders sent after the close, for the next open

Tyche decides after the close and trades at the next open ([ADR-0023](../adr/0023-execution-sleeves-stops-and-cash.md)). IBKR offers two ways to do that.

**Market-on-open (MOO):**

| Fact | Source |
|---|---|
| A market order with time in force **`OPG`**: "automatically submitted at the market's open and fills at the market price" | IBKR Canada, *Market on Open* |
| Sent the evening before, "The order will be held in the system and submitted when the market opens the next day" | Same, worked example |
| "Smart routed Market on Open orders are designed to be routed to, and execute on the **Primary Listing Exchange**". The official opening price "may differ from the 09:30:00 EST opening print" and can be delayed in volatile markets | Same, notes |
| "Nasdaq MOO (and LOO) orders must be submitted prior to 09:28 ET." No cut-off is given for NYSE Arca | Same |
| IBKR "may simulate market orders on exchanges" | Same |
| Products: stocks and ETFs among others. The tile lists the platforms as TWS and Client Portal | Same |
| On-open orders cannot be cancelled or modified once the opening imbalance is published (a search result quoting IBKR's limit-on-open page; **not read directly**) | Not confirmed |
| What happens to a MOO order that does not fill at the open is **not stated** | Not found |

**A plain day market order:**

| Fact | Source |
|---|---|
| "A Market or a Stop order is only active during the Regular Trading Hours after the 'OP' opening print on the primary Listing exchange", 09:30 to 16:00 ET for US stocks | *Why did my Market and/or Stop order for U.S. stocks not get triggered outside RTH?* FAQ |
| Orders meant for regular hours only "will not become active until on or after the official market center opening print" | *Market on Open*, notes |
| Whether a `DAY` order **sent after the close** is kept for the next session or rejected is **not stated** | Not found |

So a day market order goes to the market just after the opening print and fills at whatever the book offers then, while a MOO order takes part in the opening auction itself. The simulator fills at the session's open price ([backtesting internals](backtesting-internals.md)); MOO is the closer match.

## 5. Stops that rest across sessions

| Fact | Source |
|---|---|
| A stop is "an instruction to submit a buy or sell market order if and when the user-specified stop trigger price is attained or penetrated", with no guaranteed price | IBKR Canada, *Stop* |
| IBKR may simulate stops on its own books. For simulated stops the client can choose a trigger method; the default "can differ depending on the type of product" | Same |
| **US-stock stops work only in regular hours** (09:30 to 16:00 ET); only limit and stop-limit orders can be set to work outside them | RTH FAQ |
| In the API, `outsideRth` "allows orders to also trigger or fill outside of regular trading hours" | TWS API, `Order` reference |
| **Good-til-canceled** keeps an order working "until the order fills or is canceled". Time in force `GTC` in the API | IBKR Canada, *Good Til Canceled*; `Order` reference |
| **But IBKR cancels GTC orders by itself**: after a split, a share exchange or a share distribution; after a dividend above 3% of the previous close, or any special dividend; **if you do not log in to your IBKR account for 90 days**; and **at the end of the calendar quarter after the one the order was placed in** (on the last trading day if the quarter ends on a non-trading day). A modified order gets a new expiry date | Same |
| Orders working for more than one day are flagged Do Not Reduce: **not lowered for ordinary dividends** | Same, disclosure |
| IBKR cancels on corporate actions on a best-efforts basis and may miss one announced less than 48 hours ahead; "It is the Customer's responsibility to monitor their account" | Same |
| GTC is not supported for IB Algos | Same |

## 6. Recognising Tyche's own orders

| Fact | Source |
|---|---|
| `orderId` is chosen by the client and **must be strictly increasing**. A lower or equal id is refused: error 103, "Duplicate order ID" | TWS API, *OrderId*; error codes |
| `nextValidId` arrives on connection and after `reqIds`. The sequence **persists between sessions**, and can be reset in the API settings only while no API order is open | TWS API, *Next Valid ID* |
| An execution's `OrderId` "May not be unique to an account" | TWS API, *Execution details* |
| `permId` is "the Host order identifier" (TWS's own id); it can be 0 for trades that started outside IBKR | `Order` reference; *Execution details* |
| **`orderRef`**: the execution page calls it "a user-customizable string that can be set from the API or TWS and will be associated with an order for its lifetime". The `Order` reference says "Intended for institutional customers only". **The pages disagree** | *Execution details*; `Order` reference |
| An API order is bound to the client id that placed it: only that client can modify or cancel it. `reqOpenOrders` returns that client's open orders; `reqAllOpenOrders` returns every open order in the accounts, once | TWS API, *Open orders*; *Cancel order* |
| Without the "Master API client ID" setting, a client sees only its own orders and executions. Client id 0 also sees orders placed in TWS and through FIX | TWS API, *ClientId 0 and the Master Client ID* |
| `reqGlobalCancel` cancels **all** open orders, however they were placed | TWS API, *Cancel order* |
| `reqCompletedOrders` returns **the day's** orders that can no longer change: filled, rejected or cancelled | TWS API, *Completed orders* |
| `reqExecutions` returns executions **since midnight** by default. TWS can show up to 7 days if its Trade Log setting is changed; **"The IB Gateway is limited to only executions from the current trading day since midnight"** | TWS API, *Execution details* |
| A corrected execution arrives again with the same fields and an `execId` that differs only after the last period | Same |

**Consequence:** a run that does not happen on the day of a fill cannot read that fill from the gateway the next day. The day's executions must be read the same day, or the fill rebuilt from positions and cash (PRs 12 to 14).

## 7. Pacing

| Fact | Source |
|---|---|
| Requests per second = market-data lines ÷ 2; the default 100 lines give **50 requests a second** | TWS API, *Pacing limitations* |
| With "Reject messages above maximum allowed message rate" checked, an excess request gets error 100, and after three, the session is closed. Unchecked, the gateway paces requests itself | Same |
| Error 100's description: "exceeded the rate of 50 messages/second. The TWS will likely disconnect the client application" | TWS API, error codes |

Tyche sends a handful of requests per run, far below this. The limit matters only if a bug makes Tyche loop.

## 8. Settlement in a cash account, read again

The question carried from [the costs page, section 4](ibkr-canada-costs-and-settlement.md#4-settlement-in-a-cash-account): can a cash account buy with proceeds that have not settled? Re-read on 2026-11-23, plus one page not read before.

| Page | What it says |
|---|---|
| *Why is my buying power less than my available cash?* | "New opening orders in Cash accounts only allow trading using the settled cash balance" and "your buying power is equal to your settled cash balance". **No** |
| *Free riding rule* | Example 2: on day T the account sells ABC and buys XYZ with the proceeds; the violation is selling XYZ on T+1. Buying with unsettled proceeds is not the violation. **Yes, implied** |
| *Why am I unable to use my cash after selling?* | After a free-riding violation "they can only place new orders with fully settled funds for the next 90 days", implying that before one they could use unsettled funds. **Yes, implied** |
| *What is a free riding violation?* | During the 90 days, "you cannot enter a new opening order with unsettled funds". **Yes, implied** |
| *What determines how much cash is available for withdrawal?* | A cash account has no "access to the proceeds from the sale of securities until such time the transaction has settled at the clearinghouse". About withdrawal; **does not settle trading** |

**Still unresolved.** One FAQ says no in words; three imply yes through their examples. None names IBKR Canada. **The paper account cannot answer it**, because paper trades never settle at a clearing house (section 3). The answer has to come from IBKR support, in writing, or from the live account itself. [ADR-0020](../adr/0020-cost-and-settlement-model.md)'s stricter reading stays.

## 9. FINRA's Trading Activity Fee from 2027

| Fact | Source |
|---|---|
| FINRA paused the TAF "for three months, for transactions from October 1, 2026 through December 31, 2026, with TAF assessment resuming on January 1, 2027". Effective on filing, 2026-09-15 | SEC Release 34-106409, SR-FINRA-2026-021 (Federal Register 2026-19392) |
| "Beginning with January 2027 transactions, the previous TAF fee rates will resume" | Same |
| A second filing postpones by two years every fee change from the 2024 fee filing due between 2027-01-01 and 2029-01-01. Covered equity securities: **USD 0.000195 per share sold, at most USD 9.79 per trade, in 2027 and 2028**; USD 0.000232 (at most 11.61) from 2029; 0.000240 (12.05) in 2030; 0.000249 (12.50) in 2031 | SEC Release 34-106410, SR-FINRA-2026-020 (Federal Register 2026-19393) |
| Both took effect on filing under Section 19(b)(3)(A); the SEC could suspend them within 60 days of filing, so until 2026-11-14. A suspension was not searched for separately; none is mentioned on the two documents | Same |
| FINRA's own fee-schedule page still shows USD 0.000232 for 2027: **out of date** on this point | FINRA, *Fee adjustment schedule* |
| IBKR Canada's commission page still shows the holiday (USD 0.00 a share sold) and the same regulatory, clearing and pass-through figures as on 2026-11-22 | IBKR Canada, commission page, re-read 2026-11-23 |

The cap binds only on a sale of more than about 50,000 shares (9.79 ÷ 0.000195), far beyond any Tyche order. Whether IBKR passes the fee through exactly as FINRA charges it is not stated beyond the commission page's line.

## 10. To confirm on the paper account

Each item is something IBKR's pages leave open and that PR 11 builds on. **They wait for Pablo's paper account**: his live account was funded on 2026-11-23, the deposit had not arrived on 2026-11-24, and the paper account opens only once it has. They are run when he says it is active. With the paper account open, each takes a few minutes in TWS or Client Portal; PR 11's opt-in integration tests repeat the API ones.

| # | Check | Why |
|---|---|---|
| 1 | The paper account number's format, and whether the paper login is separate from the live one | Section 3. The account check compares the exact id; this only confirms what to put in `.env` |
| 2 | A MOO order (`MKT`, `OPG`) for one share of SPY, sent the evening before, is accepted and fills at the open; note the fill time and price against the official open | Section 4. Paper does not support "Auction" orders; whether it supports MOO for stocks is not stated |
| 3 | What happens to a MOO order that does not fill | Section 4. Decides whether a working order can survive to the next decision (STATUS, carried to PR 14) |
| 4 | A `DAY` market order sent after the close: kept for the next session, or rejected | Section 4. The fallback if 2 fails |
| 5 | A GTC sell stop shows its auto-expiry date (end of the next quarter), and survives an overnight gateway restart | Section 5 |
| 6 | An order sent with an `orderRef` comes back with it on the open order, the execution and the completed order, after disconnecting and reconnecting | Section 6. The pages disagree on `orderRef` |
| 7 | Cancelling a single order in Client Portal and in IBKR Mobile, step by step; and whether IBKR Mobile's **Cancel Orders** also cancels resting stops | Section 11 and the [kill-switch runbook](../runbooks/kill-switch.md) |
| 8 | Each `XNAS` candidate (QQQ, TLT, IEF) resolves to exactly one stock contract without a listing-exchange code, and which code IBKR gives it (`test_every_candidate_resolves_to_one_contract` prints them). Add each code to `PRIMARY_EXCHANGES` once seen | Section 12. IBKR's pages give `ARCA` only |
| 9 | Whether the paper account reports `SettledCashByDate`, and what it holds after a trade, since paper never settles | Section 12. `IBKRBroker.account()` refuses an account without it |
| 10 | The currency of the commission report on a US trade in a CAD-based account | Section 12. A fill's commission must be in the trade's currency; another currency stops the run |
| 11 | What status an order IBKR refuses ends in (`Inactive` or `Cancelled`), and its error message | Section 12. IBKR's page describes `Inactive` only as an order not yet transmitted |
| 12 | In which currencies the paper account reports `AccruedDividend` (per currency, or only `BASE`), from a dividend's ex-date to its pay date | Section 13. `IBKRBroker.record()` reads it per currency and ignores `BASE`; reported only in `BASE`, a dividend's payment may exceed reconciliation's allowance and halt once ([ADR-0044](../adr/0044-reconciliation-exact-positions-broker-cash.md)) |
| 13 | Whether `AccruedDividend` is gross or net of withholding, and what the cash rises by on the pay date | Section 13. Decides how much of a dividend reconciliation adopts as noise |

**Not confirmable on paper:** unsettled proceeds in a cash account (section 8), real opening-auction fills, and exchange fees.

## 11. Cancelling an order in IBKR's own apps

| App | Steps, as IBKR's FAQs give them | Source |
|---|---|---|
| Client Portal | **Trade** menu, then **Orders & Trades** (or **Trade** at the top right of the Home page). On the order's row, click the **pencil icon**; in the order ticket on the right, click **Cancel Order** | *What can I see on the Orders & Trades screen of Client Portal?* |
| IBKR Mobile (iPhone) | Account menu (head and shoulders, top left), **Transactions**, **Orders**, the three dots at the top right, **Cancel Orders**, then confirm. **This cancels all working orders**, which would include Tyche's protective stops | *How do I cancel all my open orders in IBKR Mobile for iPhone?* |

A page for cancelling a *single* order in IBKR Mobile was not found. Orders Tyche places through the gateway are bound to its API client id (section 6); whether Client Portal and IBKR Mobile can cancel them is item 7 above.

## 12. Read for PR 11

**Read on 2026-11-24** in a browser, for the adapter ([ADR-0042](../adr/0042-ibkr-paper-adapter-at-most-once-orders.md)). IBKR's documentation refuses automated fetches.

**Cash in the account**

| Fact | Source |
|---|---|
| Account summary tags: `TotalCashValue` is "Total cash balance recognized at the time of trade + futures PNL"; `SettledCash` is cash "recognized at the time of settlement", less purchases at the time of trade, commissions, taxes and fees | TWS API, *Account Summary* |
| `$LEDGER` relays the cash balance tags in the base currency only; `$LEDGER:ALL` in every currency | Same |
| **`SettledCashByDate`** is "returned for each currency held in the account", plus `BASE`. Its value is `YYYYMMDD:amount` pairs joined by semicolons: the first is the settled cash available now, and later dates are **cumulative** values, so what settles on a date is its difference from the one before. TWS's own window shows the differences instead | TWS API, *Account Updates* |
| Account values are sent at subscription, then on a position change, or every three minutes if a value changed | Same |

**Orders and statuses**

| Fact | Source |
|---|---|
| `tif`: the reference lists `DAY` and `GTC` and repeats IBKR's automatic GTC cancellations. `OPG` for market-on-open comes from IBKR's *Market on Open* page (section 4) | TWS API, `Order` reference |
| `orderRef` is still described as "Intended for institutional customers only"; no length limit is stated | Same |
| Statuses: `PendingSubmit` (transmitted, not yet confirmed), `PreSubmitted` (accepted by the system for simulated orders, or by an exchange, "yet to be elected"), `Submitted` (working), `Filled`, `PendingCancel` and `PreCancelled` (a cancel not yet confirmed; an execution may still arrive), `Cancelled` ("could occur unexpectedly when the destination has rejected your order"), `Inactive` (described only as an order being created and not yet transmitted), `WarnState` | TWS API, *Order Status* |
| `ib_async` also counts `Inactive` among the finished states, beside `Filled`, `Cancelled` and `ApiCancelled` | `ib_async` 2.1.0, `order.py` |
| After a fill, `execDetails` and a separate commission report arrive. The report holds `execId`, `commission`, `currency`, `realizedPnl`, `yield` and `yieldRedemptionDate`. Whether `commission` includes regulatory fees is not stated | TWS API, *Commission And Fees Report* |
| `ib_async` gives an execution's time with a time zone, or in the gateway's zone if the gateway sent none and `IB.TimezoneTWS` is set | `ib_async` 2.1.0, `decoder.py` |

**Contracts**

| Fact | Source |
|---|---|
| A minimum contract is a `conId` and an exchange, or a symbol, security type, exchange, primary exchange and currency | TWS API, *The Contract Object* |
| A stock or ETF is `secType` `STK`, exchange `SMART`. "For certain smart-routed stock that have the same symbol, currency and exchange, you would also need to specify the primary exchange"; it is "good practice to include for all stocks". The example: SPY with `primaryExchange` **`ARCA`** | TWS API, *Stocks* |
| IBKR's codes for Nasdaq and NYSE listings were not found on the pages read. Tyche looks those up without one and requires a single match (check 8) | Not found |
| `reqContractDetails` returns every match: none means unknown, several means ambiguous | `ib_async` 2.1.0, `ib.py` |

**`tzdata`**

| Fact | Source |
|---|---|
| `tzdata` 2025.3 was uploaded on 2025-12-13, after IANA release 2025c (2025-12-10); 2026.6 on 2026-10-28 | PyPI, *tzdata* release history |
| Releases 2026a to 2026f change no rule for `America/New_York` or `America/Toronto`. 2026d changes the old `EST5EDT`-style names before 1966 only; the Canadian changes are in British Columbia, Alberta, the Northwest Territories and Manitoba | IANA, tzdb `NEWS` |

## 13. Read for PR 13

**Read on 2026-11-24** in a browser, for reconciliation ([ADR-0044](../adr/0044-reconciliation-exact-positions-broker-cash.md)). TWS API, *Account Updates*: the account value tags.

| Tag | IBKR's description |
|---|---|
| `AccruedDividend` | "Total portfolio value of dividends accrued"; `AccruedDividend-S`: dividends "accrued but not paid in security segment" |
| `NetDividend` | "The sum of the Dividend Payable/Receivable Values for the securities and commodities segments of the account" |
| `AccruedCash` | "Total accrued cash value of stock, commodities and securities"; `AccruedCash-S` "reflects the current month's accrued debit and credit interest to date, updated daily" |
| `TotalCashValue` | "Total cash value of stock, commodities and securities" |
| `SettledCashByDate` | Returned for each currency held, plus `BASE`; dates and values joined by semicolons (section 12) |

**Not stated:** whether `AccruedDividend` is reported per currency or only in the base currency, and whether it is gross or net of withholding. Paper checks 12 and 13.

## Sources

All read on 2026-11-23. IBKR's pages were read in a browser; their FAQs carry no publication date.

**Library**

- PyPI, [ib-async](https://pypi.org/project/ib-async/) and its [JSON metadata](https://pypi.org/pypi/ib-async/json); [aeventkit](https://pypi.org/project/aeventkit/); [nest-asyncio](https://pypi.org/project/nest-asyncio/).
- GitHub, [ib-api-reloaded/ib_async](https://github.com/ib-api-reloaded/ib_async): README, `LICENSE`, `pyproject.toml`, `.github/workflows/test.yml`; [erdewit/nest_asyncio](https://github.com/erdewit/nest_asyncio) (archived).

**IBKR order types** (IBKR Canada)

- [Market on Open](https://www.interactivebrokers.ca/en/trading/orders/moo.php), [Good Til Canceled](https://www.interactivebrokers.ca/en/trading/orders/gtc.php), [Stop](https://www.interactivebrokers.ca/en/trading/orders/stop.php), and the *Simulated order types* note on the [order types page](https://www.interactivebrokers.ca/en/trading/ordertypes.php).
- [Commissions: Stocks, ETFs, Warrants and Certificates](https://www.interactivebrokers.ca/en/pricing/commissions-stocks.php), re-read for section 9.

**TWS API documentation**

- [Pacing limitations](https://www.interactivebrokers.com/docs/tws-api/doc/pacing-limitations), [Next valid ID](https://www.interactivebrokers.com/docs/tws-api/doc/next-valid-id), [OrderId](https://www.interactivebrokers.com/docs/tws-api/doc/quick-start/order-id), [Order reference](https://www.interactivebrokers.com/docs/tws-api/ref/order).
- [Open orders](https://www.interactivebrokers.com/docs/tws-api/doc/order-management/open-orders), [Completed orders](https://www.interactivebrokers.com/docs/tws-api/doc/order-management/completed-orders), [Execution details](https://www.interactivebrokers.com/docs/tws-api/doc/order-management/execution-details), [ClientId 0 and the Master Client ID](https://www.interactivebrokers.com/docs/tws-api/doc/order-management/master-client-id), [Cancel order](https://www.interactivebrokers.com/docs/tws-api/doc/orders/cancel-order).
- [Error codes](https://www.interactivebrokers.com/docs/tws-api/doc/error/codes), [Establishing an API connection](https://www.interactivebrokers.com/docs/tws-api/doc/connectivity/establishing-an-api-connection), [Connectivity behavior](https://www.interactivebrokers.com/docs/tws-api/doc/connectivity/connectivity-behavior).
- [TWS configuration for API use](https://www.interactivebrokers.com/docs/tws-api/doc/api-settings), [Daily & weekly reauthentication](https://www.interactivebrokers.com/docs/tws-api/doc/tws-settings/daily-weekly-reauthentication), [Intelligent order resubmission](https://www.interactivebrokers.com/docs/tws-api/doc/tws-settings/intelligent-order-resubmission), [Download TWS or IB Gateway](https://www.interactivebrokers.com/docs/tws-api/doc/download-tws), [Supported 2FA](https://www.interactivebrokers.com/docs/tws-api/doc/notes-limitations/supported-two-factor-authentication-2-fa), [TWS API limitations](https://www.interactivebrokers.com/docs/tws-api/doc/notes-limitations/tws-api-limitations).
- Excel RTD, [Connection parameters](https://www.interactivebrokers.com/docs/excel/rtd/connection-parameters) (the default ports).

**Paper account and cash account**

- FAQs: [What is a Paper account?](https://www.interactivebrokers.com/support/faq/content/paper-account-60341604), [Live vs paper](https://www.interactivebrokers.com/support/faq/content/452853057); IBKR Guides, [About Paper Trading Accounts](https://www.ibkrguides.com/clientportal/aboutpapertradingaccounts.htm); [Step five: review your paper credentials](https://www.interactivebrokers.com/docs/general/market-data-subscriptions/market-data-users/finding-your-paper-user-credentials/step-five-review-your-paper-credentials); Web API, [Using a paper account](https://www.interactivebrokers.com/docs/web-api/authentication/paper).
- FAQs: [Buying power less than available cash](https://www.interactivebrokers.com/support/faq/content/699740704), [Free riding rule](https://www.interactivebrokers.com/support/faq/content/1163245617), [Free riding violation](https://www.interactivebrokers.com/support/faq/content/699745149), [Unable to use cash after selling](https://www.interactivebrokers.com/support/faq/content/29079698), [Cash available for withdrawal](https://www.interactivebrokers.com/support/faq/content/32647712).
- FAQ: [Market and stop orders outside RTH](https://www.interactivebrokers.com/support/faq/content/did-market-stop-order-u-35803691).
- FAQs: [Orders & Trades in Client Portal](https://www.interactivebrokers.com/support/faq/content/38453132), [Cancel all open orders in IBKR Mobile](https://www.interactivebrokers.com/support/faq/content/cancel-all-open-orders-ibkr-181474102).

**Read for PR 13** (2026-11-24): TWS API [Account Updates](https://www.interactivebrokers.com/docs/tws-api/doc/accounts/updates).

**Read for PR 11** (2026-11-24): TWS API [Account Summary](https://www.interactivebrokers.com/docs/tws-api/doc/accounts/summary), [Account Updates](https://www.interactivebrokers.com/docs/tws-api/doc/accounts/updates), [Order Status](https://www.interactivebrokers.com/docs/tws-api/doc/order-management/order-status), [Commission And Fees Report](https://www.interactivebrokers.com/docs/tws-api/doc/order-management/commission-and-fees-report), [The Contract Object](https://www.interactivebrokers.com/docs/tws-api/doc/contracts/object), [Stocks](https://www.interactivebrokers.com/docs/tws-api/contracts/stocks) and the [Order reference](https://www.interactivebrokers.com/docs/tws-api/ref/order); IANA [tzdb NEWS](https://data.iana.org/time-zones/tzdb/NEWS); PyPI [tzdata](https://pypi.org/project/tzdata/#history); the installed `ib_async` 2.1.0 source.

**FINRA**

- Federal Register, [2026-19392](https://www.federalregister.gov/documents/2026/09/23/2026-19392/self-regulatory-organizations-financial-industry-regulatory-authority-inc-notice-of-filing-and) (Release 34-106409, SR-FINRA-2026-021, the pause) and [2026-19393](https://www.federalregister.gov/documents/2026/09/23/2026-19393/self-regulatory-organizations-financial-industry-regulatory-authority-inc-notice-of-filing-and) (Release 34-106410, SR-FINRA-2026-020, the schedule).
- FINRA, [Fee adjustment schedule](https://www.finra.org/rules-guidance/rule-filings/sr-finra-2024-019/fee-adjustment-schedule) (out of date for 2027).
