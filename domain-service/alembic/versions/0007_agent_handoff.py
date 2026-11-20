"""Store Agent handoff notes and run references in the case audit history.

Revision ID: 0007_agent_handoff
Revises: 0006_dc_country
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0007_agent_handoff"
down_revision = "0006_dc_country"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("case_status_events", sa.Column("agent_run_id", sa.Uuid()))
    op.add_column("case_status_events", sa.Column("handoff_details", JSONB()))
    op.create_unique_constraint(
        "uq_case_status_events_agent_run", "case_status_events", ["investigation_case_id", "agent_run_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_case_status_events_agent_run", "case_status_events", type_="unique")
    op.drop_column("case_status_events", "handoff_details")
    op.drop_column("case_status_events", "agent_run_id")
