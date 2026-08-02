"""integrity.py — the DB-free risk scorer (I1 integrity report). Pure unit
tests: weights, caps, tiers, level boundaries, and the two context-only kinds
that must never score."""

from __future__ import annotations

from dataclasses import dataclass

from assessment_platform.integrity import risk_level, risk_score


@dataclass
class Ev:
    kind: str
    duration_ms: int | None = None
    blocked: bool = False


def test_empty_events_score_zero_with_no_reasons() -> None:
    assert risk_score([]) == (0, [])
    assert risk_level(0) == "none"


def test_a_blocked_outside_paste_alone_reads_elevated() -> None:
    score, reasons = risk_score([Ev("paste_external", blocked=True)])
    assert score == 30
    assert risk_level(score) == "elevated"
    assert reasons == [("1 outside paste blocked", 30)]


def test_two_blocked_pastes_alone_read_high_and_cap_there() -> None:
    two, _ = risk_score([Ev("paste_external", blocked=True)] * 2)
    five, _ = risk_score([Ev("paste_external", blocked=True)] * 5)
    assert two == five == 60  # capped: more repeats add nothing
    assert risk_level(two) == "high"


def test_an_unblocked_external_paste_does_not_score() -> None:
    # blocked=False = the client recorded but did not block (defensive: today's
    # client always blocks outside pastes; the scorer must not assume it).
    assert risk_score([Ev("paste_external", blocked=False)]) == (0, [])


def test_context_kinds_never_score() -> None:
    assert risk_score([Ev("paste_internal"), Ev("fullscreen_denied")]) == (0, [])


def test_ambient_signals_accumulate_slowly_and_cap() -> None:
    score, reasons = risk_score([Ev("focus_loss", duration_ms=1_000)] * 3)
    assert score == 12
    assert risk_level(score) == "low"
    # 30 flickers cannot masquerade as a severe signal: capped at 20.
    capped, _ = risk_score([Ev("focus_loss", duration_ms=1_000)] * 30)
    assert capped == 20


def test_time_away_tiers_replace_not_stack() -> None:
    short, r_short = risk_score([Ev("focus_loss", duration_ms=150_000)])
    long, r_long = risk_score([Ev("focus_loss", duration_ms=360_000)])
    assert short == 4 + 10 and long == 4 + 20  # count points + one away tier
    assert [p for _, p in r_short] == [10, 4]
    assert [p for _, p in r_long] == [20, 4]


def test_reasons_are_sorted_by_contribution() -> None:
    _, reasons = risk_score(
        [Ev("focus_loss", duration_ms=1_000), Ev("paste_external", blocked=True), Ev("devtools")]
    )
    assert [p for _, p in reasons] == sorted((p for _, p in reasons), reverse=True)
    assert reasons[0][0] == "1 outside paste blocked"


def test_score_caps_at_100() -> None:
    events = (
        [Ev("paste_external", blocked=True)] * 3
        + [Ev("devtools")] * 3
        + [Ev("fullscreen_exit")] * 4
        + [Ev("focus_loss", duration_ms=400_000)] * 6
    )
    score, _ = risk_score(events)
    assert score == 100


def test_level_boundaries() -> None:
    assert risk_level(1) == "low"
    assert risk_level(19) == "low"
    assert risk_level(20) == "elevated"
    assert risk_level(49) == "elevated"
    assert risk_level(50) == "high"
