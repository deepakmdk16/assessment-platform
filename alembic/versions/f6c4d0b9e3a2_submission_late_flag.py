"""submission.late flag (record past-deadline submits instead of discarding)

Revision ID: f6c4d0b9e3a2
Revises: e5b3c9d7a2f1
Create Date: 2026-07-26 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f6c4d0b9e3a2'
down_revision: Union[str, Sequence[str], None] = 'e5b3c9d7a2f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """A submit past the timed window is now recorded (flagged) instead of being
    rejected with a 410. `late` is additive and defaults False, so every existing
    submission is treated as on-time."""
    with op.batch_alter_table('submission', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('late', sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    with op.batch_alter_table('submission', schema=None) as batch_op:
        batch_op.drop_column('late')
