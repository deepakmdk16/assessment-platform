"""invite deliveries audit trail

Revision ID: 330f96008258
Revises: 40b262e3d6b5
Create Date: 2026-07-19 00:15:30.214523

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '330f96008258'
down_revision: Union[str, Sequence[str], None] = '40b262e3d6b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Persist per-recipient invite delivery outcomes on the invite.

    nullable=True to match the model (a JSON field with a default_factory maps to a
    nullable column), with a server_default of '[]' so existing invites still
    backfill to an empty trail rather than NULL. New rows get the model's
    default_factory=list.
    """
    with op.batch_alter_table("invite", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "deliveries", sa.JSON(), nullable=True, server_default=sa.text("'[]'")
            )
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("invite", schema=None) as batch_op:
        batch_op.drop_column("deliveries")
