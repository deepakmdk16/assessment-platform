"""organizations, membership and org invites; org_id on owned resources (X01)

Revision ID: a1c4e07b2d93
Revises: e3b9a7c1d052
Create Date: 2026-09-08 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1c4e07b2d93'
down_revision: Union[str, Sequence[str], None] = 'e3b9a7c1d052'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# The tables whose ownership moves from an interviewer to an organisation.
OWNED = ('question', 'variantset', 'assessment')

# Seed each organisation from the workspace branding the interviewer already set
# (A12 `default_org_name`) — the closest thing to a company name the platform
# holds — rather than putting everyone on a generated placeholder.
_ORG_NAME = (
    "CASE "
    "WHEN default_org_name IS NOT NULL AND TRIM(default_org_name) <> '' "
    "THEN TRIM(default_org_name) "
    "WHEN name IS NOT NULL AND TRIM(name) <> '' "
    "THEN TRIM(name) || '''s organisation' "
    "ELSE 'My organisation' END"
)


def upgrade() -> None:
    """Give every existing account its own single-member organisation and move
    resource ownership onto it.

    The backfill is what makes this safe to run on live data: one organisation
    per interviewer, that interviewer as its admin, and every question / variant
    set / assessment they owned re-pointed at it. Nothing changes hands and
    nobody gains sight of anyone else's data — the shape changes, the isolation
    does not. Only an explicit org invite (a route added with this migration)
    ever puts a second person in an organisation.

    Each backfilled organisation deliberately takes `id = interviewer.id`. It
    makes the whole backfill three set-based statements with no id round-trip
    and no reliance on RETURNING, and it is unambiguous because this runs
    exactly once, on a table that is empty before it. The alignment is an
    artifact of the migration and means nothing afterwards — organisations
    created by a later sign-up get their own sequence values.

    `org_id` is added nullable, backfilled, and only then made NOT NULL: a NOT
    NULL column can't be added to a table that already has rows.
    """
    op.create_table(
        'organization',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'membership',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('org_id', sa.Integer(), nullable=False),
        sa.Column('interviewer_id', sa.Integer(), nullable=False),
        sa.Column('role', sa.String(), nullable=False),
        sa.Column('invited_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organization.id']),
        sa.ForeignKeyConstraint(['interviewer_id'], ['interviewer.id']),
        sa.ForeignKeyConstraint(['invited_by'], ['interviewer.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('interviewer_id', name='uq_membership_interviewer'),
    )
    op.create_index(op.f('ix_membership_org_id'), 'membership', ['org_id'])
    op.create_index(op.f('ix_membership_interviewer_id'), 'membership', ['interviewer_id'])
    op.create_table(
        'orginvite',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('org_id', sa.Integer(), nullable=False),
        sa.Column('token', sa.String(), nullable=False),
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('role', sa.String(), nullable=False),
        # Nullable like every other authorship column here: the admin who sent
        # the invitation can delete their account while the organisation lives on
        # (see `_disown`), and this row is kept as the audit trail.
        sa.Column('invited_by', sa.Integer(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('accepted_at', sa.DateTime(), nullable=True),
        sa.Column('sent', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('send_error', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organization.id']),
        sa.ForeignKeyConstraint(['invited_by'], ['interviewer.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_orginvite_org_id'), 'orginvite', ['org_id'])
    op.create_index(op.f('ix_orginvite_email'), 'orginvite', ['email'])
    op.create_index(op.f('ix_orginvite_token'), 'orginvite', ['token'], unique=True)
    op.create_index(op.f('ix_orginvite_invited_by'), 'orginvite', ['invited_by'])

    conn = op.get_bind()
    conn.execute(
        sa.text(
            'INSERT INTO organization (id, name, created_at, updated_at) '
            f'SELECT id, {_ORG_NAME}, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP '  # noqa: S608
            'FROM interviewer'
        )
    )
    conn.execute(
        sa.text(
            'INSERT INTO membership '
            '(org_id, interviewer_id, role, invited_by, created_at, updated_at) '
            "SELECT id, id, 'admin', NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP "
            'FROM interviewer'
        )
    )
    if conn.dialect.name == 'postgresql':
        # Explicit ids leave an IDENTITY sequence behind, so the next sign-up
        # would collide with a backfilled organisation. (No-op on SQLite, whose
        # rowid allocator reads MAX(id) itself.)
        conn.execute(
            sa.text(
                "SELECT setval(pg_get_serial_sequence('organization', 'id'), "
                'COALESCE((SELECT MAX(id) FROM organization), 1))'
            )
        )

    for table in OWNED:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.add_column(sa.Column('org_id', sa.Integer(), nullable=True))
        # owner_id -> the organisation that owner was just made admin of. Reads
        # membership rather than assuming the id alignment above, so this stays
        # correct if the seeding strategy ever changes.
        conn.execute(
            sa.text(
                f'UPDATE {table} SET org_id = '
                '(SELECT m.org_id FROM membership m '
                f'WHERE m.interviewer_id = {table}.owner_id)'
            )
        )
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.alter_column('org_id', existing_type=sa.Integer(), nullable=False)
            # Authorship becomes nullable in the same breath: with the organisation
            # owning the row, a departing team member's account can be deleted
            # without taking the org's questions with it (see `_purge_account`).
            batch_op.alter_column('owner_id', existing_type=sa.Integer(), nullable=True)
            batch_op.create_foreign_key(
                f'fk_{table}_org_id', 'organization', ['org_id'], ['id']
            )
            batch_op.create_index(op.f(f'ix_{table}_org_id'), ['org_id'])

    with op.batch_alter_table('invite', schema=None) as batch_op:
        batch_op.alter_column('created_by', existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    """`owner_id` was never dropped, so ownership survives the reversal intact —
    the organisations and the roster are what is lost.

    The NOT NULL on `owner_id` / `created_by` is deliberately NOT restored. Once
    an account has been deleted out of a surviving organisation those columns
    hold NULL by design (see `_disown`), and re-imposing the constraint would
    either abort the downgrade or require inventing an owner for someone else's
    question. A column that is nullable and never null is a harmless difference
    from the pre-X01 schema; losing or misattributing a row is not.
    """
    for table in OWNED:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_index(op.f(f'ix_{table}_org_id'))
            batch_op.drop_column('org_id')
    op.drop_table('orginvite')
    op.drop_table('membership')
    op.drop_table('organization')
