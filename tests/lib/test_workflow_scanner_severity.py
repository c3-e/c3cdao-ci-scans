"""Pins the workflow-level scanner severity export config in
reusable-security-gate.yml against silent narrowing back to High/Critical.
"""

from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/reusable-security-gate.yml"


def test_trivy_severity_exports_the_full_spectrum():
    env = yaml.safe_load(WORKFLOW.read_text())["env"]
    assert set(env["TRIVY_SEVERITY"].split(",")) == {
        "CRITICAL",
        "HIGH",
        "MEDIUM",
        "LOW",
        "UNKNOWN",
    }
