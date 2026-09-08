"""carry a period's overage into the next one (X02)

Revision ID: c4a71e3b9d28
Revises: b8f2c4d16a07
Create Date: 2026-09-08 19:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4a71e3b9d28'
down_revision: Union[str, Sequence[str], None] = 'b8f2c4d16a07'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Two counters recording what the previous period overran by.

    Zero for every existing row, which is correct rather than merely convenient:
    nothing was carried before this existed, and the first period to be settled
    is the one after the migration runs.
    """
    with op.batch_alter_table('orgusage', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('sittings_carried', sa.Integer(), nullable=False, server_default='0')
        )
        batch_op.add_column(
            sa.Column('drafts_carried', sa.Integer(), nullable=False, server_default='0')
        )


def downgrade() -> None:
    """Drops the carried figures. Any debt still outstanding is forgiven, which
    is the safe direction — the alternative is deducting from an allowance with
    no record of why."""
    with op.batch_alter_table('orgusage', schema=None) as batch_op:
        batch_op.drop_column('drafts_carried')
        batch_op.drop_column('sittings_carried')
