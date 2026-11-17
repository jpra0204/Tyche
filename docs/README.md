# Tyche documentation

| Folder | For | Start with |
|---|---|---|
| [`architecture/`](architecture/) | Understanding the design | [System overview](architecture/system-overview.md) |
| [`adr/`](adr/README.md) | Why each decision was made | [Index of decisions](adr/README.md) |
| [`developer-guide/`](developer-guide/README.md) | Working on the code | [Repo map](developer-guide/repo-map.md) |
| [`user-guide/`](user-guide/README.md) | Using Tyche day to day | [Index](user-guide/README.md) |
| [`runbooks/`](runbooks/README.md) | Step-by-step procedures when something needs attention | [Index](runbooks/README.md) |
| [`learning/`](learning/README.md) | The patterns behind the design, in plain language | [Index](learning/README.md) |

The original product brief is [`initial-brief.md`](initial-brief.md). Where a later decision refines the brief, the ADR is the current truth.

## How the docs are kept

- A task is not done until its docs are updated in the same pull request.
- Pages are written in the phase that builds the thing they describe. Until then each folder's index lists the planned page and its phase. There are no empty placeholder pages, because a page that exists but says nothing is worse than a missing one.
- Diagrams are Mermaid, so they are versioned and reviewed like code.
