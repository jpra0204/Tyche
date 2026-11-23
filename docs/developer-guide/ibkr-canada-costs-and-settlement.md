# IBKR Canada: costs and settlement for US stocks and ETFs

**Checked on 2026-11-17** against IBKR's own pages, listed under [Sources](#sources), and **re-checked on 2026-11-22** for PR 22: the commission page's Fixed, Tiered and third-party figures were unchanged, and the exchange-fee figures in section 1 were added. Nothing here is from memory. IBKR may change any of it at any time; when a number here is used in code, the code cites this page and its date. Re-check before Phase 2 (paper trading) and before going live.

This page records facts. The modelling choices built on them are in [ADR-0020](../adr/0020-cost-and-settlement-model.md). The rates Tyche uses live in the workspace, in `config/costs/US.toml`, with the date they were checked; `tyche config check` prints that date.

## 1. Commissions: US-listed stocks and ETFs

IBKR Canada's pricing page lists two plans for US stocks, both under IBKR Pro: **Fixed** and **Tiered**. It does not list IBKR Lite.

| | Fixed | Tiered (first tier, up to 300,000 shares a month) |
|---|---|---|
| Per share | USD 0.005 | USD 0.0035 |
| Minimum per order | USD 1.00 | USD 0.35 |
| Maximum per order | 1% of trade value | 1% of trade value |
| Third-party fees added on top | Regulatory fees only | Regulatory, exchange, clearing and pass-through fees |

**When the maximum is below the minimum, the maximum wins.** IBKR's own example: 10 shares of a USD 0.20 stock are charged USD 0.02, not USD 1.00. So under Fixed, any order worth less than USD 100 pays exactly 1% of its value.

**Fixed, written as a formula** (per order, before regulatory fees):

```text
commission = min( max(0.005 × shares, 1.00), 0.01 × trade value )
```

IBKR's published Fixed examples: 100 shares at USD 25 cost USD 1.00; 1,000 shares at USD 25 cost USD 5.00; 1,000 shares at USD 0.25 cost USD 2.50 (the 1% cap).

**Tiered** adds third-party fees that depend on where the order executes:

| Fee | Amount (as published) |
|---|---|
| Clearing (NSCC, DTC) | USD 0.00020 per share, capped at 0.5% of trade value |
| NYSE pass-through | commission × 0.000175 |
| FINRA pass-through | commission × 0.000563 |
| Exchange fees | Per venue; a fee is added when an order removes liquidity. Not knowable before the order executes |

**Exchange fees on the two venues Tyche's candidates list on**, as IBKR Canada publishes them for Tiered (per share, shares priced at USD 1.00 or more; read 2026-11-22):

| Venue | Remove liquidity | Add liquidity | At the open |
|---|---|---|---|
| NYSE Arca | USD 0.0030 | rebate of USD 0.0020 (NYSE- and Nasdaq-listed) | USD 0.0015 ("At the Open") |
| Nasdaq | USD 0.0030 | rebate of USD 0.0013 (Nasdaq-listed) to 0.0018 | USD 0.0015 (market-on-open) |

Arca also lists USD 0.0035 for orders it routes to another venue. Where a SmartRouted market order for the next open actually executes, and so which of these it pays, is not published; Tyche's `[tiered]` table assumes **USD 0.0030**, the fee for removing liquidity, which overstates the cost of an order filled in an opening auction ([ADR-0031](../adr/0031-minimum-viable-capital.md)).

The page also says that **directed API orders cannot use Tiered**; SmartRouted API orders can use either plan. Tyche would SmartRoute.

Two of the page's footnotes are easy to misread: "Maximum 0.5% of trade value" belongs to the NSCC/DTC clearing fee, not to the commission, whose maximum is 1% under both plans. Whether that 1% maximum also caps the third-party fees is not stated.

**Regulatory fees, charged under both plans:**

| Fee | Amount (as published) | Applies to |
|---|---|---|
| SEC transaction fee | USD 0.0000206 × value of sales | Sales only |
| FINRA Trading Activity Fee | USD 0.00 × quantity sold, under a fee holiday for trades from 2026-10-01 to 2026-12-31 | Sales only. The rate after the holiday is not published on the page |
| FINRA Consolidated Audit Trail fees | USD 0.000003 × quantity | Every trade. FINRA re-evaluates these twice a year |

**Other rules on the page that matter to Tyche:**

- Commissions apply to every order type.
- A modified order counts as a cancel and a new order, so each part can be charged a minimum. **An order that stays open overnight is treated as a new order** for minimums.
- Orders where the 1% cap applies do not count towards the Tiered volume tiers.
- "GST and PST where applicable" are applied separately to eligible services, commissions included. Whether that applies to stock commissions for a Canadian resident is **not verified**: check the first real statement.
- The page states no account minimum and no platform fee.

## 2. What this means for a small account

Arithmetic only, from the Fixed schedule above. Amounts are in USD because US stocks trade in USD; no CAD/USD rate is assumed.

| Order value (USD) | Fixed commission | As % of the order | Round trip (buy then sell) |
|---|---|---|---|
| 50 | 0.50 (1% cap) | 1.00% | about 2.0% |
| 100 | 1.00 | 1.00% | about 2.0% |
| 150 | 1.00 (minimum) | 0.67% | about 1.3% |
| 200 | 1.00 (minimum) | 0.50% | about 1.0% |
| 500 | 1.00 (minimum) | 0.20% | about 0.4% |
| 1,000 | 1.00 (minimum, unless above 200 shares) | 0.10% | about 0.2% |

