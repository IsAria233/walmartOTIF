"""Attachment text, direct source-record citations, and finding detail fields.

Revision ID: 0005_review_fixes
Revises: 0004_scrum15_domain_workflows
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005_review_fixes"
down_revision = "0004_scrum15_domain_workflows"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # All additive and nullable: existing rows are untouched.
    op.add_column("attachments", sa.Column("content_text", sa.Text(), nullable=True))
    op.add_column("investigation_findings", sa.Column("confidence_level", sa.String(10), nullable=True))
    op.add_column("investigation_findings", sa.Column("ruled_out_causes", postgresql.JSONB(), nullable=True))
    op.add_column("finding_facts", sa.Column("source_records", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("finding_facts", "source_records")
    op.drop_column("investigation_findings", "ruled_out_causes")
    op.drop_column("investigation_findings", "confidence_level")
    op.drop_column("attachments", "content_text")
