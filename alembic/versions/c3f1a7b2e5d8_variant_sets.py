"""variant sets (per-candidate unique variants)

Revision ID: c3f1a7b2e5d8
Revises: b7e2c1a4d9f0
Create Date: 2026-07-26 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'c3f1a7b2e5d8'
down_revision: Union[str, Sequence[str], None] = 'b7e2c1a4d9f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the `variantset` table and tag `question` rows that belong to one.

    A variant is an ordinary question with `variant_set_id` set; both new columns
    are nullable, so every existing standalone question is untouched (variant_set_id
    NULL = not part of a set)."""
    op.create_table(
        'variantset',
        sa.Column('id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('owner_id', sa.Integer(), nullable=False),
        sa.Column('title', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('brief', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('language', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('difficulty', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('target_complexity', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('status', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['owner_id'], ['interviewer.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_variantset_owner_id'), 'variantset', ['owner_id'], unique=False)
    op.create_index(op.f('ix_variantset_status'), 'variantset', ['status'], unique=False)

    with op.batch_alter_table('question', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('variant_set_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )
        batch_op.add_column(
            sa.Column('variant_label', sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )
        batch_op.create_index(
            batch_op.f('ix_question_variant_set_id'), ['variant_set_id'], unique=False
        )
        batch_op.create_foreign_key(
            'fk_question_variant_set_id', 'variantset', ['variant_set_id'], ['id']
        )


def downgrade() -> None:
    with op.batch_alter_table('question', schema=None) as batch_op:
        batch_op.drop_constraint('fk_question_variant_set_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_question_variant_set_id'))
        batch_op.drop_column('variant_label')
        batch_op.drop_column('variant_set_id')

    op.drop_index(op.f('ix_variantset_status'), table_name='variantset')
    op.drop_index(op.f('ix_variantset_owner_id'), table_name='variantset')
    op.drop_table('variantset')
