"""submission.attempts + index on submission.status (grading durability)

Revision ID: d7c3e9a1b5f2
Revises: a4f8c2d6e9b1
Create Date: 2026-09-07 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd7c3e9a1b5f2'
down_revision: Union[str, Sequence[str], None] = 'a4f8c2d6e9b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """The background grading reaper re-triggers stranded submissions and gives up
    after MAX_TRIGGER_ATTEMPTS; `attempts` is that counter (additive, defaults 0 so
    every existing row is treated as never re-triggered). The status index is what
    the reaper's scan of pending/running rows uses."""
    with op.batch_alter_table('submission', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('attempts', sa.Integer(), nullable=False, server_default='0')
        )
        batch_op.create_index(batch_op.f('ix_submission_status'), ['status'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('submission', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_submission_status'))
        batch_op.drop_column('attempts')
