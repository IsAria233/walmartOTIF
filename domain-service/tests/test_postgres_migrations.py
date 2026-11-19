"""Exercise migration backfills, preflight guards, and safe downgrade in a temp schema."""
from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

DATABASE_NAME = "walmart_otif_scrum15_test"


@pytest.fixture(scope="session")
def pg_engine():
    value = os.getenv("SCRUM15_TEST_DATABASE_URL")
    if not value:
        pytest.skip("SCRUM15_TEST_DATABASE_URL is not configured")
    url = make_url(value)
    if url.database != DATABASE_NAME or url.username != "stephenhuang":
        pytest.fail("Refusing migration test against a database or role outside the approved target")
    engine = create_engine(url, poolclass=NullPool)
    with engine.connect() as connection:
        identity = connection.execute(text("SELECT current_database(), current_user")).one()
        assert identity == (DATABASE_NAME, "stephenhuang")
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0004_scrum15_domain_workflows"
    yield engine
    engine.dispose()


def test_postgres_legacy_backfill_preflight_and_safe_downgrade(pg_engine):
    schema = f"scrum15_mig_{uuid.uuid4().hex[:12]}"
    with pg_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))

    original_url = make_url(os.environ["SCRUM15_TEST_DATABASE_URL"])
    schema_url = original_url.set(query={**original_url.query, "options": f"-csearch_path={schema}"})
    scratch_engine = create_engine(schema_url, pool_pre_ping=True)
    alembic = Path(__file__).parents[1] / ".venv" / "bin" / "alembic"
    if not alembic.exists():
        pytest.fail(f"Alembic executable not found in project uv environment: {alembic}")

    def migrate(*args, should_pass=True):
        env = dict(os.environ, DATABASE_URL=str(schema_url))
        result = subprocess.run(
            [str(alembic), *args], cwd=Path(__file__).parents[1], env=env,
            capture_output=True, text=True, timeout=60,
        )
        output = result.stdout + result.stderr
        if should_pass:
            assert result.returncode == 0, output
        else:
            assert result.returncode != 0, output
        return output

    try:
        migrate("upgrade", "0003_case_attachment_consistency")
        with scratch_engine.begin() as connection:
            supplier_id, dc_id, po_id, line_a_id, line_b_id = [uuid.uuid4() for _ in range(5)]
            fine_a_id, fine_b_id, dispute_id, dispute_line_id = [uuid.uuid4() for _ in range(4)]
            case_a_id, case_b_id, finding_id, line_outcome_id, approval_id = [uuid.uuid4() for _ in range(5)]
            connection.execute(text("INSERT INTO suppliers (id,supplier_code,name) VALUES (:id,:code,'Supplier')"), {"id": supplier_id, "code": str(supplier_id)})
            connection.execute(text("INSERT INTO distribution_centers (id,dc_code,name) VALUES (:id,:code,'DC')"), {"id": dc_id, "code": str(dc_id)})
            connection.execute(text("INSERT INTO purchase_orders (id,po_number,supplier_id,distribution_center_id) VALUES (:id,:number,:supplier,:dc)"), {"id": po_id,"number": str(po_id),"supplier": supplier_id,"dc": dc_id})
            connection.execute(text("INSERT INTO po_lines (id,purchase_order_id,line_number) VALUES (:a,:po,1),(:b,:po,2)"), {"a": line_a_id,"b": line_b_id,"po": po_id})
            connection.execute(text("INSERT INTO fine_records (id,po_line_id,po_version_used,ordered_cases,received_cases,non_compliant_cases,system_accountability,original_amount,case_cost_snapshot,fine_rate) VALUES (:a,:la,1,10,8,2,'supplier',20,10,.03),(:b,:lb,1,10,9,1,'supplier',10,10,.03)"), {"a": fine_a_id,"la": line_a_id,"b": fine_b_id,"lb": line_b_id})
            connection.execute(text("INSERT INTO disputes (id,supplier_id,submitted_at) VALUES (:id,:supplier,now())"), {"id": dispute_id,"supplier": supplier_id})
            connection.execute(text("INSERT INTO dispute_lines (id,dispute_id,fine_record_id) VALUES (:id,:dispute,:fine)"), {"id": dispute_line_id,"dispute": dispute_id,"fine": fine_a_id})
            connection.execute(text("INSERT INTO investigation_cases (id,fine_record_id,dispute_line_id,origin,status) VALUES (:a,:fa,:dl,'supplier_dispute','investigating'),(:b,:fb,NULL,'pre_invoice_scan','pending')"), {"a": case_a_id,"fa": fine_a_id,"dl": dispute_line_id,"b": case_b_id,"fb": fine_b_id})
            connection.execute(text("UPDATE investigation_cases SET scan_rule='R2' WHERE id=:id"), {"id": case_b_id})
            connection.execute(text("INSERT INTO investigation_findings (id,investigation_case_id,cause_code,summary) VALUES (:id,:case,'C1','legacy finding')"), {"id": finding_id,"case": case_a_id})
            connection.execute(text("INSERT INTO line_outcomes (id,finding_id,outcome,corrected_amount,rationale,policy_version,accountable_party,original_amount,calculated_at) VALUES (:id,:finding,'partial',12,'legacy outcome','0.1','supplier',20,now())"), {"id": line_outcome_id,"finding": finding_id})
            connection.execute(text("INSERT INTO approvals (id,line_outcome_id,approval_type,status) VALUES (:id,:line,'associate','pending')"), {"id": approval_id,"line": line_outcome_id})

        # Legacy records are preserved and enriched by 0004 without recalculation.
        migrate("upgrade", "head")
        with scratch_engine.connect() as connection:
            assert connection.scalar(text("SELECT version_number FROM investigation_findings WHERE id=:id"), {"id": finding_id}) == 1
            assert connection.scalar(text("SELECT count(*) FROM dispute_line_cases WHERE dispute_line_id=:id AND investigation_case_id=:case"), {"id": dispute_line_id,"case": case_a_id}) == 1
            trigger = connection.execute(text("SELECT trigger_rule,scan_id FROM investigation_case_triggers WHERE investigation_case_id=:id"), {"id": case_b_id}).one()
            assert trigger == ("R2", "legacy-unknown")
            evaluation = connection.execute(text("SELECT result->>'legacy_snapshot',policy_version,finding_id FROM evaluations WHERE investigation_case_id=:case"), {"case": case_a_id}).one()
            assert evaluation == ("true", "0.1", finding_id)
            outcome = connection.execute(text("SELECT status FROM case_outcomes WHERE evaluation_id IN (SELECT id FROM evaluations WHERE investigation_case_id=:case)"), {"case": case_a_id}).scalar_one()
            assert outcome == "pending_approval"
            assert connection.scalar(text("SELECT calculated_at IS NOT NULL AND corrected_amount=12 FROM line_outcomes WHERE id=:id"), {"id": line_outcome_id}) is True

        # Only legacy snapshots exist, so downgrade must preserve original rows.
        migrate("downgrade", "0003_case_attachment_consistency")
        with scratch_engine.begin() as connection:
            assert connection.scalar(text("SELECT corrected_amount FROM line_outcomes WHERE id=:id"), {"id": line_outcome_id}) == 12
            assert connection.scalar(text("SELECT count(*) FROM investigation_findings WHERE id=:id"), {"id": finding_id}) == 1

            # Verify 0004 preflight failures leave 0003 intact and are repairable.
            connection.execute(text("UPDATE investigation_cases SET status='unsupported' WHERE id=:id"), {"id": case_a_id})
        out = migrate("upgrade", "head", should_pass=False)
        assert "null or unsupported legacy statuses" in out
        with scratch_engine.begin() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0003_case_attachment_consistency"
            connection.execute(text("UPDATE investigation_cases SET status='investigating' WHERE id=:id"), {"id": case_a_id})
            connection.execute(text("INSERT INTO investigation_cases (id,fine_record_id,origin,status) VALUES (:id,:fine,'pre_invoice_scan','investigating')"), {"id": uuid.uuid4(),"fine": fine_a_id})
        out = migrate("upgrade", "head", should_pass=False)
        assert "multiple active cases exist" in out
        with scratch_engine.begin() as connection:
            connection.execute(text("DELETE FROM investigation_cases WHERE fine_record_id=:fine AND id<>:keep"), {"fine": fine_a_id,"keep": case_a_id})
            connection.execute(text("UPDATE approvals SET status='unsupported' WHERE id=:id"), {"id": approval_id})
        out = migrate("upgrade", "head", should_pass=False)
        assert "unsupported legacy status" in out
        with scratch_engine.begin() as connection:
            connection.execute(text("UPDATE approvals SET status='pending' WHERE id=:id"), {"id": approval_id})
        migrate("upgrade", "head")
    finally:
        scratch_engine.dispose()
        with pg_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
