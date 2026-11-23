"""Record which reviewer wrote a Finding when it was not the Agent.

Revision ID: 0008_finding_author
Revises: 0007_agent_handoff
"""
import sqlalchemy as sa
from alembic import op

revision = "0008_finding_author"
down_revision = "0007_agent_handoff"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("investigation_findings", sa.Column("submitted_by_user_id", sa.Uuid()))


def downgrade() -> None:
    op.drop_column("investigation_findings", "submitted_by_user_id")
