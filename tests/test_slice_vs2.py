"""VS2 — variant-set slots inside a multi-question assessment.

A slot of an assessment can be a variant-set pool instead of a fixed question;
each candidate is handed a different variant (round-robin), frozen at start time,
so a leaked question is worthless. Fully offline (the agent submit call is
mocked): covers the builder API (slots), the per-candidate resolution + freeze,
submissions keyed to the assigned variant, the results view, and the A9 lock.
"""

from __future__ import annotations

from typing import Any

from conftest import async_return, register_interviewer
from fastapi.testclient import TestClient
from test_assessments import _make_questions, _question, _sub

from assessment_platform import agent_client


def _variant_q(qid: str, label: str) -> dict[str, Any]:
    q = _question(qid)
    q["label"] = label
    return q


def _make_variant_set(client: TestClient, set_id: str, *labels: str) -> tuple[str, list[str]]:
    """Persist a variant set with one variant per label; return (set_id, variant
    ids ordered by label). The persisted variant ids may be suffixed for
    uniqueness, so read them back from the create response rather than assuming."""
    variants = [_variant_q(f"{set_id}_{lbl.lower()}", lbl) for lbl in labels]
    r = client.post(
        "/variant-sets",
        json={
            "id": set_id,
            "title": f"Set {set_id}",
            "brief": "b",
            "language": "python",
            "variants": variants,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    ordered = [v["id"] for v in sorted(body["variants"], key=lambda v: v["variant_label"])]
    return body["id"], ordered


# --- builder API: slots -----------------------------------------------------


def test_create_assessment_with_variant_set_slot(client: TestClient) -> None:
    _make_questions(client, "q1")
    sid, _variants = _make_variant_set(client, "s1", "A", "B")
    r = client.post(
        "/assessments",
        json={
            "id": "a1",
            "title": "Mixed",
            "slots": [{"question_id": "q1"}, {"variant_set_id": sid}],
        },
    )
    assert r.status_code == 201, r.text
    slots = r.json()["questions"]
    assert slots[0] == {
        "question_id": "q1",
        "variant_set_id": None,
        "variant_count": None,
        "position": 0,
        "title": "Q q1",
    }
    assert slots[1]["variant_set_id"] == sid
    assert slots[1]["variant_count"] == 2
    assert slots[1]["question_id"] is None
    assert slots[1]["title"] == "Set s1"


def test_legacy_question_ids_still_accepted(client: TestClient) -> None:
    # Pre-VS2 clients send the flat question_ids; it maps to all fixed slots.
    _make_questions(client, "q1", "q2")
    r = client.post("/assessments", json={"id": "a1", "title": "A", "question_ids": ["q1", "q2"]})
    assert r.status_code == 201
    assert [s["question_id"] for s in r.json()["questions"]] == ["q1", "q2"]


def test_slot_must_set_exactly_one(client: TestClient) -> None:
    _make_questions(client, "q1")
    both = client.post(
        "/assessments",
        json={"title": "A", "slots": [{"question_id": "q1", "variant_set_id": "s1"}]},
    )
    assert both.status_code == 422
    neither = client.post("/assessments", json={"title": "A", "slots": [{}]})
    assert neither.status_code == 422


def test_both_sources_rejected(client: TestClient) -> None:
    _make_questions(client, "q1")
    r = client.post(
        "/assessments",
        json={"title": "A", "question_ids": ["q1"], "slots": [{"question_id": "q1"}]},
    )
    assert r.status_code == 422


def test_duplicate_variant_set_rejected(client: TestClient) -> None:
    sid, _ = _make_variant_set(client, "s1", "A", "B")
    r = client.post(
        "/assessments",
        json={"title": "A", "slots": [{"variant_set_id": sid}, {"variant_set_id": sid}]},
    )
    assert r.status_code == 400


def test_unknown_variant_set_rejected(client: TestClient) -> None:
    r = client.post("/assessments", json={"title": "A", "slots": [{"variant_set_id": "nope"}]})
    assert r.status_code == 404


def test_variant_set_slot_owner_scoped(anon_client: TestClient) -> None:
    owner = register_interviewer(anon_client, "o@test.io")
    other = register_interviewer(anon_client, "x@test.io")
    anon_client.headers["Authorization"] = f"Bearer {owner}"
    sid, _ = _make_variant_set(anon_client, "s1", "A", "B")
    anon_client.headers["Authorization"] = f"Bearer {other}"
    r = anon_client.post("/assessments", json={"title": "A", "slots": [{"variant_set_id": sid}]})
    # 404 not 403 — a variant set you don't own is indistinguishable from a
    # missing one, so an owner can't probe another's set ids.
    assert r.status_code == 404


# --- per-candidate resolution + freeze --------------------------------------


def _start(client: TestClient, tok: str, email: str) -> list[str]:
    data = client.post(f"/invite/{tok}/start", json={"candidate_email": email}).json()
    return [q["id"] for q in data["questions"]]


def test_each_candidate_gets_a_different_variant_round_robin(client: TestClient) -> None:
    _make_questions(client, "q1")
    sid, variants = _make_variant_set(client, "s1", "A", "B")  # variants = [A_id, B_id]
    client.post(
        "/assessments",
        json={"id": "a1", "title": "A", "slots": [{"question_id": "q1"}, {"variant_set_id": sid}]},
    )
    tok = client.post(
        "/assessments/a1/invites", json={"recipients": ["a@x.io", "b@x.io"]}
    ).json()["token"]

    a_qs = _start(client, tok, "a@x.io")
    b_qs = _start(client, tok, "b@x.io")

    # Fixed slot is shared; the set slot differs and rotates A -> B.
    assert a_qs[0] == "q1" and b_qs[0] == "q1"
    assert a_qs[1] == variants[0]  # first candidate -> variant A
    assert b_qs[1] == variants[1]  # second candidate -> variant B
    assert a_qs[1] != b_qs[1]


def test_assignment_frozen_across_reloads(client: TestClient) -> None:
    sid, variants = _make_variant_set(client, "s1", "A", "B")
    client.post("/assessments", json={"id": "a1", "title": "A", "slots": [{"variant_set_id": sid}]})
    tok = client.post("/assessments/a1/invites", json={"recipients": ["a@x.io"]}).json()["token"]

    first = _start(client, tok, "a@x.io")
    # Re-open the link many times; the variant must never change once assigned.
    for _ in range(4):
        assert _start(client, tok, "a@x.io") == first


def test_submit_and_results_track_the_assigned_variant(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(agent_client, "trigger_assessment", async_return("job"))
    sid, variants = _make_variant_set(client, "s1", "A", "B")
    client.post("/assessments", json={"id": "a1", "title": "A", "slots": [{"variant_set_id": sid}]})
    tok = client.post(
        "/assessments/a1/invites", json={"recipients": ["a@x.io", "b@x.io"]}
    ).json()["token"]

    a_qs = _start(client, tok, "a@x.io")  # -> variant A
    b_qs = _start(client, tok, "b@x.io")  # -> variant B

    # Each candidate submits their OWN assigned variant id.
    assert client.post(f"/invite/{tok}/submit", json=_sub(tok, "a@x.io", a_qs[0])).status_code == 201
    assert client.post(f"/invite/{tok}/submit", json=_sub(tok, "b@x.io", b_qs[0])).status_code == 201
    # Submitting the OTHER candidate's variant is not part of this candidate's set.
    assert (
        client.post(f"/invite/{tok}/submit", json=_sub(tok, "a@x.io", variants[1])).status_code
        == 404
    )

    attempts = client.get("/assessments/a1/attempts").json()
    by_email = {row["candidate_email"]: row for row in attempts}
    a_slot = by_email["a@x.io"]["questions"][0]
    b_slot = by_email["b@x.io"]["questions"][0]
    # The results row resolves each candidate's own variant + label, keyed under
    # the same set-slot title, and marks it submitted.
    assert a_slot["variant_set_id"] == sid and a_slot["title"] == "Set s1"
    assert a_slot["question_id"] == variants[0] and a_slot["variant_label"] == "A"
    assert b_slot["question_id"] == variants[1] and b_slot["variant_label"] == "B"
    assert a_slot["submitted"] is True and b_slot["submitted"] is True


# --- A9 lock ----------------------------------------------------------------


def test_update_locks_slot_set_once_invited(client: TestClient) -> None:
    _make_questions(client, "q1")
    sid, _ = _make_variant_set(client, "s1", "A", "B")
    client.post(
        "/assessments",
        json={"id": "a1", "title": "A", "slots": [{"question_id": "q1"}, {"variant_set_id": sid}]},
    )
    client.post("/assessments/a1/invites", json={"recipients": ["c@x.io"]})

    # Same slots, changed title -> allowed.
    same = client.put(
        "/assessments/a1",
        json={"title": "Renamed", "slots": [{"question_id": "q1"}, {"variant_set_id": sid}]},
    )
    assert same.status_code == 200
    assert same.json()["title"] == "Renamed"

    # Dropping the variant-set slot changes the set -> 409.
    changed = client.put("/assessments/a1", json={"title": "Renamed", "slots": [{"question_id": "q1"}]})
    assert changed.status_code == 409
