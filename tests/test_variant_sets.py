"""Variant sets (per-candidate unique variants) — backend foundation.

Covers the draft (agent-mocked), persist, list, and detail endpoints plus
owner-scoping and the shared case-count floor. Fully offline: the agent's
draft-set call is monkeypatched, so no network / no real LLM."""

from __future__ import annotations

from typing import Any

from conftest import register_interviewer
from fastapi.testclient import TestClient
from test_slice1 import _auth, _sample_question

from assessment_platform import agent_client, config


def _variant_payload(qid: str, *, complexity: str = "O(n)", cost: float | None = 0.01) -> dict[str, Any]:
    return {
        "question": {
            "id": qid,
            "title": f"Variant {qid}",
            "prompt": "Read N then N ints; do the thing.",
            "constraints": "1 <= N <= 10^5",
            "required_complexity": complexity,
            "time_limit_s": 2.0,
            "pass_threshold": 0.9,
            "example": {"input": "2\n1 2\n", "output": "3"},
            "test_cases": [],
        },
        "reference_solution": "print(1)",
        "reference_language": "python",
        "warnings": [],
        "cost_usd": cost,
    }


def _fake_set(*variants: dict[str, Any], warnings: list[str] | None = None):
    async def _f(**_kwargs: object) -> dict[str, Any]:
        return {"engine": "test", "warnings": warnings or [], "variants": list(variants)}

    return _f


def _draft_body(**extra: Any) -> dict[str, Any]:
    return {"brief": "longest increasing run", "language": "python", "count": 3, **extra}


def _variant_create(qid: str, label: str) -> dict[str, Any]:
    q = _sample_question(qid)
    q["label"] = label
    return q


def _set_create_body(**extra: Any) -> dict[str, Any]:
    return {
        "title": "Longest increasing run",
        "brief": "longest increasing run",
        "language": "python",
        "difficulty": "medium",
        "variants": [_variant_create("va", "A"), _variant_create("vb", "B")],
        **extra,
    }


# --- draft ------------------------------------------------------------------


def test_draft_variant_set_success(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(
        agent_client, "draft_set", _fake_set(_variant_payload("va"), _variant_payload("vb"), _variant_payload("vc"))
    )
    r = client.post("/variant-sets/draft", json=_draft_body())
    assert r.status_code == 200
    body = r.json()
    assert [v["label"] for v in body["variants"]] == ["A", "B", "C"]
    assert body["engine"] == "test"
    assert body["cost_usd"] == 0.03  # summed across variants
    # reshaped into the create form's question shape
    assert body["variants"][0]["question"]["required_complexity"] == "O(n)"


def test_draft_variant_set_partial_skips_failed_variant(client: TestClient, monkeypatch) -> None:
    failed = {"question": None, "warnings": ["reference didn't compile"]}
    monkeypatch.setattr(
        agent_client,
        "draft_set",
        _fake_set(_variant_payload("va"), failed, _variant_payload("vc"),
                  warnings=["Only 2 of 3 variants drafted successfully."]),
    )
    r = client.post("/variant-sets/draft", json=_draft_body())
    assert r.status_code == 200
    body = r.json()
    assert [v["label"] for v in body["variants"]] == ["A", "B"]  # labels reflow over usable
    assert any("Only 2 of 3" in w for w in body["warnings"])


def test_draft_variant_set_requires_auth(anon_client: TestClient) -> None:
    assert anon_client.post("/variant-sets/draft", json=_draft_body()).status_code == 401


def test_draft_variant_set_count_bounds(client: TestClient) -> None:
    assert client.post("/variant-sets/draft", json=_draft_body(count=1)).status_code == 422
    assert client.post("/variant-sets/draft", json=_draft_body(count=9)).status_code == 422


def test_draft_variant_set_rate_limited(anon_client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(config, "DRAFT_RATE_LIMIT_MAX", 1)
    monkeypatch.setattr(agent_client, "draft_set", _fake_set(_variant_payload("va"), _variant_payload("vb")))
    tok = register_interviewer(anon_client, "vset-rl@x.io")
    assert anon_client.post("/variant-sets/draft", json=_draft_body(), headers=_auth(tok)).status_code == 200
    assert anon_client.post("/variant-sets/draft", json=_draft_body(), headers=_auth(tok)).status_code == 429


# --- persist / list / detail ------------------------------------------------


def test_create_and_get_variant_set(client: TestClient) -> None:
    r = client.post("/variant-sets", json=_set_create_body())
    assert r.status_code == 201
    created = r.json()
    set_id = created["id"]
    assert [v["variant_label"] for v in created["variants"]] == ["A", "B"]

    got = client.get(f"/variant-sets/{set_id}").json()
    assert got["title"] == "Longest increasing run"
    assert got["brief"] == "longest increasing run"
    assert len(got["variants"]) == 2
    # a variant IS a question — reachable on the questions route, tagged with membership
    vid = got["variants"][0]["id"]
    q = client.get(f"/questions/{vid}").json()
    assert q["id"] == vid


def test_list_variant_sets_shows_count(client: TestClient) -> None:
    client.post("/variant-sets", json=_set_create_body())
    page = client.get("/variant-sets").json()
    assert page["total"] >= 1
    row = page["items"][0]
    assert row["variant_count"] == 2
    assert row["difficulty"] == "medium"


def test_create_variant_set_enforces_case_floor(client: TestClient) -> None:
    body = _set_create_body()
    body["variants"][0]["test_cases"] = [  # drop the performance case
        tc for tc in body["variants"][0]["test_cases"] if tc["category"] != "performance"
    ]
    r = client.post("/variant-sets", json=body)
    assert r.status_code == 422
    assert "performance" in r.text


def test_variant_set_owner_scoped(anon_client: TestClient) -> None:
    tok_a = register_interviewer(anon_client, "vs-a@x.io")
    tok_b = register_interviewer(anon_client, "vs-b@x.io")
    set_id = anon_client.post("/variant-sets", json=_set_create_body(), headers=_auth(tok_a)).json()["id"]
    # B cannot read A's set — a single 404 so ids aren't probeable.
    assert anon_client.get(f"/variant-sets/{set_id}", headers=_auth(tok_b)).status_code == 404
    assert anon_client.get(f"/variant-sets/{set_id}", headers=_auth(tok_a)).status_code == 200


def test_create_variant_set_needs_two_variants(client: TestClient) -> None:
    body = _set_create_body(variants=[_variant_create("solo", "A")])
    assert client.post("/variant-sets", json=body).status_code == 422
