"""split candidate identity from per-job candidate application; add archival

Candidates are now created per-job-application only (identity_id links to
the new candidate_identities table, which represents the person and is
reused across every job they apply to). Previously `candidates` held both
identity (full_name/email/phone) and per-job state (job_id/stage) on one
row, which made it impossible for one person to have independent
recruitment states across multiple jobs (rejecting Job A would have no way
to *not* also imply Job B). Also adds archival columns for the candidate
archive/restore lifecycle.

Revision ID: 298020f7dcf3
Revises: 507d6649b622
Create Date: 2026-08-19 17:58:26.828425

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.shared.database.ids import IdPrefix, new_id


# revision identifiers, used by Alembic.
revision: str = '298020f7dcf3'
down_revision: Union[str, None] = '507d6649b622'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    op.create_table(
        'candidate_identities',
        sa.Column('id', sa.String(length=40), nullable=False),
        sa.Column('full_name', sa.String(length=255), nullable=False),
        sa.Column('email', sa.String(length=320), nullable=False),
        sa.Column('phone', sa.String(length=40), nullable=True),
        sa.Column('organization_id', sa.String(length=40), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_candidate_identities_organization_id'), 'candidate_identities', ['organization_id']
    )
    op.create_index(op.f('ix_candidate_identities_email'), 'candidate_identities', ['email'])

    op.add_column('candidates', sa.Column('identity_id', sa.String(length=40), nullable=True))
    op.add_column('candidates', sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('candidates', sa.Column('archived_by_user_id', sa.String(length=40), nullable=True))

    # Backfill: one identity per distinct (organization_id, email), then
    # point every existing candidate row at it.
    rows = bind.execute(
        sa.text(
            'SELECT id, organization_id, email, full_name, phone FROM candidates ORDER BY created_at ASC'
        )
    ).fetchall()

    identity_id_by_key: dict[tuple[str, str], str] = {}
    for row in rows:
        key = (row.organization_id, row.email)
        if key not in identity_id_by_key:
            identity_id = new_id(IdPrefix.CANDIDATE_IDENTITY)
            identity_id_by_key[key] = identity_id
            bind.execute(
                sa.text(
                    'INSERT INTO candidate_identities '
                    '(id, organization_id, full_name, email, phone) '
                    'VALUES (:id, :org_id, :full_name, :email, :phone)'
                ),
                {
                    'id': identity_id,
                    'org_id': row.organization_id,
                    'full_name': row.full_name,
                    'email': row.email,
                    'phone': row.phone,
                },
            )
        bind.execute(
            sa.text('UPDATE candidates SET identity_id = :identity_id WHERE id = :id'),
            {'identity_id': identity_id_by_key[key], 'id': row.id},
        )

    op.alter_column('candidates', 'identity_id', nullable=False)
    op.create_foreign_key(
        None, 'candidates', 'candidate_identities', ['identity_id'], ['id'], ondelete='CASCADE'
    )
    op.create_index(op.f('ix_candidates_identity_id'), 'candidates', ['identity_id'])

    op.drop_column('candidates', 'full_name')
    op.drop_column('candidates', 'email')
    op.drop_column('candidates', 'phone')


def downgrade() -> None:
    bind = op.get_bind()

    op.add_column('candidates', sa.Column('full_name', sa.String(length=255), nullable=True))
    op.add_column('candidates', sa.Column('email', sa.String(length=320), nullable=True))
    op.add_column('candidates', sa.Column('phone', sa.String(length=40), nullable=True))

    bind.execute(
        sa.text(
            'UPDATE candidates c SET full_name = i.full_name, email = i.email, phone = i.phone '
            'FROM candidate_identities i WHERE c.identity_id = i.id'
        )
    )

    op.alter_column('candidates', 'full_name', nullable=False)
    op.alter_column('candidates', 'email', nullable=False)

    op.drop_index(op.f('ix_candidates_identity_id'), table_name='candidates')
    op.drop_constraint('candidates_identity_id_fkey', 'candidates', type_='foreignkey')
    op.drop_column('candidates', 'identity_id')
    op.drop_column('candidates', 'archived_by_user_id')
    op.drop_column('candidates', 'archived_at')

    op.drop_index(op.f('ix_candidate_identities_email'), table_name='candidate_identities')
    op.drop_index(op.f('ix_candidate_identities_organization_id'), table_name='candidate_identities')
    op.drop_table('candidate_identities')
