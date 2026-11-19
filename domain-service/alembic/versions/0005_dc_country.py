"""Store the destination country for OTIF scope checks."""

import sqlalchemy as sa
from alembic import op

revision = "0005_dc_country"
down_revision = "0004_scrum15_domain_workflows"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("distribution_centers", sa.Column("country_code", sa.String(2), nullable=True))


def downgrade() -> None:
    op.drop_column("distribution_centers", "country_code")
