"""I1 stage 1 — browser telemetry: the candidate's signal write path, the
interviewer's read path, and the per-assessment `proctored` toggle. Fully
offline (the agent call is mocked); no browser is involved, so these exercise
the contract the candidate UI speaks, not the capture itself."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from conftest import async_return, register_interviewer
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from assessment_platform import agent_client
from assessment_platform import db as db_module
from assessment_platform.models import CandidateAttempt, IntegrityEvent


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _question(qid: str) -> dict[str, Any]:
    return {
        "id": qid,
        "title": f"Q {qid}",
        "prompt": "p",
        "constraints": "c",
        "time_limit_s": 2.0,
        "pass_threshold": 0.9,
        "test_cases": [
            {"name": "t1", "stdin": "1\n", "expected": "1", "category": "correctness"},
            {"name": "t2", "stdin": "2\n", "expected": "2", "category": "correctness"},
            {"name": "t3", "stdin": "3\n", "expected": "3", "category": "correctness"},
            {"name": "t4", "stdin": "4\n", "expected": "4", "category": "correctness"},
            {"name": "big", "stdin": "9\n", "expected": "9", "category": "performance"},
        ],
    }


def _invited(client: TestClient, qid: str = "q1", email: str = "cand@x.io") -> str:
    """A live single-question invite, started by `email`. Returns its token."""
    assert client.post("/questions", json=_question(qid)).status_code == 201
    resp = client.post(f"/questions/{qid}/invites", json={"recipients": [email]})
    assert resp.status_code == 201
    token = resp.json()["token"]
    started = client.post(
        f"/invite/{token}/start", json={"candidate_name": "Cand", "candidate_email": email}
    )
    assert started.status_code == 200
    return token


def _events(**over: Any) -> dict[str, Any]:
    body = {"kind": "focus_loss", "offset_ms": 1000, "duration_ms": 4000}
    body.update(over)
    return body


def _age_attempt(*, minutes: int) -> None:
    """Push the (single) attempt's clock start into the past, modelling a sitting
    that has actually been running — offsets are clamped to elapsed time, so a
    just-started attempt flattens every offset to ~0."""
    with Session(db_module.engine) as s:
        attempt = s.exec(select(CandidateAttempt)).one()
        attempt.started_at = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        s.add(attempt)
        s.commit()


def _submit(client: TestClient, token: str, monkeypatch, email: str = "cand@x.io") -> str:
    monkeypatch.setattr(agent_client, "trigger_assessment", async_return("job-1"))
    resp = client.post(
        f"/invite/{token}/submit",
        json={
            "candidate_name": "Cand",
            "candidate_email": email,
            "language": "python",
            "code": "print(1)",
        },
    )
    assert resp.status_code == 201
    return resp.json()["submission_id"]


# --- the candidate write path ---------------------------------------------- #


def test_events_are_recorded_for_an_invited_candidate(client) -> None:
    token = _invited(client)
    resp = client.post(
        f"/invite/{token}/events",
        json={
            "candidate_email": "cand@x.io",
            "question_id": "q1",
            "events": [
                _events(),
                _events(kind="paste_external", offset_ms=2000, duration_ms=None, size=1284, blocked=True),
            ],
        },
    )
    assert resp.status_code == 204
    with Session(db_module.engine) as s:
        rows = s.exec(select(IntegrityEvent)).all()
    assert [(r.kind, r.blocked, r.size) for r in rows] == [
        ("focus_loss", False, None),
        ("paste_external", True, 1284),
    ]


def test_events_reject_an_uninvited_email_and_a_dead_link(client) -> None:
    token = _invited(client)
    stranger = client.post(
        f"/invite/{token}/events",
        json={"candidate_email": "other@x.io", "events": [_events()]},
    )
    assert stranger.status_code == 403

    assert client.post(f"/questions/q1/invites/{token}/revoke").status_code == 200
    dead = client.post(
        f"/invite/{token}/events",
        json={"candidate_email": "cand@x.io", "events": [_events()]},
    )
    assert dead.status_code == 410
    unknown = client.post(
        "/invite/nosuchtoken/events",
        json={"candidate_email": "cand@x.io", "events": [_events()]},
    )
    assert unknown.status_code == 404


def test_events_are_accepted_after_submitting(client, monkeypatch) -> None:
    # The last batch of a sitting is flushed alongside the submit, so this route
    # must NOT reuse the "already submitted" gate the run/submit paths use.
    token = _invited(client)
    _submit(client, token, monkeypatch)
    resp = client.post(
        f"/invite/{token}/events",
        json={"candidate_email": "cand@x.io", "events": [_events(kind="fullscreen_exit")]},
    )
    assert resp.status_code == 204


def test_offsets_are_clamped_to_the_elapsed_window(client) -> None:
    token = _invited(client)
    # A forged offset an hour into a sitting that started seconds ago is clamped
    # to what the server can vouch for.
    client.post(
        f"/invite/{token}/events",
        json={"candidate_email": "cand@x.io", "events": [_events(offset_ms=3_600_000)]},
    )
    with Session(db_module.engine) as s:
        row = s.exec(select(IntegrityEvent)).one()
        attempt = s.exec(select(CandidateAttempt)).one()
        started = attempt.started_at
    elapsed_ms = (datetime.now(timezone.utc) - started.replace(tzinfo=timezone.utc)).total_seconds()
    assert row.offset_ms <= elapsed_ms * 1000 + 1
    assert row.offset_ms < 3_600_000


def test_events_never_start_a_candidates_clock(client) -> None:
    # Recording that someone switched tabs must not stamp the timer: a signal
    # arriving before /start is kept, at offset 0, with no attempt created.
    assert client.post("/questions", json=_question("q1")).status_code == 201
    resp = client.post("/questions/q1/invites", json={"recipients": ["cand@x.io"]})
    token = resp.json()["token"]
    posted = client.post(
        f"/invite/{token}/events",
        json={"candidate_email": "cand@x.io", "events": [_events(offset_ms=5000)]},
    )
    assert posted.status_code == 204
    with Session(db_module.engine) as s:
        assert s.exec(select(CandidateAttempt)).all() == []
        assert s.exec(select(IntegrityEvent)).one().offset_ms == 0


def test_a_batch_is_bounded(client) -> None:
    token = _invited(client)
    resp = client.post(
        f"/invite/{token}/events",
        json={"candidate_email": "cand@x.io", "events": [_events()] * 51},
    )
    assert resp.status_code == 422
    empty = client.post(
        f"/invite/{token}/events", json={"candidate_email": "cand@x.io", "events": []}
    )
    assert empty.status_code == 422


# --- the interviewer read path --------------------------------------------- #


def test_report_summarizes_the_sitting_in_offset_order(client, monkeypatch) -> None:
    token = _invited(client)
    _age_attempt(minutes=5)  # so the reported offsets are inside the clamp window
    client.post(
        f"/invite/{token}/events",
        json={
            "candidate_email": "cand@x.io",
            "question_id": "q1",
            "events": [
                _events(kind="fullscreen_exit", offset_ms=900, duration_ms=11_000),
                _events(kind="focus_loss", offset_ms=100, duration_ms=4000),
                _events(kind="paste_external", offset_ms=500, duration_ms=None, size=99, blocked=True),
                _events(kind="paste_internal", offset_ms=700, duration_ms=None, size=12),
            ],
        },
    )
    sub_id = _submit(client, token, monkeypatch)
    report = client.get(f"/submissions/{sub_id}/integrity")
    assert report.status_code == 200
    body = report.json()

    assert body["monitored"] is True
    assert [e["kind"] for e in body["events"]] == [
        "focus_loss",
        "paste_external",
        "paste_internal",
        "fullscreen_exit",
    ]
    assert body["events"][0]["question_title"] == "Q q1"
    assert body["summary"] == {
        "total": 4,
        "focus_losses": 1,
        "away_ms": 4000,
        "fullscreen_exits": 1,
        "pastes_blocked": 1,
        "devtools_opens": 0,
    }


def test_report_counts_only_pastes_that_were_actually_blocked(client, monkeypatch) -> None:
    # Enforcement is best-effort: an outside paste the client failed to block is
    # still recorded, but the summary must not claim it was stopped.
    token = _invited(client)
    client.post(
        f"/invite/{token}/events",
        json={
            "candidate_email": "cand@x.io",
            "events": [_events(kind="paste_external", duration_ms=None, size=50, blocked=False)],
        },
    )
    sub_id = _submit(client, token, monkeypatch)
    body = client.get(f"/submissions/{sub_id}/integrity").json()
    assert body["summary"]["pastes_blocked"] == 0
    assert body["events"][0]["blocked"] is False


def test_report_is_owner_scoped(client, anon_client, monkeypatch) -> None:
    token = _invited(client)
    sub_id = _submit(client, token, monkeypatch)
    other = register_interviewer(anon_client, "other@test.io", name="Other")
    resp = anon_client.get(f"/submissions/{sub_id}/integrity", headers=_auth(other))
    assert resp.status_code in (403, 404)


def test_report_for_a_direct_submission_has_no_sitting(client, monkeypatch) -> None:
    # The interviewer's own POST /submissions has no invite and no candidate, so
    # there is nothing to monitor — and "no signals" must not read as "clean".
    assert client.post("/questions", json=_question("q1")).status_code == 201
    monkeypatch.setattr(agent_client, "trigger_assessment", async_return("job-1"))
    created = client.post(
        "/submissions",
        json={"question_id": "q1", "candidate": "Me", "language": "python", "code": "print(1)"},
    )
    assert created.status_code == 201
    body = client.get(f"/submissions/{created.json()['id']}/integrity").json()
    assert body["monitored"] is False
    assert body["events"] == []


# --- the per-assessment toggle --------------------------------------------- #


def test_assessment_proctored_defaults_on_and_round_trips(client) -> None:
    assert client.post("/questions", json=_question("q1")).status_code == 201
    created = client.post("/assessments", json={"title": "A", "question_ids": ["q1"]})
    assert created.status_code == 201
    aid = created.json()["id"]
    assert created.json()["proctored"] is True  # omitted ⇒ monitored

    updated = client.put(
        f"/assessments/{aid}",
        json={"title": "A", "question_ids": ["q1"], "proctored": False},
    )
    assert updated.status_code == 200
    assert updated.json()["proctored"] is False
    assert client.get(f"/assessments/{aid}").json()["proctored"] is False


def test_candidate_view_carries_the_sittings_monitoring_state(client) -> None:
    assert client.post("/questions", json=_question("q1")).status_code == 201
    aid = client.post(
        "/assessments",
        json={"title": "A", "question_ids": ["q1"], "proctored": False},
    ).json()["id"]
    invite = client.post(f"/assessments/{aid}/invites", json={"recipients": ["cand@x.io"]})
    token = invite.json()["token"]
    started = client.post(
        f"/invite/{token}/start", json={"candidate_name": "C", "candidate_email": "cand@x.io"}
    )
    assert started.json()["proctored"] is False

    # A legacy single-question ("Quick screen") invite has no assessment to read
    # the toggle from and is always monitored.
    quick = _invited(client, qid="q2", email="cand2@x.io")
    view = client.post(
        f"/invite/{quick}/start", json={"candidate_name": "C", "candidate_email": "cand2@x.io"}
    )
    assert view.json()["proctored"] is True


def test_report_reports_an_unmonitored_sitting_as_such(client, monkeypatch) -> None:
    assert client.post("/questions", json=_question("q1")).status_code == 201
    aid = client.post(
        "/assessments",
        json={"title": "A", "question_ids": ["q1"], "proctored": False},
    ).json()["id"]
    token = client.post(
        f"/assessments/{aid}/invites", json={"recipients": ["cand@x.io"]}
    ).json()["token"]
    client.post(
        f"/invite/{token}/start", json={"candidate_name": "C", "candidate_email": "cand@x.io"}
    )
    monkeypatch.setattr(agent_client, "trigger_assessment", async_return("job-1"))
    sub_id = client.post(
        f"/invite/{token}/submit",
        json={
            "candidate_name": "C",
            "candidate_email": "cand@x.io",
            "language": "python",
            "code": "print(1)",
            "question_id": "q1",
        },
    ).json()["submission_id"]
    body = client.get(f"/submissions/{sub_id}/integrity").json()
    assert body["monitored"] is False
    assert body["summary"]["total"] == 0


def test_signals_are_shared_across_a_sittings_submissions(client, monkeypatch) -> None:
    # A tab switch belongs to the sitting, so both questions' submissions show it.
    for qid in ("q1", "q2"):
        assert client.post("/questions", json=_question(qid)).status_code == 201
    aid = client.post("/assessments", json={"title": "A", "question_ids": ["q1", "q2"]}).json()["id"]
    token = client.post(
        f"/assessments/{aid}/invites", json={"recipients": ["cand@x.io"]}
    ).json()["token"]
    client.post(
        f"/invite/{token}/start", json={"candidate_name": "C", "candidate_email": "cand@x.io"}
    )
    client.post(
        f"/invite/{token}/events",
        json={
            "candidate_email": "cand@x.io",
            "question_id": "q2",
            "events": [_events(kind="devtools", duration_ms=None)],
        },
    )
    monkeypatch.setattr(agent_client, "trigger_assessment", async_return("job-1"))
    ids = []
    for qid in ("q1", "q2"):
        ids.append(
            client.post(
                f"/invite/{token}/submit",
                json={
                    "candidate_name": "C",
                    "candidate_email": "cand@x.io",
                    "language": "python",
                    "code": "print(1)",
                    "question_id": qid,
                },
            ).json()["submission_id"]
        )
    for sub_id in ids:
        body = client.get(f"/submissions/{sub_id}/integrity").json()
        assert body["summary"]["devtools_opens"] == 1
        # …and each event names the question that was open when it fired.
        assert body["events"][0]["question_title"] == "Q q2"


def test_events_of_one_candidate_do_not_leak_into_anothers_report(client, monkeypatch) -> None:
    assert client.post("/questions", json=_question("q1")).status_code == 201
    invite = client.post(
        "/questions/q1/invites", json={"recipients": ["a@x.io", "b@x.io"]}
    ).json()
    token = invite["token"]
    for email in ("a@x.io", "b@x.io"):
        client.post(
            f"/invite/{token}/start", json={"candidate_name": email, "candidate_email": email}
        )
    client.post(
        f"/invite/{token}/events",
        json={"candidate_email": "a@x.io", "events": [_events(kind="focus_loss")]},
    )
    monkeypatch.setattr(agent_client, "trigger_assessment", async_return("job-1"))
    b_sub = client.post(
        f"/invite/{token}/submit",
        json={
            "candidate_name": "B",
            "candidate_email": "b@x.io",
            "language": "python",
            "code": "print(1)",
        },
    ).json()["submission_id"]
    body = client.get(f"/submissions/{b_sub}/integrity").json()
    assert body["summary"]["total"] == 0


def test_a_stale_offset_from_a_long_sitting_is_kept(client) -> None:
    # The clamp must not flatten legitimate offsets in a long sitting: age the
    # attempt, then a 10-minute offset is inside the window and survives.
    token = _invited(client)
    _age_attempt(minutes=30)
    client.post(
        f"/invite/{token}/events",
        json={"candidate_email": "cand@x.io", "events": [_events(offset_ms=600_000)]},
    )
    with Session(db_module.engine) as s:
        assert s.exec(select(IntegrityEvent)).one().offset_ms == 600_000


# --- the sitting's monitoring state is frozen, not re-read ------------------ #


def _assessment_sitting(client: TestClient, *, proctored: bool, qid: str = "q1") -> tuple[str, str]:
    """An assessment + a started invite for cand@x.io. Returns (assessment_id, token)."""
    assert client.post("/questions", json=_question(qid)).status_code == 201
    aid = client.post(
        "/assessments",
        json={"title": "A", "question_ids": [qid], "proctored": proctored},
    ).json()["id"]
    token = client.post(
        f"/assessments/{aid}/invites", json={"recipients": ["cand@x.io"]}
    ).json()["token"]
    client.post(
        f"/invite/{token}/start", json={"candidate_name": "C", "candidate_email": "cand@x.io"}
    )
    return aid, token


def _submit_assessment(client: TestClient, token: str, monkeypatch, qid: str = "q1") -> str:
    monkeypatch.setattr(agent_client, "trigger_assessment", async_return("job-1"))
    return client.post(
        f"/invite/{token}/submit",
        json={
            "candidate_name": "C",
            "candidate_email": "cand@x.io",
            "language": "python",
            "code": "print(1)",
            "question_id": qid,
        },
    ).json()["submission_id"]


def test_turning_monitoring_off_later_cannot_hide_recorded_signals(client, monkeypatch) -> None:
    aid, token = _assessment_sitting(client, proctored=True)
    client.post(
        f"/invite/{token}/events",
        json={"candidate_email": "cand@x.io", "events": [_events(kind="fullscreen_exit")]},
    )
    sub_id = _submit_assessment(client, token, monkeypatch)

    # The interviewer relaxes the assessment AFTER this sitting ran.
    assert (
        client.put(
            f"/assessments/{aid}",
            json={"title": "A", "question_ids": ["q1"], "proctored": False},
        ).status_code
        == 200
    )
    body = client.get(f"/submissions/{sub_id}/integrity").json()
    # The sitting WAS monitored; its evidence must read the same as before.
    assert body["monitored"] is True
    assert body["summary"]["total"] == 1


def test_turning_monitoring_on_later_cannot_make_a_sitting_look_clean(client, monkeypatch) -> None:
    # The inverse, and the worse one: a sitting that genuinely ran unmonitored
    # must never come back as "no signals — stayed in fullscreen".
    aid, token = _assessment_sitting(client, proctored=False)
    sub_id = _submit_assessment(client, token, monkeypatch)
    assert (
        client.put(
            f"/assessments/{aid}",
            json={"title": "A", "question_ids": ["q1"], "proctored": True},
        ).status_code
        == 200
    )
    body = client.get(f"/submissions/{sub_id}/integrity").json()
    assert body["monitored"] is False


def test_the_invite_freezes_the_setting_at_mint_time(client) -> None:
    aid, first = _assessment_sitting(client, proctored=True)
    client.put(
        f"/assessments/{aid}", json={"title": "A", "question_ids": ["q1"], "proctored": False}
    )
    # A NEW invite picks up the new setting; the existing one keeps the old.
    second = client.post(
        f"/assessments/{aid}/invites", json={"recipients": ["later@x.io"]}
    ).json()["token"]
    assert client.get(f"/invite/{first}").json()["proctored"] is True
    assert client.get(f"/invite/{second}").json()["proctored"] is False


# --- the attempts grid surfaces signals without a submission ---------------- #


def test_attempts_grid_counts_signals_for_a_candidate_who_never_submitted(client) -> None:
    aid, token = _assessment_sitting(client, proctored=True)
    client.post(
        f"/invite/{token}/events",
        json={
            "candidate_email": "cand@x.io",
            "events": [
                _events(kind="focus_loss"),
                _events(kind="paste_external", duration_ms=None, size=900, blocked=True),
            ],
        },
    )
    rows = client.get(f"/assessments/{aid}/attempts").json()
    assert len(rows) == 1
    # No submission exists — this is the only surface that can show these.
    assert rows[0]["questions"][0]["submitted"] is False
    assert rows[0]["integrity_signals"] == 2
    assert rows[0]["integrity_blocked"] == 1


def test_attempts_grid_separates_unmonitored_from_no_signals(client) -> None:
    aid1, _ = _assessment_sitting(client, proctored=True)
    quiet_rows = client.get(f"/assessments/{aid1}/attempts").json()
    assert quiet_rows[0]["integrity_signals"] == 0  # monitored, nothing recorded

    aid2, _ = _assessment_sitting(client, proctored=False, qid="q2")
    rows = client.get(f"/assessments/{aid2}/attempts").json()
    assert rows[0]["integrity_signals"] is None  # nothing to record — not zero


# --- the list / export surfaces (the I1 gap-closure: they carried `late` but
# --- no integrity signal, so the CSV silently lost a signal class the UI has) - #


def test_lists_and_export_carry_the_sittings_signal_count(client, monkeypatch) -> None:
    _, token = _assessment_sitting(client, proctored=True)
    client.post(
        f"/invite/{token}/events",
        json={
            "candidate_email": "cand@x.io",
            "events": [
                _events(kind="focus_loss"),
                _events(kind="paste_external", duration_ms=None, size=900, blocked=True),
            ],
        },
    )
    _submit_assessment(client, token, monkeypatch)

    row = client.get("/submissions").json()["items"][0]
    assert row["integrity_signals"] == 2
    assert row["integrity_blocked"] == 1

    q_row = client.get("/questions/q1/submissions").json()["items"][0]
    assert q_row["integrity_signals"] == 2
    assert q_row["integrity_blocked"] == 1

    lines = client.get("/submissions/export").text.splitlines()
    header = lines[0].split(",")
    signals_col = header.index("integrity_signals")
    blocked_col = header.index("integrity_blocked_pastes")
    cells = lines[1].split(",")
    assert cells[signals_col] == "2"
    assert cells[blocked_col] == "1"


def test_lists_and_export_report_unmonitored_as_blank_not_zero(client, monkeypatch) -> None:
    _, token = _assessment_sitting(client, proctored=False)
    _submit_assessment(client, token, monkeypatch)

    row = client.get("/submissions").json()["items"][0]
    assert row["integrity_signals"] is None

    q_row = client.get("/questions/q1/submissions").json()["items"][0]
    assert q_row["integrity_signals"] is None

    lines = client.get("/submissions/export").text.splitlines()
    header = lines[0].split(",")
    signals_col = header.index("integrity_signals")
    cells = lines[1].split(",")
    assert cells[signals_col] == ""  # unmonitored ⇒ blank, never a clean-looking 0


def test_a_direct_submission_has_no_sitting_in_the_lists(client, monkeypatch) -> None:
    # An interviewer's own POST /submissions has no invite/candidate — no sitting
    # at all, which reads as unmonitored, not as a clean zero.
    assert client.post("/questions", json=_question("q1")).status_code == 201
    monkeypatch.setattr(agent_client, "trigger_assessment", async_return("job-1"))
    assert (
        client.post(
            "/submissions",
            json={
                "question_id": "q1",
                "candidate": "Cand",
                "language": "python",
                "code": "print(1)",
            },
        ).status_code
        == 201
    )
    row = client.get("/submissions").json()["items"][0]
    assert row["integrity_signals"] is None
    assert row["integrity_blocked"] == 0


# --- the risk score (I1 integrity report) ----------------------------------- #


def test_report_carries_a_risk_score_with_reasons(client, monkeypatch) -> None:
    token = _invited(client)
    client.post(
        f"/invite/{token}/events",
        json={
            "candidate_email": "cand@x.io",
            "question_id": "q1",
            "events": [
                _events(kind="paste_external", duration_ms=None, size=900, blocked=True),
                _events(kind="devtools", duration_ms=None),
            ],
        },
    )
    sub_id = _submit(client, token, monkeypatch)
    risk = client.get(f"/submissions/{sub_id}/integrity").json()["risk"]
    assert risk["score"] == 45
    assert risk["level"] == "elevated"
    assert [r["label"] for r in risk["reasons"]] == [
        "1 outside paste blocked",
        "devtools opened 1 time",
    ]


def test_a_quiet_monitored_sitting_scores_an_explicit_none_level(client, monkeypatch) -> None:
    token = _invited(client)
    sub_id = _submit(client, token, monkeypatch)
    risk = client.get(f"/submissions/{sub_id}/integrity").json()["risk"]
    assert risk == {"score": 0, "level": "none", "reasons": []}


def test_an_unmonitored_quiet_sitting_has_no_risk_to_report(client, monkeypatch) -> None:
    # null, not "none": an unmonitored sitting recorded nothing, so a score would
    # dress up absence-of-evidence as a clean reading.
    _, token = _assessment_sitting(client, proctored=False)
    sub_id = _submit_assessment(client, token, monkeypatch)
    assert client.get(f"/submissions/{sub_id}/integrity").json()["risk"] is None


def test_attempts_grid_carries_the_risk_level(client) -> None:
    aid, token = _assessment_sitting(client, proctored=True)
    client.post(
        f"/invite/{token}/events",
        json={
            "candidate_email": "cand@x.io",
            "events": [
                _events(kind="paste_external", duration_ms=None, size=900, blocked=True),
                _events(kind="paste_external", duration_ms=None, size=901, blocked=True),
            ],
        },
    )
    rows = client.get(f"/assessments/{aid}/attempts").json()
    assert rows[0]["integrity_risk"] == "high"

    quiet_aid, _ = _assessment_sitting(client, proctored=True, qid="q2")
    assert client.get(f"/assessments/{quiet_aid}/attempts").json()[0]["integrity_risk"] == "none"

    off_aid, _ = _assessment_sitting(client, proctored=False, qid="q3")
    assert client.get(f"/assessments/{off_aid}/attempts").json()[0]["integrity_risk"] is None
