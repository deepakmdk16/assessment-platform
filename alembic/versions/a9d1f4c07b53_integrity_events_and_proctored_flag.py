"""integrity events (I1 browser telemetry) + assessment.proctored toggle

Revision ID: a9d1f4c07b53
Revises: f6c4d0b9e3a2
Create Date: 2026-07-27 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a9d1f4c07b53'
down_revision: Union[str, Sequence[str], None] = 'f6c4d0b9e3a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Additive: a new table for candidate-reported integrity signals, plus the
    per-assessment monitoring toggle. `proctored` defaults true, so existing
    assessments are monitored from the next sitting onward; no existing row's
    meaning changes and nothing is backfilled (there are no historical signals)."""
    op.create_table(
        'integrityevent',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('invite_id', sa.Integer(), nullable=False),
        sa.Column('candidate_email', sa.String(), nullable=False),
        sa.Column('question_id', sa.String(), nullable=True),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('offset_ms', sa.Integer(), nullable=False),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('size', sa.Integer(), nullable=True),
        sa.Column('blocked', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['invite_id'], ['invite.id']),
        sa.ForeignKeyConstraint(['question_id'], ['question.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_integrityevent_invite_id'), 'integrityevent', ['invite_id'], unique=False
    )
    op.create_index(
        op.f('ix_integrityevent_candidate_email'),
        'integrityevent',
        ['candidate_email'],
        unique=False,
    )
    op.create_index(
        op.f('ix_integrityevent_question_id'), 'integrityevent', ['question_id'], unique=False
    )
    op.create_index(op.f('ix_integrityevent_kind'), 'integrityevent', ['kind'], unique=False)

    with op.batch_alter_table('assessment', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('proctored', sa.Boolean(), nullable=False, server_default=sa.true())
        )


def downgrade() -> None:
    with op.batch_alter_table('assessment', schema=None) as batch_op:
        batch_op.drop_column('proctored')
    op.drop_index(op.f('ix_integrityevent_kind'), table_name='integrityevent')
    op.drop_index(op.f('ix_integrityevent_question_id'), table_name='integrityevent')
    op.drop_index(op.f('ix_integrityevent_candidate_email'), table_name='integrityevent')
    op.drop_index(op.f('ix_integrityevent_invite_id'), table_name='integrityevent')
    op.drop_table('integrityevent')
