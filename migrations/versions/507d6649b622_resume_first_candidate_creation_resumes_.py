"""resume-first candidate creation: resumes.job_id, nullable candidate_id, needs_identity_review status

Candidates are now created by the resume pipeline after AI extraction
produces a usable identity (or by HR via confirm-identity), not at upload
time — so Resume needs its own job_id (previously reached only via
candidate.job_id, which didn't exist yet at upload) and candidate_id must
become nullable. The status CHECK constraints on resumes and processing_jobs
widen to include the new NEEDS_IDENTITY_REVIEW / NEEDS_REVIEW values.

Revision ID: 507d6649b622
Revises: 5768cee4e704
Create Date: 2026-08-19 16:03:05.851852

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '507d6649b622'
down_revision: Union[str, None] = '5768cee4e704'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD_RESUME_STATUSES = [
    'uploaded', 'validating', 'stored', 'ocr_processing', 'parsing', 'extracting',
    'normalizing', 'matching', 'completed', 'processing_failed', 'extraction_failed',
    'matching_failed',
]
_NEW_RESUME_STATUSES = [*_OLD_RESUME_STATUSES[:6], 'needs_identity_review', *_OLD_RESUME_STATUSES[6:]]

_OLD_JOB_STATUSES = ['queued', 'running', 'succeeded', 'failed']
_NEW_JOB_STATUSES = [*_OLD_JOB_STATUSES, 'needs_review']


def upgrade() -> None:
    # 1. resumes.job_id — nullable first so existing rows can be backfilled.
    op.add_column('resumes', sa.Column('job_id', sa.String(length=40), nullable=True))
    op.execute(
        """
        UPDATE resumes
        SET job_id = candidates.job_id
        FROM candidates
        WHERE resumes.candidate_id = candidates.id
        """
    )
    op.alter_column('resumes', 'job_id', nullable=False)
    op.create_foreign_key(None, 'resumes', 'hr_jobs', ['job_id'], ['id'], ondelete='CASCADE')
    op.create_index(op.f('ix_resumes_job_id'), 'resumes', ['job_id'], unique=False)

    # 2. resumes.candidate_id becomes optional — unset until identity is confirmed.
    op.alter_column('resumes', 'candidate_id', nullable=True)

    # 3. Widen the resumes.status CHECK constraint.
    op.drop_constraint('resumeprocessingstatus', 'resumes', type_='check')
    op.create_check_constraint(
        'resumeprocessingstatus',
        'resumes',
        sa.column('status').in_(_NEW_RESUME_STATUSES),
    )

    # 4. Widen the processing_jobs.status CHECK constraint.
    op.drop_constraint('processingjobstatus', 'processing_jobs', type_='check')
    op.create_check_constraint(
        'processingjobstatus',
        'processing_jobs',
        sa.column('status').in_(_NEW_JOB_STATUSES),
    )


def downgrade() -> None:
    op.drop_constraint('processingjobstatus', 'processing_jobs', type_='check')
    op.create_check_constraint(
        'processingjobstatus',
        'processing_jobs',
        sa.column('status').in_(_OLD_JOB_STATUSES),
    )

    op.drop_constraint('resumeprocessingstatus', 'resumes', type_='check')
    op.create_check_constraint(
        'resumeprocessingstatus',
        'resumes',
        sa.column('status').in_(_OLD_RESUME_STATUSES),
    )

    # Any resume left without a candidate (paused in NEEDS_IDENTITY_REVIEW,
    # a state that doesn't exist pre-downgrade) has no valid candidate_id to
    # restore — deleting those rows is the only safe way to satisfy the old
    # NOT NULL constraint; this is an accepted, one-way data loss on downgrade.
    op.execute("DELETE FROM resumes WHERE candidate_id IS NULL")
    op.alter_column('resumes', 'candidate_id', nullable=False)

    op.drop_index(op.f('ix_resumes_job_id'), table_name='resumes')
    op.drop_constraint('resumes_job_id_fkey', 'resumes', type_='foreignkey')
    op.drop_column('resumes', 'job_id')
