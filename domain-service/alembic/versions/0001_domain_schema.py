"""Initial Domain Service schema.

Revision ID: 0001_domain_schema
Revises:
"""
from alembic import op

revision = "0001_domain_schema"
down_revision = None
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.execute("""
CREATE TABLE asns (
	id UUID NOT NULL,
	asn_number VARCHAR(100) NOT NULL,
	ship_ts TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (asn_number)
)

""")

    op.execute("""CREATE INDEX ix_asns_ship_ts ON asns (ship_ts)""")

    op.execute("""
CREATE TABLE deliveries (
	id UUID NOT NULL,
	delivery_number VARCHAR(100),
	carrier VARCHAR(255),
	trailer_number VARCHAR(100),
	actual_arrival_ts TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (delivery_number)
)

""")

    op.execute("""CREATE INDEX ix_deliveries_arrival ON deliveries (actual_arrival_ts)""")

    op.execute("""
CREATE TABLE disputes (
	id UUID NOT NULL,
	external_dispute_id VARCHAR(150),
	submitted_at TIMESTAMP WITH TIME ZONE NOT NULL,
	reason_category VARCHAR(150),
	reason_text TEXT,
	amount_disputed NUMERIC(14, 2),
	status VARCHAR(50),
	PRIMARY KEY (id),
	UNIQUE (external_dispute_id)
)

""")

    op.execute("""CREATE INDEX ix_disputes_submitted_at ON disputes (submitted_at)""")

    op.execute("""
CREATE TABLE distribution_centers (
	id UUID NOT NULL,
	dc_code VARCHAR(100) NOT NULL,
	name VARCHAR(255) NOT NULL,
	timezone VARCHAR(64),
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (dc_code)
)

""")

    op.execute("""
CREATE TABLE evidence_records (
	id UUID NOT NULL,
	evidence_type VARCHAR(100) NOT NULL,
	external_id VARCHAR(200),
	snapshot JSONB NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id)
)

""")

    op.execute("""CREATE INDEX ix_evidence_records_kind_created ON evidence_records (evidence_type, created_at)""")

    op.execute("""
CREATE TABLE suppliers (
	id UUID NOT NULL,
	supplier_code VARCHAR(100) NOT NULL,
	name VARCHAR(255) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (supplier_code)
)

""")

    op.execute("""
CREATE TABLE attachments (
	id UUID NOT NULL,
	dispute_id UUID NOT NULL,
	external_attachment_id VARCHAR(150),
	attachment_type VARCHAR(100),
	filename VARCHAR(500),
	uri TEXT,
	metadata_json JSONB,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(dispute_id) REFERENCES disputes (id) ON DELETE CASCADE
)

""")

    op.execute("""
CREATE TABLE gate_logs (
	id UUID NOT NULL,
	delivery_id UUID NOT NULL,
	check_in_ts TIMESTAMP WITH TIME ZONE NOT NULL,
	gate_identifier VARCHAR(100),
	note TEXT,
	PRIMARY KEY (id),
	FOREIGN KEY(delivery_id) REFERENCES deliveries (id) ON DELETE CASCADE
)

""")

    op.execute("""CREATE INDEX ix_gate_logs_delivery_checkin ON gate_logs (delivery_id, check_in_ts)""")

    op.execute("""
CREATE TABLE purchase_orders (
	id UUID NOT NULL,
	po_number VARCHAR(100) NOT NULL,
	supplier_id UUID NOT NULL,
	distribution_center_id UUID NOT NULL,
	status VARCHAR(50),
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (po_number),
	FOREIGN KEY(supplier_id) REFERENCES suppliers (id) ON DELETE RESTRICT,
	FOREIGN KEY(distribution_center_id) REFERENCES distribution_centers (id) ON DELETE RESTRICT
)

""")

    op.execute("""CREATE INDEX ix_purchase_orders_supplier_dc ON purchase_orders (supplier_id, distribution_center_id)""")

    op.execute("""
CREATE TABLE weather_alerts (
	id UUID NOT NULL,
	distribution_center_id UUID NOT NULL,
	external_alert_id VARCHAR(150),
	alert_date DATE NOT NULL,
	area VARCHAR(255),
	alert_type VARCHAR(255) NOT NULL,
	details JSONB,
	PRIMARY KEY (id),
	FOREIGN KEY(distribution_center_id) REFERENCES distribution_centers (id) ON DELETE CASCADE
)

""")

    op.execute("""CREATE INDEX ix_weather_alerts_dc_date ON weather_alerts (distribution_center_id, alert_date)""")

    op.execute("""
CREATE TABLE po_lines (
	id UUID NOT NULL,
	purchase_order_id UUID NOT NULL,
	line_number INTEGER NOT NULL,
	item_number VARCHAR(100),
	item_description VARCHAR(500),
	mabd DATE,
	standard_transit_days INTEGER,
	case_cost NUMERIC(14, 4),
	freight_terms VARCHAR(50),
	channel VARCHAR(50),
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_po_lines_order_line UNIQUE (purchase_order_id, line_number),
	CONSTRAINT ck_po_lines_line_positive CHECK (line_number > 0),
	FOREIGN KEY(purchase_order_id) REFERENCES purchase_orders (id) ON DELETE CASCADE
)

""")

    op.execute("""
CREATE TABLE appointment_events (
	id UUID NOT NULL,
	po_line_id UUID NOT NULL,
	event_ts TIMESTAMP WITH TIME ZONE NOT NULL,
	action VARCHAR(50) NOT NULL,
	initiated_by VARCHAR(50),
	appointment_ts TIMESTAMP WITH TIME ZONE,
	note TEXT,
	PRIMARY KEY (id),
	FOREIGN KEY(po_line_id) REFERENCES po_lines (id) ON DELETE CASCADE
)

""")

    op.execute("""CREATE INDEX ix_appointment_events_po_line_ts ON appointment_events (po_line_id, event_ts)""")

    op.execute("""
CREATE TABLE asn_lines (
	id UUID NOT NULL,
	asn_id UUID NOT NULL,
	po_line_id UUID NOT NULL,
	shipped_cases INTEGER NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_asn_lines_shipped_nonnegative CHECK (shipped_cases >= 0),
	FOREIGN KEY(asn_id) REFERENCES asns (id) ON DELETE CASCADE,
	FOREIGN KEY(po_line_id) REFERENCES po_lines (id) ON DELETE RESTRICT
)

""")

    op.execute("""CREATE INDEX ix_asn_lines_po_line ON asn_lines (po_line_id)""")

    op.execute("""
CREATE TABLE po_line_versions (
	id UUID NOT NULL,
	po_line_id UUID NOT NULL,
	version_number INTEGER NOT NULL,
	ordered_cases INTEGER NOT NULL,
	issued_at TIMESTAMP WITH TIME ZONE NOT NULL,
	issued_by VARCHAR(255),
	note TEXT,
	PRIMARY KEY (id),
	CONSTRAINT uq_po_line_versions_number UNIQUE (po_line_id, version_number),
	CONSTRAINT uq_po_line_versions_id_po_line UNIQUE (id, po_line_id),
	CONSTRAINT ck_po_line_versions_positive CHECK (version_number > 0),
	CONSTRAINT ck_po_line_versions_ordered_nonnegative CHECK (ordered_cases >= 0),
	FOREIGN KEY(po_line_id) REFERENCES po_lines (id) ON DELETE CASCADE
)

""")

    op.execute("""CREATE INDEX ix_po_line_versions_effective ON po_line_versions (po_line_id, issued_at)""")

    op.execute("""
CREATE TABLE delivery_lines (
	id UUID NOT NULL,
	asn_line_id UUID NOT NULL,
	delivery_id UUID NOT NULL,
	allocated_cases INTEGER NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_delivery_lines_allocated_positive CHECK (allocated_cases > 0),
	CONSTRAINT uq_delivery_lines_asn_delivery UNIQUE (asn_line_id, delivery_id),
	FOREIGN KEY(asn_line_id) REFERENCES asn_lines (id) ON DELETE RESTRICT,
	FOREIGN KEY(delivery_id) REFERENCES deliveries (id) ON DELETE CASCADE
)

""")

    op.execute("""CREATE INDEX ix_delivery_lines_delivery ON delivery_lines (delivery_id)""")

    op.execute("""
CREATE TABLE fine_records (
	id UUID NOT NULL,
	external_fine_id VARCHAR(150),
	po_line_id UUID NOT NULL,
	po_line_version_id UUID,
	po_version_used INTEGER NOT NULL,
	ordered_cases INTEGER NOT NULL,
	received_cases INTEGER NOT NULL,
	non_compliant_cases INTEGER NOT NULL,
	system_accountability VARCHAR(50) NOT NULL,
	metric VARCHAR(50),
	original_amount NUMERIC(14, 2) NOT NULL,
	case_cost_snapshot NUMERIC(14, 4) NOT NULL,
	fine_rate NUMERIC(9, 6) NOT NULL,
	recorded_arrival_ts TIMESTAMP WITH TIME ZONE,
	status VARCHAR(50),
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_fine_records_ordered_nonnegative CHECK (ordered_cases >= 0),
	CONSTRAINT ck_fine_records_received_nonnegative CHECK (received_cases >= 0),
	CONSTRAINT ck_fine_records_noncompliant_nonnegative CHECK (non_compliant_cases >= 0),
	CONSTRAINT ck_fine_records_amount_nonnegative CHECK (original_amount >= 0),
	CONSTRAINT ck_fine_records_case_cost_nonnegative CHECK (case_cost_snapshot >= 0),
	CONSTRAINT ck_fine_records_rate_nonnegative CHECK (fine_rate >= 0),
	CONSTRAINT fk_fine_records_version_matches_line FOREIGN KEY(po_line_version_id, po_line_id) REFERENCES po_line_versions (id, po_line_id) ON DELETE RESTRICT,
	UNIQUE (external_fine_id),
	FOREIGN KEY(po_line_id) REFERENCES po_lines (id) ON DELETE RESTRICT
)

""")

    op.execute("""CREATE INDEX ix_fine_records_po_line_created ON fine_records (po_line_id, created_at)""")

    op.execute("""
CREATE TABLE dispute_lines (
	id UUID NOT NULL,
	dispute_id UUID NOT NULL,
	fine_record_id UUID NOT NULL,
	amount_disputed NUMERIC(14, 2),
	PRIMARY KEY (id),
	CONSTRAINT uq_dispute_lines_fine UNIQUE (dispute_id, fine_record_id),
	FOREIGN KEY(dispute_id) REFERENCES disputes (id) ON DELETE CASCADE,
	FOREIGN KEY(fine_record_id) REFERENCES fine_records (id) ON DELETE RESTRICT
)

""")

    op.execute("""CREATE INDEX ix_dispute_lines_fine ON dispute_lines (fine_record_id)""")

    op.execute("""
CREATE TABLE receiving_records (
	id UUID NOT NULL,
	delivery_line_id UUID NOT NULL,
	received_at TIMESTAMP WITH TIME ZONE NOT NULL,
	received_cases INTEGER NOT NULL,
	exception_code VARCHAR(100),
	note TEXT,
	PRIMARY KEY (id),
	CONSTRAINT ck_receiving_records_cases_nonnegative CHECK (received_cases >= 0),
	FOREIGN KEY(delivery_line_id) REFERENCES delivery_lines (id) ON DELETE CASCADE
)

""")

    op.execute("""CREATE INDEX ix_receiving_records_delivery_line_received ON receiving_records (delivery_line_id, received_at)""")

    op.execute("""
CREATE TABLE investigation_cases (
	id UUID NOT NULL,
	fine_record_id UUID NOT NULL,
	dispute_line_id UUID,
	origin VARCHAR(50) NOT NULL,
	agent_run_id UUID,
	status VARCHAR(50),
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_investigation_cases_origin CHECK (origin IN ('supplier_dispute', 'pre_invoice_scan')),
	FOREIGN KEY(fine_record_id) REFERENCES fine_records (id) ON DELETE RESTRICT,
	FOREIGN KEY(dispute_line_id) REFERENCES dispute_lines (id) ON DELETE SET NULL
)

""")

    op.execute("""CREATE INDEX ix_investigation_cases_fine_created ON investigation_cases (fine_record_id, created_at)""")

    op.execute("""
CREATE TABLE investigation_findings (
	id UUID NOT NULL,
	investigation_case_id UUID NOT NULL,
	cause_code VARCHAR(50),
	summary TEXT,
	confidence NUMERIC(5, 4),
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(investigation_case_id) REFERENCES investigation_cases (id) ON DELETE CASCADE
)

""")

    op.execute("""CREATE INDEX ix_investigation_findings_case_created ON investigation_findings (investigation_case_id, created_at)""")

    op.execute("""
CREATE TABLE finding_facts (
	id UUID NOT NULL,
	finding_id UUID NOT NULL,
	fact_key VARCHAR(150) NOT NULL,
	fact_value TEXT,
	source_description TEXT,
	PRIMARY KEY (id),
	FOREIGN KEY(finding_id) REFERENCES investigation_findings (id) ON DELETE CASCADE
)

""")

    op.execute("""
CREATE TABLE line_outcomes (
	id UUID NOT NULL,
	finding_id UUID NOT NULL,
	outcome VARCHAR(30) NOT NULL,
	corrected_amount NUMERIC(14, 2) NOT NULL,
	rationale TEXT,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_line_outcomes_finding UNIQUE (finding_id),
	CONSTRAINT ck_line_outcomes_outcome CHECK (outcome IN ('uphold', 'waive', 'partial')),
	CONSTRAINT ck_line_outcomes_amount_nonnegative CHECK (corrected_amount >= 0),
	FOREIGN KEY(finding_id) REFERENCES investigation_findings (id) ON DELETE RESTRICT
)

""")

    op.execute("""
CREATE TABLE approvals (
	id UUID NOT NULL,
	line_outcome_id UUID NOT NULL,
	approval_type VARCHAR(50) NOT NULL,
	status VARCHAR(50) DEFAULT 'pending' NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(line_outcome_id) REFERENCES line_outcomes (id) ON DELETE CASCADE
)

""")

    op.execute("""CREATE INDEX ix_approvals_outcome_status ON approvals (line_outcome_id, status)""")

    op.execute("""
CREATE TABLE evidence_links (
	id UUID NOT NULL,
	finding_fact_id UUID NOT NULL,
	evidence_record_id UUID NOT NULL,
	role VARCHAR(30) NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_evidence_links_fact_evidence_role UNIQUE (finding_fact_id, evidence_record_id, role),
	CONSTRAINT ck_evidence_links_role CHECK (role IN ('supports', 'contradicts', 'context')),
	FOREIGN KEY(finding_fact_id) REFERENCES finding_facts (id) ON DELETE CASCADE,
	FOREIGN KEY(evidence_record_id) REFERENCES evidence_records (id) ON DELETE RESTRICT
)

""")

    op.execute("""CREATE INDEX ix_evidence_links_evidence ON evidence_links (evidence_record_id)""")

    op.execute("""
CREATE TABLE approval_decisions (
	id UUID NOT NULL,
	approval_id UUID NOT NULL,
	auth_user_id UUID NOT NULL,
	decision VARCHAR(30) NOT NULL,
	decided_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	comment TEXT,
	PRIMARY KEY (id),
	CONSTRAINT ck_approval_decisions_decision CHECK (decision IN ('approved', 'rejected')),
	FOREIGN KEY(approval_id) REFERENCES approvals (id) ON DELETE CASCADE
)

""")

    op.execute("""CREATE INDEX ix_approval_decisions_approval_time ON approval_decisions (approval_id, decided_at)""")

