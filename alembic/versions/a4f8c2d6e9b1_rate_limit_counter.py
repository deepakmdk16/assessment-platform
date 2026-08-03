"""rate_limit_counter — shared-store rate limiting (SEC4, RATE_LIMIT_BACKEND=db)

Revision ID: a4f8c2d6e9b1
Revises: c8a4e6f2d190
Create Date: 2026-08-03 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a4f8c2d6e9b1'
down_revision: Union[str, Sequence[str], None] = 'c8a4e6f2d190'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Fixed-window rate-limit counters shared across workers via the database.

    Additive: nothing reads the table unless RATE_LIMIT_BACKEND=db is set, so
    existing deploys are unaffected. The composite PK is the counter's identity
    (one row per bucket + client + window); the window_start index is what the
    lazy purge of dead windows scans by.
    """
    op.create_table(
        'ratelimitcounter',
        sa.Column('bucket', sa.String(), nullable=False),
        sa.Column('client', sa.String(), nullable=False),
        sa.Column('window_start', sa.Integer(), nullable=False),
        sa.Column('count', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('bucket', 'client', 'window_start'),
    )
    op.create_index(
        op.f('ix_ratelimitcounter_window_start'),
        'ratelimitcounter',
        ['window_start'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_ratelimitcounter_window_start'), table_name='ratelimitcounter')
    op.drop_table('ratelimitcounter')
