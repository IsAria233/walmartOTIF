"""Enforce investigation case and attachment ownership consistency.

Revision ID: 0003_case_attachment_consistency
Revises: 0002_review_revisions
"""
from alembic import op

revision = "0003_case_attachment_consistency"
down_revision = "0002_review_revisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Fail with an explicit diagnostic instead of leaving old inconsistent rows
    # to fail later during constraint creation.
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (
            SELECT 1 FROM investigation_cases ic
            WHERE (ic.origin = 'supplier_dispute' AND ic.dispute_line_id IS NULL)
               OR (ic.origin = 'pre_invoice_scan' AND ic.dispute_line_id IS NOT NULL)
               OR (ic.scan_rule IS NOT NULL AND
                   (ic.origin <> 'pre_invoice_scan' OR ic.scan_rule NOT IN ('R1', 'R2')))
          ) THEN
            RAISE EXCEPTION 'Existing Investigation Cases violate origin, dispute-line, or scan-rule requirements';
          END IF;
          IF EXISTS (
            SELECT 1
            FROM investigation_cases ic
            JOIN dispute_lines dl ON dl.id = ic.dispute_line_id
            WHERE dl.fine_record_id <> ic.fine_record_id
          ) THEN
            RAISE EXCEPTION 'Existing Investigation Case dispute lines reference a different Fine Record';
          END IF;
          IF EXISTS (
            SELECT 1
            FROM attachments a
            JOIN dispute_lines dl ON dl.id = a.dispute_line_id
            WHERE dl.dispute_id <> a.dispute_id
          ) THEN
            RAISE EXCEPTION 'Existing Attachments reference a Dispute Line from another Dispute';
          END IF;
        END; $$
    """)

    # Composite foreign keys need a unique key over each referenced column pair.
    op.create_unique_constraint(
        "uq_dispute_lines_id_fine_record", "dispute_lines", ["id", "fine_record_id"]
    )
    op.create_unique_constraint(
        "uq_dispute_lines_id_dispute", "dispute_lines", ["id", "dispute_id"]
    )

    op.drop_constraint(
        "investigation_cases_dispute_line_id_fkey",
        "investigation_cases",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_investigation_cases_dispute_line_matches_fine_record",
        "investigation_cases",
        "dispute_lines",
        ["dispute_line_id", "fine_record_id"],
        ["id", "fine_record_id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_investigation_cases_origin_dispute_line",
        "investigation_cases",
        "(origin = 'supplier_dispute' AND dispute_line_id IS NOT NULL) OR "
        "(origin = 'pre_invoice_scan' AND dispute_line_id IS NULL)",
    )

    op.drop_constraint(
        "attachments_dispute_line_id_fkey", "attachments", type_="foreignkey"
    )
    op.create_foreign_key(
        "fk_attachments_dispute_line_matches_dispute",
        "attachments",
        "dispute_lines",
        ["dispute_line_id", "dispute_id"],
        ["id", "dispute_id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_attachments_dispute_line_matches_dispute", "attachments", type_="foreignkey"
    )
    op.create_foreign_key(
        "attachments_dispute_line_id_fkey",
        "attachments",
        "dispute_lines",
        ["dispute_line_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        "ck_investigation_cases_origin_dispute_line",
        "investigation_cases",
        type_="check",
    )
    op.drop_constraint(
        "fk_investigation_cases_dispute_line_matches_fine_record",
        "investigation_cases",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "investigation_cases_dispute_line_id_fkey",
        "investigation_cases",
        "dispute_lines",
        ["dispute_line_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        "uq_dispute_lines_id_dispute", "dispute_lines", type_="unique"
    )
    op.drop_constraint(
        "uq_dispute_lines_id_fine_record", "dispute_lines", type_="unique"
    )
