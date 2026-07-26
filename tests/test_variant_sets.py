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


# --- assignment (invites) ---------------------------------------------------


def _make_set(client: TestClient) -> dict[str, Any]:
    """Create a 2-variant set and return its detail (id + variants)."""
    return client.post("/variant-sets", json=_set_create_body()).json()


def test_variant_set_invites_round_robin(client: TestClient) -> None:
    vs = _make_set(client)
    labels = [v["variant_label"] for v in vs["variants"]]  # ['A', 'B']
    r = client.post(
        f"/variant-sets/{vs['id']}/invites",
        json={"recipients": ["a@x.io", "b@x.io", "c@x.io"]},
    )
    assert r.status_code == 201
    invites = r.json()
    assert len(invites) == 3  # one invite per recipient
    # A, B, then wraps back to A
    assert [i["variant_label"] for i in invites] == [labels[0], labels[1], labels[0]]
    assert all(i["variant_set_id"] == vs["id"] for i in invites)
    # each invite is a normal single-question invite (question_id = assigned variant)
    assert all(i["question_id"] for i in invites)


def test_variant_set_invites_continue_rotation_across_calls(client: TestClient) -> None:
    vs = _make_set(client)
    labels = [v["variant_label"] for v in vs["variants"]]
    first = client.post(f"/variant-sets/{vs['id']}/invites", json={"recipients": ["a@x.io"]}).json()
    second = client.post(f"/variant-sets/{vs['id']}/invites", json={"recipients": ["b@x.io"]}).json()
    # the second call picks up where the first left off (A then B), not A again
    assert first[0]["variant_label"] == labels[0]
    assert second[0]["variant_label"] == labels[1]


def test_variant_set_invite_override_pins_a_variant(client: TestClient) -> None:
    vs = _make_set(client)
    pinned = vs["variants"][1]  # variant B's question id
    r = client.post(
        f"/variant-sets/{vs['id']}/invites",
        json={"recipients": ["a@x.io"], "overrides": {"a@x.io": pinned["id"]}},
    )
    assert r.status_code == 201
    assert r.json()[0]["question_id"] == pinned["id"]
    assert r.json()[0]["variant_label"] == pinned["variant_label"]


def test_variant_set_invite_override_must_be_in_set(client: TestClient) -> None:
    vs = _make_set(client)
    r = client.post(
        f"/variant-sets/{vs['id']}/invites",
        json={"recipients": ["a@x.io"], "overrides": {"a@x.io": "not-a-variant"}},
    )
    assert r.status_code == 422


def test_list_variant_set_invites_shows_assignment(client: TestClient) -> None:
    vs = _make_set(client)
    client.post(f"/variant-sets/{vs['id']}/invites", json={"recipients": ["a@x.io", "b@x.io"]})
    listed = client.get(f"/variant-sets/{vs['id']}/invites").json()
    assert {i["variant_label"] for i in listed} == {v["variant_label"] for v in vs["variants"]}


def test_variant_set_invites_owner_scoped(anon_client: TestClient) -> None:
    tok_a = register_interviewer(anon_client, "vsi-a@x.io")
    tok_b = register_interviewer(anon_client, "vsi-b@x.io")
    set_id = anon_client.post("/variant-sets", json=_set_create_body(), headers=_auth(tok_a)).json()["id"]
    r = anon_client.post(
        f"/variant-sets/{set_id}/invites", json={"recipients": ["c@x.io"]}, headers=_auth(tok_b)
    )
    assert r.status_code == 404
