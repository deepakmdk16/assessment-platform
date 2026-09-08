"""plans, per-tenant usage metering and denormalised LLM cost (X02)

Revision ID: b8f2c4d16a07
Revises: a1c4e07b2d93
Create Date: 2026-09-08 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8f2c4d16a07'
down_revision: Union[str, Sequence[str], None] = 'a1c4e07b2d93'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Give every organisation a plan, a place to count what it uses, and a
    column to attribute LLM spend to.

    Existing organisations land on `free`/`active` through the server defaults —
    the correct starting point for accounts that predate billing, and the same
    state a new sign-up gets. The defaults stay on the columns afterwards so a
    row inserted by anything other than the ORM is still valid.

    `orgusage` rows are created lazily by the first metered event of a month, so
    there is nothing to backfill: an organisation with no row simply has no usage
    this period, which is what `billing.usage` returns for a missing row.
    """
    with op.batch_alter_table('organization', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('plan', sa.String(), nullable=False, server_default='free')
        )
        batch_op.add_column(
            sa.Column('plan_status', sa.String(), nullable=False, server_default='active')
        )
        batch_op.add_column(sa.Column('stripe_customer_id', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('stripe_subscription_id', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('current_period_end', sa.DateTime(), nullable=True))
    # A customer id maps to exactly one organisation: the webhook looks the
    # organisation up by it, so two rows sharing one would silently apply a
    # subscription to whichever came back first. NULL repeats freely (every
    # organisation that has never paid) — unique indexes ignore NULLs on both
    # SQLite and Postgres.
    op.create_index(
        op.f('ix_organization_stripe_customer_id'),
        'organization',
        ['stripe_customer_id'],
        unique=True,
    )
    op.create_index(
        op.f('ix_organization_stripe_subscription_id'),
        'organization',
        ['stripe_subscription_id'],
    )

    op.create_table(
        'orgusage',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('org_id', sa.Integer(), nullable=False),
        sa.Column('period', sa.String(), nullable=False),
        sa.Column('sittings', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('drafts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('judge_cost_usd', sa.Float(), nullable=False, server_default='0'),
        sa.Column('draft_cost_usd', sa.Float(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organization.id']),
        sa.PrimaryKeyConstraint('id'),
        # One row per organisation per month: what makes the conditional UPDATE
        # in `billing.consume` a lock-free claim on a single known row, and what
        # turns two workers racing to create the month into one insert and one
        # tolerated IntegrityError.
        sa.UniqueConstraint('org_id', 'period', name='uq_org_usage_period'),
    )
    op.create_index(op.f('ix_orgusage_org_id'), 'orgusage', ['org_id'])
    op.create_index(op.f('ix_orgusage_period'), 'orgusage', ['period'])

    with op.batch_alter_table('submission', schema=None) as batch_op:
        # Nullable: the agent prices nothing when the judge didn't run (a local
        # model, a job that errored), and every row that predates this column has
        # a cost that is genuinely unknown rather than zero.
        batch_op.add_column(sa.Column('judge_cost_usd', sa.Float(), nullable=True))


def downgrade() -> None:
    """Drops the plan and every counter. Cost figures already recorded on
    submissions go too — but the agent's original callback is kept verbatim in
    `assessmentresult.full_result`, so `judge_cost_usd` can be recovered from
    there if this is ever reversed and re-applied."""
    with op.batch_alter_table('submission', schema=None) as batch_op:
        batch_op.drop_column('judge_cost_usd')
    op.drop_index(op.f('ix_orgusage_period'), table_name='orgusage')
    op.drop_index(op.f('ix_orgusage_org_id'), table_name='orgusage')
    op.drop_table('orgusage')
    op.drop_index(op.f('ix_organization_stripe_subscription_id'), table_name='organization')
    op.drop_index(op.f('ix_organization_stripe_customer_id'), table_name='organization')
    with op.batch_alter_table('organization', schema=None) as batch_op:
        batch_op.drop_column('current_period_end')
        batch_op.drop_column('stripe_subscription_id')
        batch_op.drop_column('stripe_customer_id')
        batch_op.drop_column('plan_status')
        batch_op.drop_column('plan')
