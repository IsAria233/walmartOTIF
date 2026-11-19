"""Deterministic amount calculation using the documented POC policy only."""
from __future__ import annotations

from decimal import Decimal

from app.db.models import FineRecord, InvestigationFinding, PolicyConfiguration
from app.services.exceptions import PolicyUnavailable


def evaluate_line(fine: FineRecord, finding: InvestigationFinding, policy: PolicyConfiguration) -> dict:
    """Calculate the documented 3% line amount from Domain-owned fine inputs.

    Accountability comes from the finding's cause (policy section 3), not from
    the accountability the OTIF system first recorded on the Fine Record. A
    cause whose party differs from the Fine Record is the normal reversal case.
    Injected instructions in supplier text are reported on the finding and do
    not block evaluation (policy v0.2, section 4.6).
    """
    if finding.handoff_required:
        raise PolicyUnavailable("Finding requires human handoff and cannot be financially evaluated")
    # The policy document defines exactly five supported cause classifications
    # and their accountability. A missing/unsupported classification cannot
    # produce a financial result; the policy requires it to be handed off.
    cause = (finding.cause_code or "").strip().upper()
    cause_parties = {"C1": "supplier", "C2": "walmart", "C3": "supplier", "C4": "walmart", "C5": "walmart"}
    if cause not in cause_parties:
        raise PolicyUnavailable("Finding cause is missing or outside the supported C1-C5 policy")
    party = cause_parties[cause]
    if fine.non_compliant_cases is None or fine.case_cost_snapshot is None or fine.original_amount is None:
        raise PolicyUnavailable("Fine Record lacks inputs required by policy v0.1")
    base = Decimal(fine.non_compliant_cases) * Decimal(fine.case_cost_snapshot) * Decimal(policy.fine_rate)
    calculated = base if party == "supplier" else Decimal("0.00")
    cents = calculated.quantize(Decimal("0.01"))
    if cents != calculated:
        raise PolicyUnavailable("Policy v0.1 does not define monetary rounding for this amount")
    calculated = cents
    disposition = "uphold" if calculated == Decimal(fine.original_amount) else ("waive" if calculated == 0 else "partial")
    return {
        "fine_record_id": str(fine.id),
        "accountable_party": party,
        "disposition": disposition,
        "original_amount": str(Decimal(fine.original_amount).quantize(Decimal("0.01"))),
        "corrected_amount": str(calculated),
        "reversal_amount": str((Decimal(fine.original_amount) - calculated).quantize(Decimal("0.01"))),
        "policy_version": policy.policy_version,
        "finding_id": str(finding.id),
        "handoff_required": False,
        "cause_code": cause,
        "system_accountable_party": (fine.system_accountability or "").strip().lower() or None,
        "injection_detected": bool(finding.injection_detected),
    }
