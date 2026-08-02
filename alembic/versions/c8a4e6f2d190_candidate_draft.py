"""candidatedraft — server-side autosave of in-progress candidate code (CX2)

Revision ID: c8a4e6f2d190
Revises: b1e7f3a52c94
Create Date: 2026-07-31 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c8a4e6f2d190'
down_revision: Union[str, Sequence[str], None] = 'b1e7f3a52c94'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Additive: a new table, nothing existing changes. One draft per
    (invite, candidate, question), upserted while the candidate types."""
    op.create_table(
        'candidatedraft',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('invite_id', sa.Integer(), nullable=False),
        sa.Column('candidate_email', sa.String(), nullable=False),
        sa.Column('question_id', sa.String(), nullable=False),
        sa.Column('code', sa.String(), nullable=False),
        sa.Column('language', sa.String(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['invite_id'], ['invite.id']),
        sa.ForeignKeyConstraint(['question_id'], ['question.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'invite_id', 'candidate_email', 'question_id',
            name='uq_draft_invite_candidate_question',
        ),
    )
    op.create_index(
        op.f('ix_candidatedraft_invite_id'), 'candidatedraft', ['invite_id'], unique=False
    )
    op.create_index(
        op.f('ix_candidatedraft_candidate_email'),
        'candidatedraft',
        ['candidate_email'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_candidatedraft_candidate_email'), table_name='candidatedraft')
    op.drop_index(op.f('ix_candidatedraft_invite_id'), table_name='candidatedraft')
    op.drop_table('candidatedraft')
