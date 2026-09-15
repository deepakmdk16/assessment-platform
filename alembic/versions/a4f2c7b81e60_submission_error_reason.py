"""submission.error_reason (why an ungraded submission ended in "error")

Revision ID: a4f2c7b81e60
Revises: c5e81a7d34b6
Create Date: 2026-09-15 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a4f2c7b81e60'
down_revision: Union[str, Sequence[str], None] = 'c5e81a7d34b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """A submission that ends in "error" without a grade now carries the reason —
    the grader refused the job, or never answered. Nullable and additive: every
    existing row keeps NULL, which reads as the unexplained error it was."""
    with op.batch_alter_table('submission', schema=None) as batch_op:
        batch_op.add_column(sa.Column('error_reason', sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('submission', schema=None) as batch_op:
        batch_op.drop_column('error_reason')
