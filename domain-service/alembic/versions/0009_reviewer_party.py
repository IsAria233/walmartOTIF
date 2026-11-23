"""Record the party a reviewer names for a cause outside C1-C5.

Revision ID: 0009_reviewer_party
Revises: 0008_finding_author
"""
import sqlalchemy as sa
from alembic import op

revision = "0009_reviewer_party"
down_revision = "0008_finding_author"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("investigation_findings", sa.Column("reviewer_accountable_party", sa.String(20)))


def downgrade() -> None:
    op.drop_column("investigation_findings", "reviewer_accountable_party")
