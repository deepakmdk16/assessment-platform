"""Integrity risk scoring (I1) — turns a sitting's raw signals into an
actionable, *explainable* triage hint: a 0-100 score, a level, and the reasons
that drove it, so the interviewer reads "high — 2 outside pastes blocked"
instead of eyeballing a raw timeline.

DB-free and deterministic (like analytics.py): pure functions over event
values, unit-tested without a database. The weights are editorial, not
statistical — chosen so the severe, deliberate signals (an outside paste, an
open devtools panel) dominate and the ambient ones (brief focus losses)
accumulate slowly with a low cap. Two kinds score zero by design:
`paste_internal` (allowed; context) and `fullscreen_denied` (the browser
refused fullscreen — context, not misconduct).

THE SCORE IS A DETERRENT-GRADE TRIAGE HINT, NOT PROOF. It runs over
client-reported, browser-side signals, so a zero never certifies a clean
sitting and a high score is a reason to look, not a verdict. It must never
gate or weight the assessment verdict (CONVENTIONS: signals never touch the
verdict).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, Protocol

RiskLevel = Literal["none", "low", "elevated", "high"]

# Per-event points and per-kind caps. Caps keep one repeated ambient signal
# (say, 30 focus flickers from a flaky window manager) from masquerading as
# the severe kinds, which alone can reach "high".
_PASTE_BLOCKED_POINTS, _PASTE_BLOCKED_CAP = 30, 60
_DEVTOOLS_POINTS, _DEVTOOLS_CAP = 15, 30
_FULLSCREEN_EXIT_POINTS, _FULLSCREEN_EXIT_CAP = 8, 24
_FOCUS_LOSS_POINTS, _FOCUS_LOSS_CAP = 4, 20
# Total time away from the tab, tiered (the larger tier replaces the smaller).
_AWAY_LONG_MS, _AWAY_LONG_POINTS = 300_000, 20
_AWAY_SHORT_MS, _AWAY_SHORT_POINTS = 120_000, 10

_LEVEL_ELEVATED, _LEVEL_HIGH = 20, 50
_SCORE_MAX = 100


class _EventLike(Protocol):
    """The three fields scoring reads — satisfied by both models.IntegrityEvent
    and schemas.IntegrityEventOut, so callers pass rows straight through."""

    @property
    def kind(self) -> str: ...
    @property
    def duration_ms(self) -> int | None: ...
    @property
    def blocked(self) -> bool: ...


def risk_score(events: Sequence[_EventLike]) -> tuple[int, list[tuple[str, int]]]:
    """The 0-100 score plus its reasons as (label, points), largest first.
    Empty events -> (0, [])."""
    pastes = sum(1 for e in events if e.kind == "paste_external" and e.blocked)
    devtools = sum(1 for e in events if e.kind == "devtools")
    fs_exits = sum(1 for e in events if e.kind == "fullscreen_exit")
    focus = sum(1 for e in events if e.kind == "focus_loss")
    away_ms = sum(e.duration_ms or 0 for e in events if e.kind == "focus_loss")

    reasons: list[tuple[str, int]] = []
    if pastes:
        pts = min(pastes * _PASTE_BLOCKED_POINTS, _PASTE_BLOCKED_CAP)
        reasons.append((f"{pastes} outside paste{_s(pastes)} blocked", pts))
    if devtools:
        pts = min(devtools * _DEVTOOLS_POINTS, _DEVTOOLS_CAP)
        reasons.append((f"devtools opened {devtools} time{_s(devtools)}", pts))
    if fs_exits:
        pts = min(fs_exits * _FULLSCREEN_EXIT_POINTS, _FULLSCREEN_EXIT_CAP)
        reasons.append((f"left fullscreen {fs_exits} time{_s(fs_exits)}", pts))
    if focus:
        pts = min(focus * _FOCUS_LOSS_POINTS, _FOCUS_LOSS_CAP)
        reasons.append((f"{focus} focus loss{'es' if focus != 1 else ''}", pts))
    if away_ms >= _AWAY_LONG_MS:
        reasons.append((f"{away_ms // 60_000} min away from the tab", _AWAY_LONG_POINTS))
    elif away_ms >= _AWAY_SHORT_MS:
        reasons.append((f"{away_ms // 60_000} min away from the tab", _AWAY_SHORT_POINTS))

    reasons.sort(key=lambda r: r[1], reverse=True)
    return min(sum(p for _, p in reasons), _SCORE_MAX), reasons


def risk_level(score: int) -> RiskLevel:
    if score >= _LEVEL_HIGH:
        return "high"
    if score >= _LEVEL_ELEVATED:
        return "elevated"
    if score > 0:
        return "low"
    return "none"


def _s(n: int) -> str:
    return "" if n == 1 else "s"
