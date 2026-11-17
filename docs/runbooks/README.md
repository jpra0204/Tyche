# Runbooks

A runbook is a checklist for a specific situation, written to be followed when you are tired or worried: exact steps, in order, with what you should see after each one. The user guide explains; a runbook instructs.

## Available now

None. There is nothing running to operate until Phase 2.

## Planned

| Runbook | Situation | Written in |
|---|---|---|
| `start-stop.md` | Starting and stopping Tyche and the gateway cleanly | Phase 2 |
| `crash-recovery.md` | Tyche or the machine stopped unexpectedly | Phase 2 |
| `gateway-reauth.md` | Discord says the IBKR gateway needs a login or 2FA | Phase 2 |
| `kill-switch.md` | You want everything to stop now; and how to resume afterwards | Phase 2 |
| `reconciliation-mismatch.md` | Tyche halted because its records differ from the broker's | Phase 2 |
| `paper-to-live-promotion.md` | Going live with a strategy that met the promotion criteria. Only Pablo performs this ([ADR-0013](../adr/0013-live-trading-gate.md)) | Phase 3 |

Every runbook will follow the same shape: when to use it, before you start, numbered steps with the expected result of each, how to confirm it worked, and what to do if it did not.