The minimum dominates every order Tyche will place at first. A strategy that rotates five positions of about USD 150 every month pays roughly 1.3% of the account per rotation, about 16% a year, before slippage. This is the cost drag the [system overview](../architecture/system-overview.md#9-assumptions-and-honest-notes) warned about, and why PR 22 (minimum viable capital) matters.

Under Tiered the minimum is USD 0.35 plus exchange and clearing fees, so small orders cost noticeably less, but the exact cost depends on the venue. `tyche capital` (PR 22) runs every amount under both plans; [minimum viable capital](../user-guide/06-minimum-viable-capital.md) has the comparison on real data.

## 3. Fractional shares

| Fact | Source |
|---|---|
| IBKR Canada offers fractional shares in eligible US, Canadian and European stocks and ETFs, from USD 1 | Fractional trading page |
| Fractional trades pay the same commission rates as whole-share trades, with a minimum of USD 0.01. The footnote adds "the greater of 1% of the trade value or USD 0.01"; its examples are all under USD 100, where that matches the Fixed formula's 1% cap | Pricing page, footnote 9 |
| **Canadian RRSP and TFSA accounts are not eligible** | Fractional share FAQ |
| **Fractional trading is not available through the API.** IBKR: "Interactive Brokers APIs do not support fractional or cash quantity trading with exception to Cryptocurrencies and Forex trading." The FAQ says it is supported through FIX/CTCI but not the API | API order-types notes; fractional share FAQ |
| Market, limit, stop and stop-limit orders are accepted for fractions; an unmarketable limit order's fractional part may never execute | Fractional share FAQ |

**Consequence for Tyche:** Tyche will place orders through IB Gateway's API (Phase 2), so **it can trade whole shares only**, whatever the account type. Backtests must use the same rule, or they will hold positions the live system cannot.

## 4. Settlement in a cash account

| Fact | Source |
|---|---|
| US stock trades settle on the next business day: **T+1** | "Why is my buying power less than my available cash", IBKR FAQ |
| In a cash account, **buying power equals the settled cash balance**. "New opening orders in Cash accounts only allow trading using the settled cash balance" | Same FAQ |
| **Free riding:** closing a position before its opening trade has settled is a violation. IBKR checks at the end of each day | Free riding FAQs |
| Consequence of a violation: the account is put on "Cash Up Front" for **90 days**, meaning new orders may use fully settled funds only | Free riding FAQs |
| A margin account may trade with unsettled funds, but not withdraw them before settlement | Free riding rule FAQ |

**Two things these pages do not settle**, to confirm in the paper account in Phase 2 or with IBKR support:

1. **The pages disagree on buying with unsettled proceeds.** The buying-power FAQ says a cash account trades only with settled cash. The free-riding FAQ's examples show an account selling ABC and buying XYZ with the proceeds on the same day. ADR-0020 takes the stricter reading.
2. **They are IBKR-wide pages and do not name IBKR Canada.** They do not say whether the Canadian entity applies exactly the same checks, or when on the settlement date the proceeds count as settled.

**Consequence for Tyche:** with whole-day bars and next-open orders, T+1 means a sale on day *d* funds a purchase on day *d*+1 at the earliest. A same-day round trip (a buy at the open and a protective stop triggered later that day) is a free-riding violation.

## 5. Currency conversion (for later)

Not used by the `US` profile in Phase 1, which holds USD only. Recorded because Pablo's money arrives in CAD.

| Fact | Source |
|---|---|
| Spot currency conversion: 0.20 basis points × trade value (first tier) | Spot currencies pricing page |
| Minimum per order: USD 2.00 (first tier) | Same |
| Automatic conversion when buying in a currency the account does not hold: IBKR typically adds or subtracts 0.03% to the rate, with no separate commission | Same |

**The CAD/USD rate used in PR 22:** the Bank of Canada's daily average for 2026-11-20, **1.4325 CAD per USD** ([Valet API, series FXUSDCAD](https://www.bankofcanada.ca/valet/observations/FXUSDCAD/json?recent=5), read 2026-11-22). At that rate CAD 1,000 is USD 698.08; `tyche capital` was run with USD 700 to stand for it. The rate moves every day.

## Sources

All read on 2026-11-17; the first and the two exchange-fee pages also on 2026-11-22.

- IBKR Canada, [Commissions: Stocks, ETFs, Warrants and Certificates](https://www.interactivebrokers.ca/en/pricing/commissions-stocks.php) (Americas tab, United States section, its third-party fees and disclosures).
- IBKR Canada, [NYSE Arca exchange fees](https://www.interactivebrokers.ca/en/accounts/fees/ARCAstkfee.php?nhf=T) and [Nasdaq exchange fees](https://www.interactivebrokers.ca/en/accounts/fees/INETstkfee.php?nhf=T), linked from the commission page's Tiered exchange fees.
- IBKR Canada, [Fractional Trading](https://www.interactivebrokers.ca/en/trading/fractional-trading.php).
- IBKR FAQ, [Fractional share trading](https://www.interactivebrokers.com/support/faq/content/1163260722).
- IBKR API documentation, [Order types: notes and limitations](https://www.interactivebrokers.com/docs/general/order-types/notes-limitations/introduction).
- IBKR FAQ, [Why is my buying power less than my available cash in a Cash account?](https://www.interactivebrokers.com/support/faq/content/699740704)
- IBKR FAQ, [Free riding rule](https://www.interactivebrokers.com/support/faq/content/1163245617).
- IBKR FAQ, [What is a Free Riding violation in a Cash account and what are its consequences?](https://www.interactivebrokers.com/support/faq/content/699745149)
- IBKR FAQ, [Why am I unable to use my cash after selling my stock in a Cash account?](https://www.interactivebrokers.com/support/faq/content/29079698)
- IBKR Canada, [Commissions: Spot Currencies](https://www.interactivebrokers.ca/en/pricing/commissions-spot-currencies.php).
