"""invite.variant_set_id (per-candidate variant assignment)

Revision ID: d4a2b8c6f1e0
Revises: c3f1a7b2e5d8
Create Date: 2026-07-26 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'd4a2b8c6f1e0'
down_revision: Union[str, Sequence[str], None] = 'c3f1a7b2e5d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Record which variant set an invite drew its assigned variant from. Additive
    and nullable — every existing invite keeps variant_set_id NULL (an ordinary
    question/assessment invite); question_id still holds the actual question."""
    with op.batch_alter_table('invite', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('variant_set_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )
        batch_op.create_index(
            batch_op.f('ix_invite_variant_set_id'), ['variant_set_id'], unique=False
        )
        batch_op.create_foreign_key(
            'fk_invite_variant_set_id', 'variantset', ['variant_set_id'], ['id']
        )


def downgrade() -> None:
    with op.batch_alter_table('invite', schema=None) as batch_op:
        batch_op.drop_constraint('fk_invite_variant_set_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_invite_variant_set_id'))
        batch_op.drop_column('variant_set_id')
