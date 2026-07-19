"""question difficulty and status

Revision ID: 40b262e3d6b5
Revises: 4134ffc10adb
Create Date: 2026-07-19 00:09:41.574254

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '40b262e3d6b5'
down_revision: Union[str, Sequence[str], None] = '4134ffc10adb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add interviewer-facing difficulty + status to question.

    status is NOT NULL with a server_default of 'active' so existing rows backfill
    to active; new inserts use the model's Python-side default. batch_alter_table
    because SQLite cannot ALTER-ADD a NOT NULL column in place — Alembic rebuilds.
    """
    with op.batch_alter_table("question", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("difficulty", sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "status",
                sqlmodel.sql.sqltypes.AutoString(),
                nullable=False,
                server_default="active",
            )
        )
        batch_op.create_index(batch_op.f("ix_question_status"), ["status"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("question", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_question_status"))
        batch_op.drop_column("status")
        batch_op.drop_column("difficulty")
