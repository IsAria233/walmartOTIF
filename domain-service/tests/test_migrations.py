import ast
from pathlib import Path


def revision_values(path: Path):
    tree = ast.parse(path.read_text())
    values = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in {"revision", "down_revision"}:
                    values[target.id] = ast.literal_eval(node.value)
    return values


def test_revision_chain_and_scrum15_migration_safety_guards():
    versions = Path(__file__).parents[1] / "alembic" / "versions"
    revisions = {
        revision_values(path).get("revision"): revision_values(path).get("down_revision")
        for path in versions.glob("*.py")
    }
    assert revisions["0001_domain_schema"] is None
    assert revisions["0002_review_revisions"] == "0001_domain_schema"
    assert revisions["0003_case_attachment_consistency"] == "0002_review_revisions"
    assert revisions["0004_scrum15_domain_workflows"] == "0003_case_attachment_consistency"
    assert revisions["0005_review_fixes"] == "0004_scrum15_domain_workflows"

    migration = (versions / "0004_scrum15_domain_workflows.py").read_text()
    assert "null or unsupported legacy statuses" in migration
    assert "multiple active cases exist" in migration
    assert "legacy-unknown" in migration
    assert "row_number() OVER" in migration
    assert "legacy-snapshot Evaluation" in migration or "legacy_snapshot" in migration
    assert "non-legacy Evaluations would lose audit data" in migration
