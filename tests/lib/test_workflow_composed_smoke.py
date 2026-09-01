"""Static drift guards for composed-smoke.yml's helm test hook partitioning.

TEMPORARY migration scaffolding (see reusable-security-gate.yml's own
hook-detect step and scripts/lib/lint_rules/chart.py's smoke_target rule):
this run partitions its pilots by whether each pilot's own rendered
subchart carries a `helm.sh/hook: test` resource. Hook-bearing pilots are
covered by one release-wide `helm test umbrella-ci` run; hook-less pilots
keep the pre-migration per-target port-forward+curl loop untouched.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/composed-smoke.yml"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def _compose_smoke() -> dict:
    return _workflow()["jobs"]["compose-smoke"]


def _steps() -> list[dict]:
    return _compose_smoke()["steps"]


def _step(step_id: str) -> dict:
    return next(s for s in _steps() if s.get("id") == step_id)


def _run_text() -> str:
    return "\n".join(str(s.get("run", "")) for s in _steps())


def test_partition_step_exists_before_health_check():
    ids = [s.get("id") for s in _steps()]
    assert "partition" in ids
    assert "helm-test" in ids
    assert "health" in ids
    assert ids.index("partition") < ids.index("health")
    assert ids.index("helm-test") < ids.index("health")


def test_partition_step_checks_hook_annotation_per_pilot():
    text = str(_step("partition").get("run", ""))
    assert "helm" in text and "hook" in text and "test" in text
    assert "hook-pilots.txt" in text
    assert "nohook-pilots.txt" in text


def test_helm_test_step_runs_once_release_wide_with_logs():
    text = str(_step("helm-test").get("run", ""))
    assert "helm test umbrella-ci" in text
    assert "--logs" in text
    # Skips gracefully (no error) when there are no hook-bearing pilots.
    assert "hook-pilots.txt" in text


def test_health_check_skips_hook_bearing_pilots():
    text = str(_step("health").get("run", ""))
    assert "grep -qxF \"$name\" /tmp/hook-pilots.txt" in text
    assert "continue" in text


def test_health_check_records_helm_test_outcome_for_hook_pilots():
    text = str(_step("health").get("run", ""))
    assert "steps.helm-test.outcome" in text
    assert "OK (helm test)" in text
    assert "FAIL (helm test)" in text


def test_partition_branches_carry_a_temporary_scaffolding_comment():
    text = WORKFLOW.read_text()
    assert "TEMPORARY migration scaffolding" in text


def test_nohook_per_target_loop_unchanged_markers_present():
    # Same greppable evidence markers the pre-migration loop always had —
    # confirms the fallback path (hook-less pilots) was not gutted.
    text = _run_text()
    assert "derive_smoke_target" not in text  # composed-smoke calls smoke_candidates directly
    assert "smoke_candidates" in text
    assert "port-forward" in text
