"""interviewer default_org_name and default_logo_url (A12 workspace branding)

Revision ID: b7e2c1a4d9f0
Revises: 4185e1964c38
Create Date: 2026-07-26 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'b7e2c1a4d9f0'
down_revision: Union[str, Sequence[str], None] = '4185e1964c38'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Workspace default branding (A12): optional default_org_name +
    default_logo_url on the interviewer, used to pre-fill a new assessment's
    branding. Both nullable — additive, existing interviewers keep no default."""
    with op.batch_alter_table('interviewer', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('default_org_name', sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )
        batch_op.add_column(
            sa.Column('default_logo_url', sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('interviewer', schema=None) as batch_op:
        batch_op.drop_column('default_logo_url')
        batch_op.drop_column('default_org_name')
