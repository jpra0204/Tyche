# A second front door

**The pattern:** when a system gets a new way in, a web page beside the command line, the new door calls the same code the old one does, or even the old door itself. It adds no logic of its own. And a door that opens onto your own machine still needs a lock.

## Why it matters here

In [hexagonal architecture](hexagonal-architecture.md) the core sits in the middle and the outside world plugs in through adapters. Some adapters are **driven**: the core calls them (the broker, the data source, the notifier). Others are **driving**: they call the core. Until now Tyche had one driving adapter, the CLI. The console ([ADR-0046](../adr/0046-a-local-web-console.md)) is the second.

The danger with a second door is drift. If the page computed its own view of the account, or placed orders its own way, there would be two Tychés that slowly disagree, and the one handling money would be the less tested. So:

- **Reading** goes through `tyche.runtime` and `tyche.config`, the same functions `tyche config check` and `tyche kill` use. The Status page *is* those commands' answers, as data.
- **Running** starts the `tyche` command itself as a subprocess, with the options the form chose. The page can never do what the CLI cannot, and every safety check the CLI has comes along for free: a backtest form that reaches the holdout gets the CLI's own refusal, printed on the page.
- **An import contract** keeps the web framework inside `tyche.api`, so it cannot leak into the core.

## The lock

"It only listens on `127.0.0.1`" sounds safe, but your browser runs code from every site you visit, and that code can send requests to `127.0.0.1`. A console that runs a paper cycle on request would be a target. Two checks close it:

1. **A token per launch**, put in the address after `#`. The fragment is never sent to a server, so it does not end up in logs; the page reads it, keeps it for its tab, and sends it in a header. Another site cannot know it.
2. **A host check.** A site can point its own domain at your machine (DNS rebinding) to look "local". The server refuses any host name but `127.0.0.1` and `localhost`.

## A request, not a command line

The page never sends a command line for the server to run. It sends a small typed request, `{"command": "backtest", "first": "2005-01-03", "risk_profile": "stage-1"}`, and the server builds the argument list from it (`tyche.api.runs.arguments`). Three things follow:

- **Only listed commands exist.** `paper_run`, `kill` or anything else is not one of the request types, so it is refused before a process starts. Adding one is a code change, reviewed like any other.
- **No value can turn into an option.** A symbol, a profile name or a run id must match a pattern that never starts with `-`, so `--all` typed as a symbol, or `--home /elsewhere` as a profile, is refused. A field the command does not have is refused too, not ignored.
- **No shell.** The arguments go to the operating system as a list, so `;`, `$(...)` or spaces mean nothing special.

This is an *allowlist*: say what is allowed and refuse the rest, rather than trying to list what is dangerous.

For the commands that touch the account (the paper cycle, `kill`, `resume`), the request also carries `confirmed: true`. It adds no security (anything holding the token could send it) but it puts the confirmation into the contract: a page that forgot to ask would fail its own type check.

## In Tyche

- `tyche.api`: `create_app`, `security.py` (token and host names), `models.py` (the contract, including the run requests), `runs.py` (the subprocess, one at a time), `status.py`, `data.py`, `backtests.py`.
- `tyche ui` in `tyche.cli`: makes the token, serves, opens the browser.
- `ui/`: the React app; `ui/src/api/` is the only place it talks to the server.

## What it costs

- **A second language** with its own tools, lint and CI job.
- **A contract to keep in step:** the API's models generate the app's types, and a test fails when they drift.
- **A subprocess per run** is slower to start than a function call, and its result has to be read back from what it wrote. That is the price of never having two ways to trade.
