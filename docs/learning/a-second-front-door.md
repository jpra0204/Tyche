# A second front door

**The pattern:** when a system gets a new way in, a web page beside the command line, the new door calls the same code the old one does, or even the old door itself. It adds no logic of its own. And a door that opens onto your own machine still needs a lock.

## Why it matters here

In [hexagonal architecture](hexagonal-architecture.md) the core sits in the middle and the outside world plugs in through adapters. Some adapters are **driven**: the core calls them (the broker, the data source, the notifier). Others are **driving**: they call the core. Until now Tyche had one driving adapter, the CLI. The console ([ADR-0046](../adr/0046-a-local-web-console.md)) is the second.

The danger with a second door is drift. If the page computed its own view of the account, or placed orders its own way, there would be two Tychés that slowly disagree, and the one handling money would be the less tested. So:

- **Reading** goes through `tyche.runtime` and `tyche.config`, the same functions `tyche config check` and `tyche kill` use. The Status page *is* those commands' answers, as data.
- **Running** (from U2) starts the `tyche` command itself as a subprocess, with the options the form chose. The page can never do what the CLI cannot, and every safety check the CLI has comes along for free.
- **An import contract** keeps the web framework inside `tyche.api`, so it cannot leak into the core.

## The lock

"It only listens on `127.0.0.1`" sounds safe, but your browser runs code from every site you visit, and that code can send requests to `127.0.0.1`. A console that runs a paper cycle on request would be a target. Two checks close it:

1. **A token per launch**, put in the address after `#`. The fragment is never sent to a server, so it does not end up in logs; the page reads it, keeps it for its tab, and sends it in a header. Another site cannot know it.
2. **A host check.** A site can point its own domain at your machine (DNS rebinding) to look "local". The server refuses any host name but `127.0.0.1` and `localhost`.

## In Tyche

- `tyche.api`: `create_app`, `security.py` (token and host names), `models.py` (the contract), `status.py`.
- `tyche ui` in `tyche.cli`: makes the token, serves, opens the browser.
- `ui/`: the React app; `ui/src/api/` is the only place it talks to the server.

## What it costs

- **A second language** with its own tools, lint and CI job.
- **A contract to keep in step:** the API's models generate the app's types, and a test fails when they drift.
- **A subprocess per run** is slower to start than a function call, and its result has to be read back from what it wrote. That is the price of never having two ways to trade.