def downgrade() -> None:
    op.execute("DROP TABLE approval_decisions CASCADE")
    op.execute("DROP TABLE evidence_links CASCADE")
    op.execute("DROP TABLE approvals CASCADE")
    op.execute("DROP TABLE line_outcomes CASCADE")
    op.execute("DROP TABLE finding_facts CASCADE")
    op.execute("DROP TABLE investigation_findings CASCADE")
    op.execute("DROP TABLE investigation_cases CASCADE")
    op.execute("DROP TABLE receiving_records CASCADE")
    op.execute("DROP TABLE dispute_lines CASCADE")
    op.execute("DROP TABLE fine_records CASCADE")
    op.execute("DROP TABLE delivery_lines CASCADE")
    op.execute("DROP TABLE po_line_versions CASCADE")
    op.execute("DROP TABLE asn_lines CASCADE")
    op.execute("DROP TABLE appointment_events CASCADE")
    op.execute("DROP TABLE po_lines CASCADE")
    op.execute("DROP TABLE weather_alerts CASCADE")
    op.execute("DROP TABLE purchase_orders CASCADE")
    op.execute("DROP TABLE gate_logs CASCADE")
    op.execute("DROP TABLE attachments CASCADE")
    op.execute("DROP TABLE suppliers CASCADE")
    op.execute("DROP TABLE evidence_records CASCADE")
    op.execute("DROP TABLE distribution_centers CASCADE")
    op.execute("DROP TABLE disputes CASCADE")
    op.execute("DROP TABLE deliveries CASCADE")
    op.execute("DROP TABLE asns CASCADE")
