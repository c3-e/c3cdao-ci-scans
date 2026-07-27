"""Unit tests for the gate-job-id lint rule."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

from lint_caller import lint, load_contract  # noqa: E402

CONTRACT = REPO_ROOT / "contract" / "security-gate.schema.json"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "callers"


def test_wrong_job_id_fires():
    props = load_contract(CONTRACT)
    violations = lint(FIXTURES / "bad-job-id.yml", props, None)
    assert any(
        v.startswith("gate-job-id: gate job id is 'sec-gate'") for v in violations
    )


def test_security_scan_id_clean():
    props = load_contract(CONTRACT)
    violations = lint(FIXTURES / "clean-minimal.yml", props, None)
    assert not any(v.startswith("gate-job-id:") for v in violations)


if __name__ == "__main__":
    raise SystemExit(pytest.main(["-q", __file__]))
