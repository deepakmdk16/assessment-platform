"""candidate privacy: retention window, recorded consent, erasure stamp (X03/X04)

Revision ID: a8f2c30d91b4
Revises: d5b82f4c1e63
Create Date: 2026-09-08 21:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a8f2c30d91b4'
down_revision: Union[str, Sequence[str], None] = 'd5b82f4c1e63'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """One retention window per organisation, and two facts per sitting.

    All four columns are nullable with no server default, and that is the whole
    design rather than an omission:

    - `organization.retention_days` NULL means "no policy configured". A default
      window would silently start deleting existing customers' hiring records on
      the first deploy after this migration — the one outcome a privacy feature
      must not produce.
    - `candidateattempt.consent_at` / `consent_version` NULL is the truthful
      record for every sitting that happened before consent was ever asked for.
      Backfilling a timestamp would manufacture evidence of an agreement that
      was never given, which is worse than having none.
    - `candidateattempt.erased_at` NULL means "still holds personal data", which
      is correct for every pre-existing row and is what the retention job reads
      to know it has work to do.
    """
    with op.batch_alter_table('organization', schema=None) as batch_op:
        batch_op.add_column(sa.Column('retention_days', sa.Integer(), nullable=True))
    with op.batch_alter_table('candidateattempt', schema=None) as batch_op:
        batch_op.add_column(sa.Column('consent_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('consent_version', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('erased_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('candidateattempt', schema=None) as batch_op:
        batch_op.drop_column('erased_at')
        batch_op.drop_column('consent_version')
        batch_op.drop_column('consent_at')
    with op.batch_alter_table('organization', schema=None) as batch_op:
        batch_op.drop_column('retention_days')
