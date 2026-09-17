"""invite.duration_minutes (freeze the sitting's length when the invite is minted)

Revision ID: b3f1d64c2a07
Revises: a4f2c7b81e60
Create Date: 2026-09-17 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3f1d64c2a07'
down_revision: Union[str, Sequence[str], None] = 'a4f2c7b81e60'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """R2-031: the deadline is computed from a duration frozen on the invite, not
    from whatever the assessment says at the moment it is read.

    Existing invites are backfilled from the assessment (or, for a quick screen,
    the question) they point at, because NULL has to mean exactly one thing —
    *untimed* — and nothing else. Read as "no snapshot recorded" it would keep the
    live fallback alive for the one sitting that has no deadline of its own: an
    interviewer turning a limit on mid-flight would hand a candidate promised no
    limit a deadline, and then record their submit `late`. The value written is
    the one in force now, which is what those links were already being read
    against a moment ago.
    """
    with op.batch_alter_table('invite', schema=None) as batch_op:
        batch_op.add_column(sa.Column('duration_minutes', sa.Integer(), nullable=True))

    op.execute(
        """
        UPDATE invite
           SET duration_minutes = (
               SELECT a.duration_minutes FROM assessment a WHERE a.id = invite.assessment_id
           )
         WHERE assessment_id IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE invite
           SET duration_minutes = (
               SELECT q.duration_minutes FROM question q WHERE q.id = invite.question_id
           )
         WHERE assessment_id IS NULL AND question_id IS NOT NULL
        """
    )


def downgrade() -> None:
    with op.batch_alter_table('invite', schema=None) as batch_op:
        batch_op.drop_column('duration_minutes')
