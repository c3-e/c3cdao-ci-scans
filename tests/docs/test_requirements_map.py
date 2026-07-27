"""DOC-3 acceptance tests for docs/RUNBOOK.md and docs/REQUIREMENTS-MAP.md.

The drift guard (test_every_job_mapped) parses the job ids out of the reusable
workflow and asserts each has a row in the requirements map, so a new gate job
can't ship unmapped.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNBOOK = REPO_ROOT / "docs" / "RUNBOOK.md"
REQ_MAP = REPO_ROOT / "docs" / "REQUIREMENTS-MAP.md"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "reusable-security-gate.yml"
LINT = REPO_ROOT / "scripts" / "lib" / "lint_caller.py"

# Job ids are the only keys at exactly two-space indent after the `jobs:` line;
# deeper keys (name/runs-on/steps) are indented 4+, so `^  [a-z0-9-]+:` matches
# ids only. Top-level blocks before `jobs:` (permissions/concurrency) also have
# two-space lowercase children, hence the scoping to after the `jobs:` line.
JOB_ID_RE = re.compile(r"^  ([a-z0-9-]+):")


def workflow_job_ids():
    lines = WORKFLOW.read_text().splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.rstrip() == "jobs:")
    return [
        m.group(1)
        for ln in lines[start + 1 :]
        if (m := JOB_ID_RE.match(ln))
    ]


def test_files_exist():
    assert RUNBOOK.is_file() and RUNBOOK.stat().st_size > 0
    assert REQ_MAP.is_file() and REQ_MAP.stat().st_size > 0


def test_every_job_mapped():
    job_ids = workflow_job_ids()
    assert len(job_ids) == 9, f"expected 9 jobs, parsed {job_ids}"
    text = REQ_MAP.read_text()
    missing = [j for j in job_ids if j not in text]
    assert not missing, f"jobs missing from REQUIREMENTS-MAP.md: {missing}"


def test_links_both_pages():
    text = REQ_MAP.read_text()
    assert "10839163045" in text
    assert "10910040079" in text


def test_blocking_flip_is_final():
    text = REQ_MAP.read_text()
    assert "SECURITY_SCAN_BLOCKING" in text
    assert re.search(r"final|last|steady-state", text, re.IGNORECASE)


def test_manifest_extras_credited():
    text = REQ_MAP.read_text()
    assert re.search(r"manifest extras", text, re.IGNORECASE)
    assert re.search(r"frontend", text, re.IGNORECASE)


def test_out_of_scope_named():
    text = REQ_MAP.read_text()
    assert re.search(r"GHCR|publish", text, re.IGNORECASE)
    assert re.search(r"harden|bootstrap", text, re.IGNORECASE)


def test_runbook_covers_ruleset_and_promote():
    text = RUNBOOK.read_text()
    assert "setup-ruleset.sh" in text
    assert re.search(r"promote", text, re.IGNORECASE)


def lint_rule_ids():
    """Rule ids from lint_caller.py's maintained 'Rule ids:' docstring block."""
    m = re.search(r"Rule ids:(.*?)\.", LINT.read_text(), re.DOTALL)
    assert m, "lint_caller.py docstring has no 'Rule ids:' enumeration"
    return re.findall(r"[a-z]+(?:-[a-z]+)+", m.group(1))


def test_all_lint_rules_documented():
    rules = lint_rule_ids()
    assert len(rules) == 15, f"expected 15 lint rule ids, parsed {rules}"
    text = RUNBOOK.read_text()
    missing = [r for r in rules if r not in text]
    assert not missing, f"lint rules missing from RUNBOOK.md: {missing}"
