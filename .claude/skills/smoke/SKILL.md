---
name: smoke
description: Run the cross-repo end-to-end smoke — boots the REAL agent + platform and drives one submission through to a stored verdict. Use to confirm the agent↔platform wire (trigger → execution → callback → persistence) still works after changes touching the boundary, agent_client, signing, or the callback contract. Requires ../AssesmentAgent checked out beside this repo.
---

# Cross-repo e2e smoke

Unlike the unit suites (which mock the agent) and the Playwright e2e (mock agent),
this exercises the **real** wire: `platform → agent trigger → real code execution →
agent callback → platform persistence`. It runs fully offline (the verdict is
execution-based; the LLM judge falls back to its offline heuristic and never gates).

## Run it

```bash
uv run python scripts/smoke_e2e.py            # unsecured (fast default)
uv run python scripts/smoke_e2e.py --secure   # also exercise bearer auth + HMAC signing both ways
```

- **Exit 0** and `✅ SMOKE PASSED` — the loop is healthy.
- **Non-zero** and `❌`/`✗` — report the failing step and the last log line.

`--secure` generates matching tokens + signing secrets on both servers, so it
covers the full path: `X-Assess-Token` bearer auth **and** HMAC body signing on
both the trigger and the callback. Use it after touching `signing.py`, auth, or
`agent_client`; the plain run is enough for the callback-contract path.

The script boots both servers on loopback, registers an interviewer, creates a
self-consistent question (with a computed performance-case oracle), submits a
correct solution, and asserts the platform stored `verdict=PASS`. It cleans up the
servers and the throwaway SQLite DB on exit.

## When it fails

Re-run with child-server logs captured for triage:

```bash
SMOKE_DEBUG_DIR=/tmp/smoke uv run python scripts/smoke_e2e.py
# then inspect /tmp/smoke/agent.log and /tmp/smoke/platform.log
```

Common causes: the agent's `/assessments` contract changed (question validation,
callback-URL guard), `agent_client` no longer builds the trigger body the agent
expects, or the callback envelope drifted (see `contract/callback_contract.py`,
which the pre-push gate keeps byte-identical across repos).

## Prerequisite

`../AssesmentAgent` must be checked out beside this repo (the script boots it via
`uv run assess-api`). If it isn't, the script exits with a clear message.
