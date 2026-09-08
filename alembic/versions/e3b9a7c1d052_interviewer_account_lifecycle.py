"""interviewer.token_version + email_verified_at; lower-case email backfill (P13)

Revision ID: e3b9a7c1d052
Revises: d7c3e9a1b5f2
Create Date: 2026-09-07 15:00:00.000000

"""
import logging
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e3b9a7c1d052'
down_revision: Union[str, Sequence[str], None] = 'd7c3e9a1b5f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")


def upgrade() -> None:
    """`token_version` is the JWT revocation counter (0 = nothing revoked yet, so
    every existing row keeps its sessions); `email_verified_at` is null for every
    existing account (they registered before verification existed).

    Emails are normalised to lower-case from now on at register and login, so
    accounts stored with capitals would otherwise become unreachable: lower-case
    them here. A pair that differs only in case can't both be lowered (the unique
    index), so those are left as they are and logged by id for a manual merge —
    the account whose exact spelling matches no longer logs in until then.
    """
    with op.batch_alter_table('interviewer', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('token_version', sa.Integer(), nullable=False, server_default='0')
        )
        batch_op.add_column(sa.Column('email_verified_at', sa.DateTime(), nullable=True))

    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, email FROM interviewer")).fetchall()
    by_lower: dict[str, list[int]] = {}
    for row_id, email in rows:
        by_lower.setdefault(email.lower(), []).append(row_id)
    for lowered, ids in by_lower.items():
        if len(ids) > 1:
            logger.warning(
                "interviewer emails differ only in case; not normalised — merge them "
                "by hand (ids %s).",
                ids,
            )
            continue
        conn.execute(
            sa.text("UPDATE interviewer SET email = :email WHERE id = :id AND email != :email"),
            {"email": lowered, "id": ids[0]},
        )


def downgrade() -> None:
    # The lower-casing is not reversible (the original casing is gone); only the
    # columns come back out.
    with op.batch_alter_table('interviewer', schema=None) as batch_op:
        batch_op.drop_column('email_verified_at')
        batch_op.drop_column('token_version')
