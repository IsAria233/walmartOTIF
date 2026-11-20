"""Store the destination country for OTIF scope checks.

Revision ID: 0006_dc_country
Revises: 0005_review_fixes
"""
import sqlalchemy as sa
from alembic import op

revision = "0006_dc_country"
down_revision = "0005_review_fixes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("distribution_centers", sa.Column("country_code", sa.String(2), nullable=True))


def downgrade() -> None:
    op.drop_column("distribution_centers", "country_code")
