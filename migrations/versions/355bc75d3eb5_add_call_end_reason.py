"""add call end_reason

Revision ID: 355bc75d3eb5
Revises: e31e62e7c0ab
Create Date: 2026-09-17 16:43:30.550171

Adds Call.end_reason (nullable) — a real signal from the LiveKit runtime's
CloseEvent.reason (see app.workers.voice_agent_worker), used by the voice
analytics dashboard's Disposition/How-calls-ended sections. Existing rows
get NULL, surfaced by analytics as "Unknown"/"Not enough data", never
backfilled with an invented value.

Note: alembic's autogenerate also detected an unrelated pre-existing type
drift on document_chunks.embedding (JSON vs. Vector, an artifact of
whether the pgvector extension was installed when that earlier migration
ran on a given database) — intentionally NOT included here; that's a
separate, unrelated concern from this change.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '355bc75d3eb5'
down_revision: Union[str, None] = 'e31e62e7c0ab'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('calls', sa.Column('end_reason', sa.String(length=60), nullable=True))
    op.create_index(op.f('ix_calls_end_reason'), 'calls', ['end_reason'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_calls_end_reason'), table_name='calls')
    op.drop_column('calls', 'end_reason')
