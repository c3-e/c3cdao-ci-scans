"""Unit tests for the gate-job-id caller-structure lint rule (v0.6 API).

Ported from the pre-cutover footgun-enforcement work (main) at the v0.6
reconciliation merge: the rule survives the cutover, the v0.5 contract
API (`load_contract`/`lint`) does not.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

from lint_caller import lint_caller_workflow  # noqa: E402

FIXTURES = REPO_ROOT / "tests" / "fixtures" / "callers"


def _rule_ids(path: Path) -> list[str]:
    return [v["rule_id"] for v in lint_caller_workflow(path)]


def test_wrong_job_id_fires():
    verdicts = lint_caller_workflow(FIXTURES / "bad-job-id.yml")
    hits = [v for v in verdicts if v["rule_id"] == "gate-job-id"]
    assert hits, f"gate-job-id did not fire; got {_rule_ids(FIXTURES / 'bad-job-id.yml')}"
    assert "sec-gate" in hits[0]["message"]
    assert hits[0]["level"] == "block"


def test_security_scan_id_clean():
    assert "gate-job-id" not in _rule_ids(FIXTURES / "clean-minimal.yml")


if __name__ == "__main__":
    raise SystemExit(pytest.main(["-q", __file__]))
