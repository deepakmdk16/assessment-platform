"""question reference_solution and reference_language

Revision ID: 3c8072a71f16
Revises: 330f96008258
Create Date: 2026-07-22 17:57:01.004833

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '3c8072a71f16'
down_revision: Union[str, Sequence[str], None] = '330f96008258'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Persist the AI-drafted reference solution on the question.

    Both nullable: existing rows and hand-authored questions have no reference,
    and new inserts fill them from the model's Python-side default (None).
    batch_alter_table because SQLite adds columns via an Alembic table rebuild.
    """
    with op.batch_alter_table("question", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("reference_solution", sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("reference_language", sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("question", schema=None) as batch_op:
        batch_op.drop_column("reference_language")
        batch_op.drop_column("reference_solution")
