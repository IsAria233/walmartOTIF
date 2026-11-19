"""Add SCRUM-15 case, finding, evaluation, outcome and approval workflow data.

Revision ID: 0004_scrum15_domain_workflows
Revises: 0003_case_attachment_consistency
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004_scrum15_domain_workflows"
down_revision = "0003_case_attachment_consistency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Fail closed: legacy free-form or missing statuses cannot safely be
    # assigned a lifecycle meaning without an explicit product decision.
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (
            SELECT 1 FROM investigation_cases
            WHERE status IS NULL OR status NOT IN (
              'pending', 'investigating', 'findings_submitted', 'awaiting_approval',
              'handed_off', 'revision_required', 'closed'
            )
          ) THEN
            RAISE EXCEPTION 'SCRUM-15 migration blocked: investigation_cases has null or unsupported legacy statuses';
          END IF;
          IF EXISTS (
            SELECT 1 FROM investigation_cases
            WHERE status <> 'closed'
            GROUP BY fine_record_id HAVING count(*) > 1
          ) THEN
            RAISE EXCEPTION 'SCRUM-15 migration blocked: multiple active cases exist for a Fine Record';
          END IF;
          IF EXISTS (
            SELECT dispute_line_id FROM investigation_cases
            WHERE dispute_line_id IS NOT NULL
            GROUP BY dispute_line_id HAVING count(*) > 1
          ) THEN
            RAISE EXCEPTION 'SCRUM-15 migration blocked: a Dispute Line is associated with multiple Cases';
          END IF;
          IF EXISTS (
            SELECT 1 FROM approvals WHERE status NOT IN ('pending', 'approved', 'rejected')
          ) THEN
            RAISE EXCEPTION 'SCRUM-15 migration blocked: approvals contain an unsupported legacy status';
          END IF;
          IF EXISTS (
            SELECT 1 FROM approvals WHERE approval_type NOT IN ('associate', 'manager')
          ) THEN
            RAISE EXCEPTION 'SCRUM-15 migration blocked: approvals contain an unsupported legacy stage';
          END IF;
        END; $$
    """)

    op.create_unique_constraint(
        "uq_investigation_cases_id_fine", "investigation_cases", ["id", "fine_record_id"]
    )
    op.create_table(
        "dispute_line_cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("dispute_line_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("investigation_case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("fine_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["dispute_line_id", "fine_record_id"], ["dispute_lines.id", "dispute_lines.fine_record_id"], name="fk_dispute_line_cases_line_fine", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["investigation_case_id", "fine_record_id"], ["investigation_cases.id", "investigation_cases.fine_record_id"], name="fk_dispute_line_cases_case_fine", ondelete="RESTRICT"),
        sa.UniqueConstraint("dispute_line_id", name="uq_dispute_line_cases_line"),
        sa.UniqueConstraint("dispute_line_id", "investigation_case_id", name="uq_dispute_line_cases_pair"),
    )
    op.create_index("ix_dispute_line_cases_case", "dispute_line_cases", ["investigation_case_id"])
    op.execute("""
        INSERT INTO dispute_line_cases (id, dispute_line_id, investigation_case_id, fine_record_id, created_at)
        SELECT gen_random_uuid(), dispute_line_id, id, fine_record_id, now()
        FROM investigation_cases WHERE dispute_line_id IS NOT NULL
    """)
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (
            SELECT 1 FROM investigation_cases ic
            LEFT JOIN dispute_line_cases dlc ON dlc.investigation_case_id = ic.id
              AND dlc.dispute_line_id = ic.dispute_line_id
            WHERE ic.dispute_line_id IS NOT NULL AND dlc.id IS NULL
          ) THEN RAISE EXCEPTION 'SCRUM-15 migration blocked: Case/Dispute Line backfill verification failed'; END IF;
        END; $$
    """)

    op.create_table(
        "investigation_case_triggers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("investigation_case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("fine_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trigger_rule", sa.String(10), nullable=False),
        sa.Column("scan_id", sa.String(150), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["investigation_case_id", "fine_record_id"], ["investigation_cases.id", "investigation_cases.fine_record_id"], name="fk_case_triggers_case_fine", ondelete="RESTRICT"),
        sa.CheckConstraint("trigger_rule IN ('R1', 'R2')", name="ck_case_triggers_rule"),
    )
    op.create_index("ix_case_triggers_scan", "investigation_case_triggers", ["scan_id"])
    op.create_index("uq_case_trigger_scan_fine_rule", "investigation_case_triggers", ["scan_id", "fine_record_id", "trigger_rule"], unique=True, postgresql_where=sa.text("scan_id <> 'legacy-unknown'"))
    op.execute("""
        INSERT INTO investigation_case_triggers (id, investigation_case_id, fine_record_id, trigger_rule, scan_id, created_at)
        SELECT gen_random_uuid(), id, fine_record_id, scan_rule, 'legacy-unknown', now()
        FROM investigation_cases WHERE origin = 'pre_invoice_scan' AND scan_rule IS NOT NULL
    """)

    op.alter_column("investigation_cases", "status", existing_type=sa.String(length=50), nullable=False, server_default="pending")
    op.create_check_constraint(
        "ck_investigation_cases_status", "investigation_cases",
        "status IN ('pending', 'investigating', 'findings_submitted', 'awaiting_approval', 'handed_off', 'revision_required', 'closed')",
    )
    op.create_index(
        "uq_active_case_per_fine", "investigation_cases", ["fine_record_id"],
        unique=True, postgresql_where=sa.text("status <> 'closed'"),
    )
    op.create_index("ix_investigation_cases_status_created", "investigation_cases", ["status", "created_at", "id"])
    op.create_index("ix_investigation_cases_origin_created", "investigation_cases", ["origin", "created_at", "id"])
    op.create_table(
        "case_status_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("investigation_case_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("investigation_cases.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("from_status", sa.String(50), nullable=True),
        sa.Column("to_status", sa.String(50), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("to_status IN ('pending', 'investigating', 'findings_submitted', 'awaiting_approval', 'handed_off', 'revision_required', 'closed')", name="ck_case_status_events_to_status"),
    )
    op.create_index("ix_case_status_events_case_time", "case_status_events", ["investigation_case_id", "occurred_at"])
    op.create_table(
        "pre_invoice_scan_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("scan_id", sa.String(150), nullable=False),
        sa.Column("fine_record_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("fine_records.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("investigation_case_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("investigation_cases.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("triggered_rules", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("rule_results", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("case_action", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("case_action IN ('created', 'reused_existing', 'skipped')", name="ck_pre_invoice_scan_case_action"),
        sa.UniqueConstraint("scan_id", "fine_record_id", name="uq_pre_invoice_scan_fine"),
    )
    op.create_index("ix_pre_invoice_scan_scan_id", "pre_invoice_scan_results", ["scan_id"])
    op.create_index("ix_pre_invoice_scan_fine_created", "pre_invoice_scan_results", ["fine_record_id", "created_at"])

    op.add_column("investigation_findings", sa.Column("version_number", sa.Integer(), nullable=True))
    op.execute("""
        WITH numbered AS (
          SELECT id, row_number() OVER (
            PARTITION BY investigation_case_id ORDER BY created_at, id
          ) AS version_number FROM investigation_findings
        )
        UPDATE investigation_findings f SET version_number = numbered.version_number
        FROM numbered WHERE f.id = numbered.id
    """)
    op.alter_column("investigation_findings", "version_number", nullable=False)
    op.create_unique_constraint("uq_findings_case_version", "investigation_findings", ["investigation_case_id", "version_number"])
    op.create_unique_constraint("uq_findings_id_case", "investigation_findings", ["id", "investigation_case_id"])
    op.create_check_constraint("ck_findings_version_positive", "investigation_findings", "version_number > 0")

    op.create_table(
        "policy_configurations",
        sa.Column("policy_version", sa.String(50), primary_key=True),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("manager_approval_threshold", sa.Numeric(14, 2), nullable=False),
        sa.Column("fine_rate", sa.Numeric(9, 6), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("manager_approval_threshold >= 0", name="ck_policy_manager_threshold_nonnegative"),
        sa.CheckConstraint("fine_rate >= 0", name="ck_policy_fine_rate_nonnegative"),
    )
    op.create_index("ix_policy_configurations_effective_from", "policy_configurations", ["effective_from"])
    # These values are sourced from docs/otif_policy.md (POC v0.1), not invented defaults.
    op.execute("""
        INSERT INTO policy_configurations
          (policy_version, effective_from, manager_approval_threshold, fine_rate)
        VALUES ('0.1', '1970-01-01T00:00:00+00:00', 500.00, 0.030000)
    """)
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM line_outcomes lo LEFT JOIN policy_configurations p
                     ON p.policy_version = lo.policy_version WHERE p.policy_version IS NULL) THEN
            RAISE EXCEPTION 'SCRUM-15 migration blocked: historical Line Outcomes reference a policy version without configuration';
          END IF;
        END; $$
    """)

    op.create_table(
        "evaluations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("investigation_case_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("investigation_cases.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("finding_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("policy_version", sa.String(50), sa.ForeignKey("policy_configurations.policy_version", ondelete="RESTRICT"), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("calculation_inputs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("calculation_outputs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["finding_id", "investigation_case_id"], ["investigation_findings.id", "investigation_findings.investigation_case_id"], name="fk_evaluations_finding_same_case", ondelete="RESTRICT"),
        sa.UniqueConstraint("investigation_case_id", "version_number", name="uq_evaluations_case_version"),
        sa.UniqueConstraint("id", "investigation_case_id", name="uq_evaluations_id_case"),
        sa.CheckConstraint("version_number > 0", name="ck_evaluations_version_positive"),
    )
    op.create_index("ix_evaluations_case_created", "evaluations", ["investigation_case_id", "created_at"])

    op.create_table(
        "case_outcomes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("investigation_case_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("investigation_cases.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("evaluation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="pending_approval"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["evaluation_id", "investigation_case_id"], ["evaluations.id", "evaluations.investigation_case_id"], name="fk_case_outcomes_evaluation_same_case", ondelete="RESTRICT"),
        sa.UniqueConstraint("evaluation_id", name="uq_case_outcomes_evaluation"),
        sa.UniqueConstraint("id", "investigation_case_id", name="uq_case_outcomes_id_case"),
        sa.CheckConstraint("status IN ('pending_approval', 'pending_manager_approval', 'approved', 'rejected')", name="ck_case_outcomes_status"),
    )
    op.create_index("ix_case_outcomes_case_created", "case_outcomes", ["investigation_case_id", "created_at"])

    op.add_column("line_outcomes", sa.Column("case_outcome_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("line_outcomes", sa.Column("investigation_case_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("line_outcomes", sa.Column("evaluated_line_key", sa.String(150), nullable=True))
    op.add_column("line_outcomes", sa.Column("reversal_amount", sa.Numeric(14, 2), nullable=False, server_default="0"))
    op.add_column("line_outcomes", sa.Column("approval_status", sa.String(40), nullable=False, server_default="pending_approval"))
    op.drop_constraint("uq_line_outcomes_finding", "line_outcomes", type_="unique")
    op.create_foreign_key("fk_line_outcomes_case_outcome_same_case", "line_outcomes", "case_outcomes", ["case_outcome_id", "investigation_case_id"], ["id", "investigation_case_id"], ondelete="RESTRICT")
    op.create_unique_constraint("uq_line_outcomes_evaluated_line", "line_outcomes", ["case_outcome_id", "evaluated_line_key"])
    op.create_check_constraint("ck_line_outcomes_approval_status", "line_outcomes", "approval_status IN ('pending_approval', 'pending_manager_approval', 'approved', 'rejected')")

    # Convert each legacy Line Outcome into a one-line historical aggregate
    # tied to a snapshot Evaluation of its original Finding. Amounts and policy
    # versions are copied verbatim; no historical decision is recalculated.
    op.execute("""
        CREATE TEMP TABLE _scrum15_legacy_outcome_map ON COMMIT DROP AS
        SELECT gen_random_uuid() AS evaluation_id, gen_random_uuid() AS outcome_id,
               lo.id AS line_outcome_id, f.investigation_case_id,
               f.id AS finding_id, lo.policy_version,
               row_number() OVER (PARTITION BY f.investigation_case_id ORDER BY lo.created_at, lo.id) AS version_number,
               lo.calculated_at, lo.created_at, lo.outcome, lo.accountable_party,
               lo.original_amount, lo.corrected_amount, lo.rationale,
               lo.original_amount - lo.corrected_amount AS reversal_amount,
               CASE
                 WHEN COALESCE(bool_or(approval.status = 'rejected'), false) THEN 'rejected'
                 WHEN lo.original_amount - lo.corrected_amount > policy.manager_approval_threshold
                      AND COALESCE(bool_or(approval.approval_type = 'associate' AND approval.status = 'approved'), false)
                      AND NOT COALESCE(bool_or(approval.approval_type = 'manager' AND approval.status = 'approved'), false)
                   THEN 'pending_manager_approval'
                 WHEN count(approval.id) > 0 AND bool_and(approval.status = 'approved') THEN 'approved'
                 ELSE 'pending_approval'
               END AS workflow_status
        FROM line_outcomes lo
        JOIN investigation_findings f ON f.id = lo.finding_id
        JOIN policy_configurations policy ON policy.policy_version = lo.policy_version
        LEFT JOIN approvals approval ON approval.line_outcome_id = lo.id
        GROUP BY lo.id, f.investigation_case_id, f.id, policy.manager_approval_threshold
    """)
    op.execute("""
        INSERT INTO evaluations (id, investigation_case_id, finding_id, version_number,
                                 policy_version, evaluated_at, result, calculation_inputs,
                                 calculation_outputs, created_at)
        SELECT evaluation_id, investigation_case_id, finding_id, version_number,
               policy_version, calculated_at,
               jsonb_build_object('legacy_snapshot', true, 'outcome', outcome,
                 'accountable_party', accountable_party, 'original_amount', original_amount,
                 'corrected_amount', corrected_amount, 'rationale', rationale),
               jsonb_build_object('source_line_outcome_id', line_outcome_id),
               jsonb_build_object('reversal_amount', reversal_amount), created_at
        FROM _scrum15_legacy_outcome_map
    """)
    op.execute("""
        INSERT INTO case_outcomes (id, investigation_case_id, evaluation_id, status, created_at)
        SELECT outcome_id, investigation_case_id, evaluation_id, workflow_status, created_at
        FROM _scrum15_legacy_outcome_map
    """)
    op.execute("""
        UPDATE line_outcomes lo SET
          case_outcome_id = legacy.outcome_id,
          investigation_case_id = legacy.investigation_case_id,
          evaluated_line_key = ic.fine_record_id::text,
          reversal_amount = legacy.reversal_amount,
          approval_status = legacy.workflow_status
        FROM _scrum15_legacy_outcome_map legacy
        JOIN investigation_cases ic ON ic.id = legacy.investigation_case_id
        WHERE lo.id = legacy.line_outcome_id
    """)
    op.alter_column("line_outcomes", "case_outcome_id", nullable=False)
    op.alter_column("line_outcomes", "investigation_case_id", nullable=False)
    op.alter_column("line_outcomes", "evaluated_line_key", nullable=False)

    op.create_check_constraint("ck_approvals_stage", "approvals", "approval_type IN ('associate', 'manager')")
    op.create_check_constraint("ck_approvals_status", "approvals", "status IN ('pending', 'approved', 'rejected')")
    op.create_unique_constraint("uq_approvals_line_stage", "approvals", ["line_outcome_id", "approval_type"])

    # Findings/evaluations/decisions are audit records. Services append new
    # versions/decisions; the database also blocks direct UPDATE/DELETE.
    op.execute("""
        CREATE FUNCTION reject_audit_record_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'Audit records are append-only: %', TG_TABLE_NAME;
        END; $$ LANGUAGE plpgsql
    """)
    for table in ("investigation_findings", "finding_facts", "evidence_records", "evidence_links", "evaluations", "approval_decisions", "case_status_events", "investigation_case_triggers", "dispute_line_cases", "pre_invoice_scan_results"):
        op.execute(f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION reject_audit_record_mutation()")
    op.execute("""
        CREATE FUNCTION protect_outcome_history() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'Aggregate Outcomes are historical records'; END IF;
          IF NEW.investigation_case_id IS DISTINCT FROM OLD.investigation_case_id
             OR NEW.evaluation_id IS DISTINCT FROM OLD.evaluation_id
             OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
            RAISE EXCEPTION 'Aggregate Outcome identity and Evaluation snapshot are immutable';
          END IF;
          IF NEW.status IS DISTINCT FROM OLD.status AND NOT (
            (OLD.status = 'pending_approval' AND NEW.status IN ('pending_manager_approval', 'approved', 'rejected'))
            OR (OLD.status = 'pending_manager_approval' AND NEW.status IN ('pending_approval', 'approved', 'rejected'))
          ) THEN RAISE EXCEPTION 'Invalid Aggregate Outcome status transition'; END IF;
          RETURN NEW;
        END; $$ LANGUAGE plpgsql
    """)
    op.execute("CREATE TRIGGER case_outcomes_history_guard BEFORE UPDATE OR DELETE ON case_outcomes FOR EACH ROW EXECUTE FUNCTION protect_outcome_history()")
    op.execute("""
        CREATE FUNCTION protect_line_outcome_history() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'Line Outcomes are historical records'; END IF;
          IF NEW.case_outcome_id IS DISTINCT FROM OLD.case_outcome_id
             OR NEW.investigation_case_id IS DISTINCT FROM OLD.investigation_case_id
             OR NEW.evaluated_line_key IS DISTINCT FROM OLD.evaluated_line_key
             OR NEW.finding_id IS DISTINCT FROM OLD.finding_id
             OR NEW.outcome IS DISTINCT FROM OLD.outcome
             OR NEW.policy_version IS DISTINCT FROM OLD.policy_version
             OR NEW.accountable_party IS DISTINCT FROM OLD.accountable_party
             OR NEW.original_amount IS DISTINCT FROM OLD.original_amount
             OR NEW.corrected_amount IS DISTINCT FROM OLD.corrected_amount
             OR NEW.rationale IS DISTINCT FROM OLD.rationale
             OR NEW.calculated_at IS DISTINCT FROM OLD.calculated_at
             OR NEW.reversal_amount IS DISTINCT FROM OLD.reversal_amount
             OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
            RAISE EXCEPTION 'Line Outcome financial snapshot is immutable';
          END IF;
          IF NEW.approval_status IS DISTINCT FROM OLD.approval_status AND NOT (
            (OLD.approval_status = 'pending_approval' AND NEW.approval_status IN ('pending_manager_approval', 'approved', 'rejected'))
            OR (OLD.approval_status = 'pending_manager_approval' AND NEW.approval_status IN ('approved', 'rejected'))
          ) THEN RAISE EXCEPTION 'Invalid Line Outcome approval transition'; END IF;
          RETURN NEW;
        END; $$ LANGUAGE plpgsql
    """)
    op.execute("CREATE TRIGGER line_outcomes_history_guard BEFORE UPDATE OR DELETE ON line_outcomes FOR EACH ROW EXECUTE FUNCTION protect_line_outcome_history()")
    op.execute("""
        CREATE FUNCTION protect_used_policy_configuration() RETURNS trigger AS $$
        BEGIN
          IF EXISTS (SELECT 1 FROM evaluations WHERE policy_version = OLD.policy_version) THEN
            RAISE EXCEPTION 'Policy configuration % is immutable after evaluation use', OLD.policy_version;
          END IF;
          IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END; $$ LANGUAGE plpgsql
    """)
    op.execute("CREATE TRIGGER policy_configurations_used_immutable BEFORE UPDATE OR DELETE ON policy_configurations FOR EACH ROW EXECUTE FUNCTION protect_used_policy_configuration()")


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM evaluations WHERE result->>'legacy_snapshot' IS DISTINCT FROM 'true') THEN
            RAISE EXCEPTION 'SCRUM-15 downgrade blocked: non-legacy Evaluations would lose audit data';
          END IF;
          IF EXISTS (SELECT 1 FROM investigation_case_triggers WHERE scan_id <> 'legacy-unknown') THEN
            RAISE EXCEPTION 'SCRUM-15 downgrade blocked: scan trigger history would be lost';
          END IF;
          IF EXISTS (SELECT 1 FROM pre_invoice_scan_results) THEN
            RAISE EXCEPTION 'SCRUM-15 downgrade blocked: scan idempotency results would be lost';
          END IF;
          IF EXISTS (SELECT 1 FROM case_status_events) THEN
            RAISE EXCEPTION 'SCRUM-15 downgrade blocked: Case lifecycle history would be lost';
          END IF;
          IF EXISTS (
            SELECT investigation_case_id, finding_id FROM line_outcomes
            GROUP BY investigation_case_id, finding_id HAVING count(*) > 1
          ) THEN
            RAISE EXCEPTION 'SCRUM-15 downgrade blocked: one Finding has multiple Line Outcomes';
          END IF;
          IF EXISTS (SELECT 1 FROM policy_configurations WHERE policy_version <> '0.1') THEN
            RAISE EXCEPTION 'SCRUM-15 downgrade blocked: additional policy configurations would be lost';
          END IF;
          IF EXISTS (
            SELECT 1 FROM dispute_line_cases dlc JOIN investigation_cases ic ON ic.id = dlc.investigation_case_id
            WHERE ic.dispute_line_id IS DISTINCT FROM dlc.dispute_line_id
          ) THEN
            RAISE EXCEPTION 'SCRUM-15 downgrade blocked: new Case/Dispute Line links would be lost';
          END IF;
        END; $$
    """)
    op.execute("DROP TRIGGER line_outcomes_history_guard ON line_outcomes")
    op.execute("DROP FUNCTION protect_line_outcome_history()")
    op.execute("DROP TRIGGER case_outcomes_history_guard ON case_outcomes")
    op.execute("DROP FUNCTION protect_outcome_history()")
    op.execute("DROP TRIGGER policy_configurations_used_immutable ON policy_configurations")
    op.execute("DROP FUNCTION protect_used_policy_configuration()")
    for table in ("pre_invoice_scan_results", "dispute_line_cases", "investigation_case_triggers", "case_status_events", "approval_decisions", "evaluations", "evidence_links", "evidence_records", "finding_facts", "investigation_findings"):
        op.execute(f"DROP TRIGGER {table}_append_only ON {table}")
    op.execute("DROP FUNCTION reject_audit_record_mutation()")
    op.drop_constraint("uq_approvals_line_stage", "approvals", type_="unique")
    op.drop_constraint("ck_approvals_status", "approvals", type_="check")
    op.drop_constraint("ck_approvals_stage", "approvals", type_="check")
    op.drop_constraint("ck_line_outcomes_approval_status", "line_outcomes", type_="check")
    op.drop_constraint("uq_line_outcomes_evaluated_line", "line_outcomes", type_="unique")
    op.drop_constraint("fk_line_outcomes_case_outcome_same_case", "line_outcomes", type_="foreignkey")
    op.create_unique_constraint("uq_line_outcomes_finding", "line_outcomes", ["finding_id"])
    for column in ("approval_status", "reversal_amount", "evaluated_line_key", "investigation_case_id", "case_outcome_id"):
        op.drop_column("line_outcomes", column)
    op.drop_index("ix_case_outcomes_case_created", table_name="case_outcomes")
    op.drop_table("case_outcomes")
    op.drop_index("ix_evaluations_case_created", table_name="evaluations")
    op.drop_table("evaluations")
    op.drop_index("ix_policy_configurations_effective_from", table_name="policy_configurations")
    op.drop_table("policy_configurations")
    op.drop_constraint("uq_findings_id_case", "investigation_findings", type_="unique")
    op.drop_constraint("uq_findings_case_version", "investigation_findings", type_="unique")
    op.drop_constraint("ck_findings_version_positive", "investigation_findings", type_="check")
    op.drop_column("investigation_findings", "version_number")
    op.drop_index("ix_case_status_events_case_time", table_name="case_status_events")
    op.drop_table("case_status_events")
    op.drop_index("ix_pre_invoice_scan_fine_created", table_name="pre_invoice_scan_results")
    op.drop_index("ix_pre_invoice_scan_scan_id", table_name="pre_invoice_scan_results")
    op.drop_table("pre_invoice_scan_results")
    op.drop_index("ix_investigation_cases_origin_created", table_name="investigation_cases")
    op.drop_index("ix_investigation_cases_status_created", table_name="investigation_cases")
    op.drop_index("uq_active_case_per_fine", table_name="investigation_cases")
    op.drop_constraint("ck_investigation_cases_status", "investigation_cases", type_="check")
    op.alter_column("investigation_cases", "status", existing_type=sa.String(length=50), nullable=True, server_default=None)
    op.drop_index("uq_case_trigger_scan_fine_rule", table_name="investigation_case_triggers")
    op.drop_index("ix_case_triggers_scan", table_name="investigation_case_triggers")
    op.drop_table("investigation_case_triggers")
    op.drop_index("ix_dispute_line_cases_case", table_name="dispute_line_cases")
    op.drop_table("dispute_line_cases")
    op.drop_constraint("uq_investigation_cases_id_fine", "investigation_cases", type_="unique")
