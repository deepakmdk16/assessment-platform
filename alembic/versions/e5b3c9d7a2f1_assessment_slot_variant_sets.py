"""assessment slot variant sets (VS2)

Revision ID: e5b3c9d7a2f1
Revises: d4a2b8c6f1e0
Create Date: 2026-07-26 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'e5b3c9d7a2f1'
down_revision: Union[str, Sequence[str], None] = 'd4a2b8c6f1e0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """A VS2 assessment slot can be a variant-set pool instead of a fixed question.

    Additive: `assessmentquestion.variant_set_id` is new + nullable and
    `question_id` becomes nullable (a set-slot has no fixed question), so every
    existing slot — all of which carry a `question_id` — is untouched. The new
    `candidateslotvariant` table records which variant each candidate was handed
    for a set-slot (frozen per candidate); empty for existing data."""
    with op.batch_alter_table('assessmentquestion', schema=None) as batch_op:
        batch_op.alter_column('question_id', existing_type=sa.String(), nullable=True)
        batch_op.add_column(
            sa.Column('variant_set_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )
        batch_op.create_index(
            batch_op.f('ix_assessmentquestion_variant_set_id'),
            ['variant_set_id'],
            unique=False,
        )
        batch_op.create_foreign_key(
            'fk_assessmentquestion_variant_set_id', 'variantset', ['variant_set_id'], ['id']
        )

    op.create_table(
        'candidateslotvariant',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('invite_id', sa.Integer(), nullable=False),
        sa.Column('candidate_email', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('assessment_question_id', sa.Integer(), nullable=False),
        sa.Column('question_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['invite_id'], ['invite.id']),
        sa.ForeignKeyConstraint(['assessment_question_id'], ['assessmentquestion.id']),
        sa.ForeignKeyConstraint(['question_id'], ['question.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'invite_id',
            'candidate_email',
            'assessment_question_id',
            name='uq_candidate_slot_variant',
        ),
    )
    op.create_index(
        op.f('ix_candidateslotvariant_invite_id'),
        'candidateslotvariant',
        ['invite_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_candidateslotvariant_candidate_email'),
        'candidateslotvariant',
        ['candidate_email'],
        unique=False,
    )
    op.create_index(
        op.f('ix_candidateslotvariant_assessment_question_id'),
        'candidateslotvariant',
        ['assessment_question_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_candidateslotvariant_question_id'),
        'candidateslotvariant',
        ['question_id'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f('ix_candidateslotvariant_question_id'), table_name='candidateslotvariant'
    )
    op.drop_index(
        op.f('ix_candidateslotvariant_assessment_question_id'),
        table_name='candidateslotvariant',
    )
    op.drop_index(
        op.f('ix_candidateslotvariant_candidate_email'), table_name='candidateslotvariant'
    )
    op.drop_index(
        op.f('ix_candidateslotvariant_invite_id'), table_name='candidateslotvariant'
    )
    op.drop_table('candidateslotvariant')

    with op.batch_alter_table('assessmentquestion', schema=None) as batch_op:
        batch_op.drop_constraint('fk_assessmentquestion_variant_set_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_assessmentquestion_variant_set_id'))
        batch_op.drop_column('variant_set_id')
        batch_op.alter_column('question_id', existing_type=sa.String(), nullable=False)
