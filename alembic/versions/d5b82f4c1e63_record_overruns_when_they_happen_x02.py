"""record an overrun when it happens, not by reconstructing it later (X02)

Revision ID: d5b82f4c1e63
Revises: c4a71e3b9d28
Create Date: 2026-09-08 20:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd5b82f4c1e63'
down_revision: Union[str, Sequence[str], None] = 'c4a71e3b9d28'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Two counters holding what a period went past its allowance by.

    The carried figures added in the previous revision were reconstructed at the
    period boundary by comparing last month's usage against the plan in force
    *now* — which turns a downgrade into a debt for usage that was entitled when
    it happened (400 of a Growth plan's 500, then a move to Starter, read as 300
    over). The overrun is recorded as it occurs instead, against the allowance
    that actually applied.

    Zero everywhere, which is right: nothing recorded an overrun before this
    existed, and inventing one now would be the same mistake in reverse.
    """
    with op.batch_alter_table('orgusage', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('sittings_over', sa.Integer(), nullable=False, server_default='0')
        )
        batch_op.add_column(
            sa.Column('drafts_over', sa.Integer(), nullable=False, server_default='0')
        )


def downgrade() -> None:
    with op.batch_alter_table('orgusage', schema=None) as batch_op:
        batch_op.drop_column('drafts_over')
        batch_op.drop_column('sittings_over')
