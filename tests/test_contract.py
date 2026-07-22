"""Platform side of the agent -> platform callback contract.

The platform reads a narrow envelope (job_id, verdict, score_pct, reason) out of
every agent callback and drives its state from it. This asserts:
  1. the shared validator (contract/callback_contract.py, byte-identical to the
     agent's copy) accepts the canonical agent payload and rejects drift, and
  2. the live /assessments/callback endpoint still persists a conformant payload.
Mirror of the agent repo's tests/test_contract.py. It reuses test_api's canonical
_callback_payload / _create_running_submission so there is one source of truth for
"what the agent sends".
"""

from __future__ import annotations

import importlib.util
import pathlib

from test_api import _callback_payload, _create_running_submission

# Load the byte-identical contract module by path (repo-root, outside the package,
# because it is a cross-repo artifact).
_CONTRACT = pathlib.Path(__file__).resolve().parents[1] / "contract" / "callback_contract.py"
_spec = importlib.util.spec_from_file_location("callback_contract", _CONTRACT)
callback_contract = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(callback_contract)


def test_canonical_agent_payload_conforms():
    assert callback_contract.validate_callback(_callback_payload("job-1")) == []


def test_unknown_verdict_is_rejected():
    payload = _callback_payload("job-1")
    payload["verdict"] = "MAYBE"
    assert any("verdict" in e for e in callback_contract.validate_callback(payload))


def test_missing_score_is_rejected():
    payload = _callback_payload("job-1")
    del payload["score_pct"]
    assert any("score_pct" in e for e in callback_contract.validate_callback(payload))


def test_conformant_payload_persists_through_endpoint(client, monkeypatch):
    sub_id = _create_running_submission(client, monkeypatch, "job-ctr")
    payload = _callback_payload("job-ctr")
    assert callback_contract.validate_callback(payload) == []

    resp = client.post("/assessments/callback", json=payload)
    assert resp.status_code == 200

    sub = client.get(f"/submissions/{sub_id}").json()
    assert sub["result"]["verdict"] == payload["verdict"]
    assert sub["result"]["score_pct"] == payload["score_pct"]
