"""unique submission per invite and candidate

Revision ID: 4134ffc10adb
Revises: cae37faa2bff
Create Date: 2026-07-17 16:07:01.864316

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '4134ffc10adb'
down_revision: Union[str, Sequence[str], None] = 'cae37faa2bff'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Enforce one attempt per candidate per invite in the DATABASE.

    The route checked with a SELECT before its INSERT, which two concurrent
    submits both pass, so the rule was advisory. NULLs compare as distinct, so
    the interviewer's direct POST /submissions path (no invite_id/candidate_email)
    is unaffected.

    batch_alter_table because SQLite cannot ALTER a table to add a constraint —
    Alembic rebuilds it instead. If an existing database already contains
    duplicate (invite_id, candidate_email) rows from the race this fixes, this
    migration will FAIL rather than pick a winner: which duplicate to keep is a
    data decision for a human, not for a schema migration.
    """
    with op.batch_alter_table("submission", schema=None) as batch_op:
        batch_op.create_unique_constraint(
            "uq_submission_invite_candidate", ["invite_id", "candidate_email"]
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("submission", schema=None) as batch_op:
        batch_op.drop_constraint("uq_submission_invite_candidate", type_="unique")
