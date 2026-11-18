"""Align domain records with SCRUM-16 review findings.

Revision ID: 0002_review_revisions
Revises: 0001_domain_schema
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_review_revisions"
down_revision = "0001_domain_schema"
branch_labels = None
depends_on = None


# Constraints that were created unnamed by PostgreSQL in revision 0001 receive
# its conventional <table>_<column>_fkey names.
_RESTRICT_FKS = (
    ("po_lines", "po_lines_purchase_order_id_fkey", "purchase_order_id", "purchase_orders", "id"),
    ("po_line_versions", "po_line_versions_po_line_id_fkey", "po_line_id", "po_lines", "id"),
    ("asn_lines", "asn_lines_asn_id_fkey", "asn_id", "asns", "id"),
    ("appointment_events", "appointment_events_po_line_id_fkey", "po_line_id", "po_lines", "id"),
    ("delivery_lines", "delivery_lines_delivery_id_fkey", "delivery_id", "deliveries", "id"),
    ("gate_logs", "gate_logs_delivery_id_fkey", "delivery_id", "deliveries", "id"),
    ("receiving_records", "receiving_records_delivery_line_id_fkey", "delivery_line_id", "delivery_lines", "id"),
    ("weather_alerts", "weather_alerts_distribution_center_id_fkey", "distribution_center_id", "distribution_centers", "id"),
    ("dispute_lines", "dispute_lines_dispute_id_fkey", "dispute_id", "disputes", "id"),
    ("attachments", "attachments_dispute_id_fkey", "dispute_id", "disputes", "id"),
    ("investigation_findings", "investigation_findings_investigation_case_id_fkey", "investigation_case_id", "investigation_cases", "id"),
    ("finding_facts", "finding_facts_finding_id_fkey", "finding_id", "investigation_findings", "id"),
    ("evidence_links", "evidence_links_finding_fact_id_fkey", "finding_fact_id", "finding_facts", "id"),
    ("approvals", "approvals_line_outcome_id_fkey", "line_outcome_id", "line_outcomes", "id"),
    ("approval_decisions", "approval_decisions_approval_id_fkey", "approval_id", "approvals", "id"),
)


def upgrade() -> None:
    # Destination evidence and Delivery ownership.
    for name, type_ in (
        ("region", sa.String(150)),
        ("address_line1", sa.String(255)),
        ("address_line2", sa.String(255)),
        ("city", sa.String(150)),
        ("state", sa.String(100)),
        ("postal_code", sa.String(30)),
    ):
        op.add_column("distribution_centers", sa.Column(name, type_, nullable=True))
    op.add_column("deliveries", sa.Column("distribution_center_id", sa.Uuid(), nullable=True))
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (
            SELECT d.id
            FROM deliveries d
            LEFT JOIN delivery_lines dl ON dl.delivery_id = d.id
            LEFT JOIN asn_lines al ON al.id = dl.asn_line_id
            LEFT JOIN po_lines pl ON pl.id = al.po_line_id
            LEFT JOIN purchase_orders po ON po.id = pl.purchase_order_id
            GROUP BY d.id
            HAVING count(DISTINCT po.distribution_center_id) <> 1
          ) THEN
            RAISE EXCEPTION 'Cannot infer one destination Distribution Center for every existing Delivery';
          END IF;
        END; $$
    """)
    op.execute("""
        UPDATE deliveries d SET distribution_center_id = q.dc_ids[1]
        FROM (
          SELECT dl.delivery_id, array_agg(DISTINCT po.distribution_center_id) AS dc_ids
          FROM delivery_lines dl
          JOIN asn_lines al ON al.id = dl.asn_line_id
          JOIN po_lines pl ON pl.id = al.po_line_id
          JOIN purchase_orders po ON po.id = pl.purchase_order_id
          GROUP BY dl.delivery_id
        ) q WHERE q.delivery_id = d.id
    """)
    op.alter_column("deliveries", "distribution_center_id", nullable=False)
    op.create_foreign_key(
        "deliveries_distribution_center_id_fkey", "deliveries", "distribution_centers",
        ["distribution_center_id"], ["id"], ondelete="RESTRICT"
    )
    op.create_index("ix_deliveries_dc_arrival", "deliveries", ["distribution_center_id", "actual_arrival_ts"])

    # Move PO-wide freight and channel fields. Abort if old line data conflicts.
    op.add_column("purchase_orders", sa.Column("freight_terms", sa.String(50), nullable=True))
    op.add_column("purchase_orders", sa.Column("channel", sa.String(50), nullable=True))
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (
            SELECT purchase_order_id FROM po_lines
            GROUP BY purchase_order_id
            HAVING count(DISTINCT freight_terms) > 1 OR count(DISTINCT channel) > 1
          ) THEN
            RAISE EXCEPTION 'Cannot move conflicting per-line freight_terms/channel values to purchase_orders';
          END IF;
        END; $$
    """)
    op.execute("""
        UPDATE purchase_orders po SET freight_terms = q.freight_terms, channel = q.channel
        FROM (
          SELECT purchase_order_id, min(freight_terms) AS freight_terms, min(channel) AS channel
          FROM po_lines GROUP BY purchase_order_id
        ) q WHERE q.purchase_order_id = po.id
    """)
    op.drop_column("po_lines", "freight_terms")
    op.drop_column("po_lines", "channel")

    # Dispute ownership is derived only when every fine line has the same supplier.
    op.add_column("disputes", sa.Column("supplier_id", sa.Uuid(), nullable=True))
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (
            SELECT d.id
            FROM disputes d
            LEFT JOIN dispute_lines dl ON dl.dispute_id = d.id
            LEFT JOIN fine_records f ON f.id = dl.fine_record_id
            LEFT JOIN po_lines pl ON pl.id = f.po_line_id
            LEFT JOIN purchase_orders po ON po.id = pl.purchase_order_id
            GROUP BY d.id
            HAVING count(DISTINCT po.supplier_id) <> 1
          ) THEN
            RAISE EXCEPTION 'Cannot infer one Supplier for every existing Dispute';
          END IF;
        END; $$
    """)
    op.execute("""
        UPDATE disputes d SET supplier_id = q.supplier_ids[1]
        FROM (
          SELECT dl.dispute_id, array_agg(DISTINCT po.supplier_id) AS supplier_ids
          FROM dispute_lines dl
          JOIN fine_records f ON f.id = dl.fine_record_id
          JOIN po_lines pl ON pl.id = f.po_line_id
          JOIN purchase_orders po ON po.id = pl.purchase_order_id
          GROUP BY dl.dispute_id
        ) q WHERE q.dispute_id = d.id
    """)
    op.alter_column("disputes", "supplier_id", nullable=False)
    op.create_foreign_key(None, "disputes", "suppliers", ["supplier_id"], ["id"], ondelete="RESTRICT")
    op.create_index("ix_disputes_supplier_submitted", "disputes", ["supplier_id", "submitted_at"])

    # Line outcomes retain both original and corrected calculation details.
    op.add_column("line_outcomes", sa.Column("policy_version", sa.String(50), nullable=True))
    op.add_column("line_outcomes", sa.Column("accountable_party", sa.String(30), nullable=True))
    op.add_column("line_outcomes", sa.Column("original_amount", sa.Numeric(14, 2), nullable=True))
    op.add_column("line_outcomes", sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("""
        UPDATE line_outcomes lo
        SET policy_version = '0.1', accountable_party = lower(f.system_accountability),
            original_amount = f.original_amount, calculated_at = lo.created_at
        FROM investigation_findings fi
        JOIN investigation_cases ic ON ic.id = fi.investigation_case_id
        JOIN fine_records f ON f.id = ic.fine_record_id
        WHERE lo.finding_id = fi.id
    """)
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (
            SELECT 1 FROM line_outcomes
            WHERE policy_version IS NULL OR accountable_party IS NULL OR accountable_party NOT IN ('supplier', 'walmart')
               OR original_amount IS NULL OR calculated_at IS NULL
          ) THEN
            RAISE EXCEPTION 'Cannot backfill required Line Outcome snapshot fields';
          END IF;
        END; $$
    """)
    for column in ("policy_version", "accountable_party", "original_amount", "calculated_at"):
        op.alter_column("line_outcomes", column, nullable=False)
    op.create_check_constraint("ck_line_outcomes_accountable_party", "line_outcomes", "accountable_party IN ('supplier', 'walmart')")
    op.create_check_constraint("ck_line_outcomes_original_amount_nonnegative", "line_outcomes", "original_amount >= 0")

    # Per-finding run and handoff provenance; preserve legacy case-level run IDs.
    op.add_column("investigation_findings", sa.Column("agent_run_id", sa.Uuid(), nullable=True))
    op.add_column("investigation_findings", sa.Column("handoff_required", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column("investigation_findings", sa.Column("handoff_reason", sa.Text(), nullable=True))
    op.add_column("investigation_findings", sa.Column("injection_detected", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.execute("UPDATE investigation_findings fi SET agent_run_id = ic.agent_run_id FROM investigation_cases ic WHERE ic.id = fi.investigation_case_id AND ic.agent_run_id IS NOT NULL AND (SELECT count(*) FROM investigation_findings fi2 WHERE fi2.investigation_case_id = ic.id) = 1")
    op.create_index("ix_investigation_findings_agent_run_id", "investigation_findings", ["agent_run_id"])
    op.add_column("investigation_cases", sa.Column("scan_rule", sa.String(10), nullable=True))
    op.create_check_constraint("ck_investigation_cases_scan_rule", "investigation_cases", "scan_rule IS NULL OR (origin = 'pre_invoice_scan' AND scan_rule IN ('R1', 'R2'))")
    op.add_column("approvals", sa.Column("assigned_to_user_id", sa.Uuid(), nullable=True))
    op.create_index("ix_approvals_assigned_user", "approvals", ["assigned_to_user_id"])
    op.add_column("attachments", sa.Column("dispute_line_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("attachments_dispute_line_id_fkey", "attachments", "dispute_lines", ["dispute_line_id"], ["id"], ondelete="RESTRICT")
    op.create_index("ix_attachments_dispute_line_id", "attachments", ["dispute_line_id"])

    # Replace cascading / SET NULL actions with RESTRICT for retained history.
    for table, name, column, referred_table, referred_column in _RESTRICT_FKS:
        op.drop_constraint(name, table, type_="foreignkey")
        op.create_foreign_key(name, table, referred_table, [column], [referred_column], ondelete="RESTRICT")
    op.drop_constraint("investigation_cases_dispute_line_id_fkey", "investigation_cases", type_="foreignkey")
    op.create_foreign_key("investigation_cases_dispute_line_id_fkey", "investigation_cases", "dispute_lines", ["dispute_line_id"], ["id"], ondelete="RESTRICT")


def downgrade() -> None:
    # Restore original foreign key actions before removing review-added columns.
    for table, name, column, referred_table, referred_column in reversed(_RESTRICT_FKS):
        op.drop_constraint(name, table, type_="foreignkey")
        op.create_foreign_key(name, table, referred_table, [column], [referred_column], ondelete="CASCADE")
    op.drop_constraint("investigation_cases_dispute_line_id_fkey", "investigation_cases", type_="foreignkey")
    op.create_foreign_key("investigation_cases_dispute_line_id_fkey", "investigation_cases", "dispute_lines", ["dispute_line_id"], ["id"], ondelete="SET NULL")

    op.drop_index("ix_attachments_dispute_line_id", table_name="attachments")
    op.drop_constraint("attachments_dispute_line_id_fkey", "attachments", type_="foreignkey")
    op.drop_column("attachments", "dispute_line_id")
    op.drop_index("ix_approvals_assigned_user", table_name="approvals")
    op.drop_column("approvals", "assigned_to_user_id")
    op.drop_constraint("ck_investigation_cases_scan_rule", "investigation_cases", type_="check")
    op.drop_column("investigation_cases", "scan_rule")
    op.drop_index("ix_investigation_findings_agent_run_id", table_name="investigation_findings")
    op.drop_column("investigation_findings", "injection_detected")
    op.drop_column("investigation_findings", "handoff_reason")
    op.drop_column("investigation_findings", "handoff_required")
    op.drop_column("investigation_findings", "agent_run_id")
    op.drop_constraint("ck_line_outcomes_original_amount_nonnegative", "line_outcomes", type_="check")
    op.drop_constraint("ck_line_outcomes_accountable_party", "line_outcomes", type_="check")
    for column in ("calculated_at", "original_amount", "accountable_party", "policy_version"):
        op.drop_column("line_outcomes", column)
    op.drop_index("ix_disputes_supplier_submitted", table_name="disputes")
    op.drop_constraint("disputes_supplier_id_fkey", "disputes", type_="foreignkey")
    op.drop_column("disputes", "supplier_id")
    op.add_column("po_lines", sa.Column("freight_terms", sa.String(50), nullable=True))
    op.add_column("po_lines", sa.Column("channel", sa.String(50), nullable=True))
    op.execute("UPDATE po_lines pl SET freight_terms = po.freight_terms, channel = po.channel FROM purchase_orders po WHERE po.id = pl.purchase_order_id")
    op.drop_column("purchase_orders", "channel")
    op.drop_column("purchase_orders", "freight_terms")
    op.drop_index("ix_deliveries_dc_arrival", table_name="deliveries")
    op.drop_constraint("deliveries_distribution_center_id_fkey", "deliveries", type_="foreignkey")
    op.drop_column("deliveries", "distribution_center_id")
    for name in ("postal_code", "state", "city", "address_line2", "address_line1", "region"):
        op.drop_column("distribution_centers", name)
