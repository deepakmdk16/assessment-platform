"""candidate feedback on a finished sitting (P2b)

Revision ID: a9c3f5e17b24
Revises: b1d7e4f9c8a3
Create Date: 2026-09-13 14:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'a9c3f5e17b24'
down_revision: Union[str, Sequence[str], None] = 'b1d7e4f9c8a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """One optional row per finished sitting: rating, difficulty, comment.

    Unique on `attempt_id` — a sitting gets one answer, and the route returns 409
    rather than letting a re-send overwrite one an interviewer may already have
    read. `org_id` is denormalised off the invite so account deletion reaches
    these rows by organisation like every other table.
    """
    op.create_table('candidatefeedback',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('org_id', sa.Integer(), nullable=False),
    sa.Column('attempt_id', sa.Integer(), nullable=False),
    sa.Column('rating', sa.Integer(), nullable=False),
    sa.Column('difficulty_fair', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('comment', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['attempt_id'], ['candidateattempt.id'], ),
    sa.ForeignKeyConstraint(['org_id'], ['organization.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('attempt_id')
    )
    with op.batch_alter_table('candidatefeedback', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_candidatefeedback_org_id'), ['org_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('candidatefeedback', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_candidatefeedback_org_id'))

    op.drop_table('candidatefeedback')
