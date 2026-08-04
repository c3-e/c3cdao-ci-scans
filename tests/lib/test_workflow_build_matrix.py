"""Contract tests for the v0.6 plan -> build matrix workflow shape (T-5).

Static drift guards on .github/workflows/reusable-security-gate.yml: the
plan job publishes the matrix the build job fans out over, every leg
carries the gate-owned --set overrides, artifacts are named by target,
and the new action pins are full commit SHAs. T-6/T-7 modify the same
file; these assertions keep the T-5 surface from regressing.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/reusable-security-gate.yml"

FULL_SHA_USES = re.compile(r"@[0-9a-f]{40}$")
SET_OVERRIDES = (
    "*.platform=linux/amd64",
    "*.args.BUILDER_IMAGE=",
    "*.args.RUNTIME_IMAGE=",
)


def _jobs() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())["jobs"]


def _steps_text(job: dict) -> str:
    return "\n".join(
        str(step.get(key, ""))
        for step in job["steps"]
        for key in ("run", "with", "uses")
    )


def test_caller_lint_renamed_to_plan():
    jobs = _jobs()
    assert "caller-lint" not in jobs
    assert "plan" in jobs


def test_plan_outputs_matrix_and_bridge_outputs():
    outputs = _jobs()["plan"]["outputs"]
    # T-6 retired the containers/has_extras/chart bridges; health stays
    # until T-7 rewires cluster-smoke.
    for key in ("matrix", "source_sbom_target", "health"):
        assert key in outputs, f"plan must declare output '{key}'"


def test_plan_wires_lint_and_derive_with_gate_overrides():
    text = _steps_text(_jobs()["plan"])
    assert "lint_caller.py" in text
    assert "derive_bom.py" in text
    assert "--set" in text
    assert "*.args.BUILDER_IMAGE=" in text
    assert "*.args.RUNTIME_IMAGE=" in text


def test_build_is_matrix_over_plan_output():
    build = _jobs()["build"]
    assert build["needs"] == ["plan"]
    strategy = build["strategy"]
    assert strategy["fail-fast"] is False
    include = strategy["matrix"]["include"]
    assert include == "${{ fromJSON(needs.plan.outputs.matrix) }}"


def test_build_leg_runs_bake_with_identical_overrides():
    build = _jobs()["build"]
    bake_steps = [
        s for s in build["steps"] if "docker/bake-action@" in str(s.get("uses", ""))
    ]
    assert len(bake_steps) == 1, "one bake-action execution step per leg"
    with_map = bake_steps[0]["with"]
    assert "${{ matrix.target }}" in str(with_map["targets"])
    for override in SET_OVERRIDES:
        assert override in str(with_map["set"]), f"missing --set {override!r}"


def test_build_leg_checks_plan_execution_parity():
    text = _steps_text(_jobs()["build"])
    assert "--print" in text, "leg must re-print its target for the parity diff"
    assert "jq -S" in text
    assert "bake-plan.json" in text


def test_build_artifacts_named_by_target():
    text = _steps_text(_jobs()["build"])
    assert "scan-image-${{ matrix.target }}" in text
    assert "sbom-image-${{ matrix.target }}" in text


def test_build_keeps_registry_failover_and_syft():
    text = _steps_text(_jobs()["build"])
    assert "hardened-registry-login" in text
    assert "anchore/sbom-action@" in text
    assert "docker save" in text


def test_plan_and_build_remote_actions_pinned_by_full_sha():
    jobs = _jobs()
    for job_id in ("plan", "build"):
        for step in jobs[job_id]["steps"]:
            uses = str(step.get("uses", ""))
            if not uses or uses.startswith("./"):
                continue
            assert FULL_SHA_USES.search(uses), f"{job_id}: '{uses}' not SHA-pinned"


def test_downstream_jobs_reference_plan_not_caller_lint():
    text = WORKFLOW.read_text()
    assert "caller-lint" not in text
    assert "needs.caller-lint" not in text
