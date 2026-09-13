"""The address a candidate is told to write to (P2b).

The product never shows a candidate an interviewer's personal address. The
invitation email already carries it as `Reply-To`, which is the interviewer's own
header to give; a link that gets forwarded must not also become a directory of
who is hiring. What the screens show instead is the platform's own mailbox,
`config.SUPPORT_EMAIL`, optionally plus-tagged with the inviting organisation's
tag — `support@x` becomes `support+acme-corp-12@x` — so one real mailbox can
still be filtered or routed per customer without any DNS work.

Two tiers, matching what the caller has proved about themselves:

* `generic_contact_email()` — the untagged address, for the pre-start probe.
  An assessment invite's probe already names the organisation (the gate is
  branded, A12/P2a), but a quick-screen invite's does not — and the probe must
  not become the one place that does, for a link anyone may be holding.
* `invite_contact_email()` — the tagged address, for a candidate who has
  identified as an invited recipient (`/start`) and for the invitation email
  itself, which already names the organisation in its subject line.

The tag is display and routing only: nothing authenticates on it, and it carries
the organisation's id so a rename cannot move it onto somebody else's.
"""

from __future__ import annotations

import re

from sqlmodel import Session

from assessment_platform import config
from assessment_platform.models import Assessment, Invite, Organization, Question

# Anything that isn't an unaccented letter or digit becomes a separator, which is
# also what keeps the tag inside the character set an address local-part allows.
_NOT_SLUG = re.compile(r"[^a-z0-9]+")
_MAX_SLUG = 32


def org_slug(org: Organization) -> str | None:
    """A short routing tag for an organisation, or None if it has none.

    `<name>-<id>`, e.g. `acme-corp-12`. Derived rather than stored, so it costs no
    column and no migration — but the id is not decoration: `Organization.name` is
    not unique and any admin can change it, so a name-only tag would let one
    customer rename themselves onto another's tag and have mail routed on it. The
    name half is there to make a mail filter readable; the id half is what makes
    it theirs. A name with nothing ASCII left in it is just the id.
    """
    if org.id is None:
        return None
    slug = _NOT_SLUG.sub("-", org.name.lower()).strip("-")[:_MAX_SLUG].strip("-")
    return f"{slug}-{org.id}" if slug else f"org{org.id}"


def generic_contact_email() -> str | None:
    """The untagged support address; None when the deploy configures none."""
    return contact_email(None)


def contact_email(org: Organization | None) -> str | None:
    """The support address to show for `org`, tagged when that is possible.

    Falls back to the untagged address whenever tagging would be wrong or
    impossible: the feature is off, the organisation is unknown, the configured
    address already carries a `+` tag of the operator's own, or it isn't shaped
    like an address at all.
    """
    base = config.SUPPORT_EMAIL
    if not base:
        return None
    if not config.SUPPORT_EMAIL_ORG_TAG or org is None:
        return base
    local, sep, domain = base.partition("@")
    if not sep or not local or "+" in local:
        return base
    slug = org_slug(org)
    return f"{local}+{slug}@{domain}" if slug else base


def invite_org(invite: Invite, session: Session) -> Organization | None:
    """The organisation behind an invite, via the assessment or question it points
    at — never via `created_by`, which records only who clicked send (the same
    rule as `privacy.org_invite_ids`).

    The one resolution of this in the codebase: `api._invite_org_id` wraps it with
    the 500 a corrupt row deserves, and the candidate routes read it through that.
    """
    org_id = None
    if invite.assessment_id is not None:
        assessment = session.get(Assessment, invite.assessment_id)
        org_id = assessment.org_id if assessment else None
    if org_id is None and invite.question_id is not None:
        question = session.get(Question, invite.question_id)
        org_id = question.org_id if question else None
    return session.get(Organization, org_id) if org_id is not None else None


def invite_contact_email(invite: Invite, session: Session) -> str | None:
    """The tagged support address for one invite. Skips the org lookup entirely
    when no address is configured, so the common unconfigured deploy pays nothing
    for this on the candidate's hot path."""
    if not config.SUPPORT_EMAIL:
        return None
    return contact_email(invite_org(invite, session))
