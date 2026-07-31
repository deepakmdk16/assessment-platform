"""freeze the sitting's monitoring setting onto the invite (I1)

Revision ID: b1e7f3a52c94
Revises: a9d1f4c07b53
Create Date: 2026-07-31 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b1e7f3a52c94'
down_revision: Union[str, Sequence[str], None] = 'a9d1f4c07b53'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """`Invite.proctored` snapshots `Assessment.proctored` at invite time, so a
    later toggle can't rewrite how an already-run sitting reads (hiding recorded
    evidence, or making an unmonitored sitting report as a clean one).

    Additive, defaulting true. Backfilled from each invite's assessment so
    existing invites carry their assessment's current setting rather than a blind
    true; an invite with no assessment (a quick screen) keeps the default, which
    is what that path always sends anyway.
    """
    with op.batch_alter_table('invite', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('proctored', sa.Boolean(), nullable=False, server_default=sa.true())
        )
    op.execute(
        """
        UPDATE invite
           SET proctored = (
                 SELECT assessment.proctored
                   FROM assessment
                  WHERE assessment.id = invite.assessment_id
               )
         WHERE assessment_id IS NOT NULL
        """
    )


def downgrade() -> None:
    with op.batch_alter_table('invite', schema=None) as batch_op:
        batch_op.drop_column('proctored')
