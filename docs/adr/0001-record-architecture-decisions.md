# ADR-0001: Record architecture decisions as ADRs

- **Status:** Accepted (brief)
- **Date:** 2026-11-16

## Context

Tyche is built in small increments over many sessions, by one person working about ten hours a week with an AI pair. Decisions made in one session are easily forgotten or silently reversed in a later one. The main goal of the project is to learn system design, and the reasoning behind a design is the part most worth keeping.

## Decision

Every significant decision gets a short record in `docs/adr/`, numbered in order, using the template in the [index](README.md). "Significant" means hard to reverse, affecting more than one module, or likely to be questioned later.

An accepted ADR is not edited apart from its status line. A changed decision gets a new ADR that supersedes the old one.

## Alternatives considered

- **Keep decisions in commit messages or PR descriptions.** They are hard to find and are not read at the start of a session.
- **One large design document.** It hides when and why each decision was made, and it invites rewriting history.

## Consequences

- Each session can start from recorded decisions instead of re-deriving them.
- The brief's "decisions already made" table is traceable to a record with its reasoning.
- There is a small cost per decision. Trivial choices do not need an ADR.
