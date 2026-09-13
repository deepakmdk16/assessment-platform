"""organisation logo as a stored asset, replacing the logo URLs (P3b)

Revision ID: c5e81a7d34b6
Revises: a9c3f5e17b24
Create Date: 2026-09-13 22:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'c5e81a7d34b6'
down_revision: Union[str, Sequence[str], None] = 'a9c3f5e17b24'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Branding stops being a URL on a person and becomes an asset on the org.

    `org_asset` holds the bytes (bytea on Postgres, BLOB on SQLite) addressed by
    sha256; `organization.logo_sha` names the current one and `assessment.logo_sha`
    snapshots it at creation, so replacing a logo leaves work already sent alone.

    The three URL columns are dropped rather than migrated. Pre-launch, there is
    nothing worth carrying: the old values are arbitrary external URLs, and the
    point of the change is that we no longer load images from them. Anyone with a
    logo set re-uploads it — which is also the only way to get bytes we have
    actually decoded ourselves.
    """
    op.create_table(
        'orgasset',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('org_id', sa.Integer(), nullable=False),
        sa.Column('kind', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('content_type', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('sha256', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('data', sa.LargeBinary(), nullable=False),
        sa.Column('width', sa.Integer(), nullable=False),
        sa.Column('height', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organization.id'], ),
        sa.PrimaryKeyConstraint('id'),
        # One row per (organisation, content): re-uploading the same file is the
        # same asset. Not unique on sha256 alone — two tenants uploading the same
        # image must not share a row, or deleting one would take the other's logo.
        sa.UniqueConstraint('org_id', 'sha256', name='uq_orgasset_org_sha'),
    )
    with op.batch_alter_table('orgasset', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_orgasset_org_id'), ['org_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_orgasset_sha256'), ['sha256'], unique=False)

    with op.batch_alter_table('organization', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('logo_sha', sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )
        batch_op.create_index(batch_op.f('ix_organization_logo_sha'), ['logo_sha'], unique=False)

    with op.batch_alter_table('assessment', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('logo_sha', sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )
        batch_op.create_index(batch_op.f('ix_assessment_logo_sha'), ['logo_sha'], unique=False)
        batch_op.drop_column('logo_url')

    with op.batch_alter_table('interviewer', schema=None) as batch_op:
        batch_op.drop_column('default_logo_url')
        # An assessment's org_name now defaults from organization.name, which the
        # X01 migration already seeded from this very column.
        batch_op.drop_column('default_org_name')


def downgrade() -> None:
    with op.batch_alter_table('interviewer', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('default_org_name', sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )
        batch_op.add_column(
            sa.Column('default_logo_url', sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )

    with op.batch_alter_table('assessment', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('logo_url', sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )
        batch_op.drop_index(batch_op.f('ix_assessment_logo_sha'))
        batch_op.drop_column('logo_sha')

    with op.batch_alter_table('organization', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_organization_logo_sha'))
        batch_op.drop_column('logo_sha')

    with op.batch_alter_table('orgasset', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_orgasset_sha256'))
        batch_op.drop_index(batch_op.f('ix_orgasset_org_id'))

    op.drop_table('orgasset')
