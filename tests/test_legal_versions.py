"""The consent stamp (`config.PRIVACY_POLICY_VERSION`) must be the version the
candidate is shown: the web renders each legal document's `version:` front
matter, and the two are bumped by hand. Without this, a bump can land in the
config and one document but not the other, and the record of what a candidate
agreed to points at words they never saw."""

from __future__ import annotations

import re
from pathlib import Path

from assessment_platform import config

DOCS = Path(__file__).resolve().parents[1] / "docs"


def _front_matter_version(name: str) -> str:
    text = (DOCS / name).read_text(encoding="utf-8")
    match = re.search(r"^version:\s*(\S+)\s*$", text, re.MULTILINE)
    assert match, f"{name} has no version in its front matter"
    return match.group(1)


def test_the_legal_documents_carry_the_consent_version() -> None:
    for name in ("PRIVACY.md", "TERMS.md"):
        assert _front_matter_version(name) == config.PRIVACY_POLICY_VERSION, name
