#!/usr/bin/env python3
"""Cross-repo end-to-end smoke: boot the REAL agent + platform and drive one
submission all the way to a stored verdict.

The unit suites mock the agent and the Playwright e2e uses a mock agent, so nothing
else exercises the actual wire. This does: platform -> agent trigger -> real code
execution -> agent callback -> platform persistence. It answers one question in one
command — does agent->platform still work end to end?

Runs fully OFFLINE: the verdict is execution-based, so no ANTHROPIC_API_KEY is
needed (the quality judge falls back to its offline heuristic, which never gates a
verdict). Both servers run unsecured (tokens/signing are enforced only when set).

Usage:  uv run python scripts/smoke_e2e.py      # from the platform repo root
Exit 0 = graded PASS and the platform stored it; non-zero = the loop is broken.

Callback host note: the agent's SSRF guard rejects literal loopback IPs and the
exact string "localhost", but allows a hostname (it does no DNS). We point the
callback at the trailing-dot FQDN "localhost." — the guard passes it and the OS
still resolves it to loopback offline. Everything therefore runs on IPv6 loopback
(::1) so the bind family stays consistent.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
AGENT_ROOT = PLATFORM_ROOT.parent / "AssesmentAgent"

AGENT_PORT = 8000
PLATFORM_PORT = 9000
AGENT_URL = f"http://127.0.0.1:{AGENT_PORT}"
PLATFORM_URL = f"http://[::1]:{PLATFORM_PORT}"          # how this script talks to it
CALLBACK_BASE = f"http://localhost.:{PLATFORM_PORT}"    # what the agent POSTs back to

SMOKE_DB = PLATFORM_ROOT / "smoke_e2e.db"

CORRECT_SOLUTION = "n = int(input())\nprint(sum(int(x) for x in input().split()))\n"

# A constraint-sized performance case (the agent requires one as its TLE gate),
# with a computed oracle: 1000 ones -> sum 1000.
_PERF_N = 1000
_PERF_STDIN = f"{_PERF_N}\n{' '.join('1' for _ in range(_PERF_N))}\n"

QUESTION = {
    "id": "smoke_sum",
    "title": "Sum of N",
    "prompt": "Read N, then a line of N integers; print their sum.",
    "constraints": "1 <= N <= 1000",
    "time_limit_s": 5.0,
    "pass_threshold": 0.9,
    "required_complexity": None,
    "example_input": "2\n3 4\n",
    "example_output": "7",
    "test_cases": [
        {"name": "t1", "stdin": "2\n3 4\n", "expected": "7",
         "category": "correctness", "weight": 1.0},
        {"name": "t2", "stdin": "3\n1 2 3\n", "expected": "6",
         "category": "correctness", "weight": 1.0},
        {"name": "perf", "stdin": _PERF_STDIN, "expected": str(_PERF_N),
         "category": "performance", "weight": 3.0},
    ],
}


_AUTH: dict[str, str] = {}  # populated with the interviewer bearer after login


def _req(method: str, url: str, body: dict | None = None, timeout: float = 10):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json", **_AUTH}
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (localhost only)
        return r.status, json.loads(r.read() or b"{}")


def _login_interviewer() -> None:
    """Register + log in an interviewer and stash the bearer for later calls.

    Interviewer routes (/questions, /submissions) are always JWT-guarded; login
    signs with a dev-default secret when JWT_SECRET is unset, so no secret needed.
    """
    creds = {"email": "smoke@test.io", "password": "pw", "name": "Smoke"}
    try:
        _req("POST", f"{PLATFORM_URL}/auth/register", creds)
    except Exception:
        pass  # already registered on a reused DB is fine
    _, tok = _req("POST", f"{PLATFORM_URL}/auth/login",
                  {"email": creds["email"], "password": creds["password"]})
    _AUTH["Authorization"] = f"Bearer {tok['access_token']}"


def _child_env(**extra: str) -> dict[str, str]:
    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)  # force the offline judge
    # Run both sides unsecured — each enforces auth/signing only when its var is set.
    for k in (
        "JWT_SECRET", "ASSESS_API_TOKEN", "CALLBACK_TOKEN",
        "ASSESS_SIGNING_SECRET", "CALLBACK_SIGNING_SECRET", "VIRTUAL_ENV",
    ):
        env.pop(k, None)
    env.update(extra)
    return env


def _wire_secrets() -> dict[str, str]:
    """Matching tokens + signing secrets for both servers, so --secure exercises
    the full path: bearer auth + HMAC body signing in BOTH directions. The four
    env-var names are identical across the two repos (that's the whole point)."""
    return {
        "ASSESS_API_TOKEN": secrets.token_hex(16),       # platform -> agent trigger
        "CALLBACK_TOKEN": secrets.token_hex(16),         # agent -> platform callback
        "ASSESS_SIGNING_SECRET": secrets.token_hex(16),  # signs/verifies the trigger
        "CALLBACK_SIGNING_SECRET": secrets.token_hex(16),  # signs/verifies the callback
    }


def _child_log(name: str):
    """Where a child server's logs go: silenced by default, or to
    ``$SMOKE_DEBUG_DIR/<name>.log`` when SMOKE_DEBUG_DIR is set (for triage)."""
    debug_dir = os.getenv("SMOKE_DEBUG_DIR")
    if not debug_dir:
        return subprocess.DEVNULL
    return open(Path(debug_dir) / f"{name}.log", "w")  # noqa: SIM115


def _wait_health(url: str, name: str, timeout: float = 60) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            status, _ = _req("GET", f"{url}/health", timeout=2)
            if status == 200:
                print(f"  ✓ {name} healthy at {url}")
                return
        except Exception:
            time.sleep(0.5)
    raise SystemExit(f"✗ {name} never became healthy at {url} within {timeout}s")


def main() -> int:
    parser = argparse.ArgumentParser(description="Cross-repo agent<->platform e2e smoke.")
    parser.add_argument(
        "--secure", action="store_true",
        help="exercise the full auth + HMAC-signing path (matching tokens/secrets "
             "on both servers) instead of running unsecured.",
    )
    secure = parser.parse_args().secure
    wire = _wire_secrets() if secure else {}
    print(f"==> mode: {'SECURED (bearer + HMAC signing, both directions)' if secure else 'unsecured'}")

    if not AGENT_ROOT.exists():
        raise SystemExit(f"✗ agent repo not found at {AGENT_ROOT}")
    SMOKE_DB.unlink(missing_ok=True)

    # Unsecured: the agent fail-closes to 503 without an explicit opt-out. Secured:
    # the shared token/secret set replaces the opt-out on both sides.
    agent_env = _child_env(**wire) if secure else _child_env(ASSESS_AUTH_DISABLED="1")
    platform_env = _child_env(
        HOST="::1", PORT=str(PLATFORM_PORT), AUTO_CREATE_TABLES="true",
        DATABASE_URL=f"sqlite:///{SMOKE_DB}",
        AGENT_BASE_URL=AGENT_URL, PLATFORM_BASE_URL=CALLBACK_BASE,
        **wire,
    )

    procs: list[subprocess.Popen] = []
    try:
        print("==> booting agent (offline) ...")
        procs.append(subprocess.Popen(
            ["uv", "run", "assess-api"], cwd=AGENT_ROOT, env=agent_env,
            stdout=_child_log("agent"), stderr=subprocess.STDOUT,
        ))
        print("==> booting platform ...")
        procs.append(subprocess.Popen(
            ["uv", "run", "platform-api"], cwd=PLATFORM_ROOT, env=platform_env,
            stdout=_child_log("platform"), stderr=subprocess.STDOUT,
        ))

        _wait_health(AGENT_URL, "agent")
        _wait_health(PLATFORM_URL, "platform")

        print("==> registering + logging in an interviewer ...")
        _login_interviewer()

        print("==> creating question ...")
        status, _ = _req("POST", f"{PLATFORM_URL}/questions", QUESTION)
        assert status == 201, f"question create -> {status}"

        print("==> submitting a correct solution ...")
        status, sub = _req("POST", f"{PLATFORM_URL}/submissions", {
            "question_id": QUESTION["id"], "candidate": "smoke",
            "language": "python", "code": CORRECT_SOLUTION,
        })
        assert status in (200, 201), f"submit -> {status}"
        sub_id = sub["id"]

        print("==> waiting for the agent callback to land ...")
        deadline = time.time() + 60
        result: dict | None = None
        while time.time() < deadline:
            _, cur = _req("GET", f"{PLATFORM_URL}/submissions/{sub_id}")
            if cur.get("status") in ("done", "error"):
                result = cur
                break
            time.sleep(0.5)
        if result is None:
            raise SystemExit("✗ no callback within 60s — submission stranded")

        res = result.get("result") or {}
        verdict, score = res.get("verdict"), res.get("score_pct")
        print(f"==> submission {sub_id}: status={result['status']} "
              f"verdict={verdict} score={score}")
        if result["status"] == "done" and verdict == "PASS":
            print("✅ SMOKE PASSED — agent graded and platform stored the verdict end-to-end")
            return 0
        print("❌ SMOKE FAILED — see status/verdict above")
        return 1
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=5)
            except Exception:
                p.kill()
        SMOKE_DB.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
