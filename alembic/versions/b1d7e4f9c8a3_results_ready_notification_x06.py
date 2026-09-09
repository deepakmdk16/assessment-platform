"""results-ready notification: per-org webhook, per-sitting notified stamp (X06)

Revision ID: b1d7e4f9c8a3
Revises: a8f2c30d91b4
Create Date: 2026-09-09 10:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b1d7e4f9c8a3'
down_revision: Union[str, Sequence[str], None] = 'a8f2c30d91b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """One optional webhook per organisation, and one notified stamp per sitting.

    All three columns are nullable with no server default:

    - `organization.results_webhook_url` / `results_webhook_secret` NULL means
      "email only", which is what every existing organisation has agreed to.
      A server default here would enrol tenants into an outbound HTTP call they
      never configured.
    - `candidateattempt.results_notified_at` NULL means "nobody has been told".
      Backfilling `now()` would be a lie about a message that was never sent,
      and backfilling nothing is also what keeps this migration from mailing
      every historical sitting the first time a callback re-delivers: the stamp
      is only ever set by a notification that actually goes out.
    """
    with op.batch_alter_table('organization', schema=None) as batch_op:
        batch_op.add_column(sa.Column('results_webhook_url', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('results_webhook_secret', sa.String(), nullable=True))
    with op.batch_alter_table('candidateattempt', schema=None) as batch_op:
        batch_op.add_column(sa.Column('results_notified_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('candidateattempt', schema=None) as batch_op:
        batch_op.drop_column('results_notified_at')
    with op.batch_alter_table('organization', schema=None) as batch_op:
        batch_op.drop_column('results_webhook_secret')
        batch_op.drop_column('results_webhook_url')
