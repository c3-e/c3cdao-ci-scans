"""Contract tests for the cluster-smoke job's helm-based rewiring.

Static drift guards on .github/workflows/reusable-security-gate.yml:
cluster-smoke consumes per-leg image tars, provisions smoke resources
before helm install, installs with --wait, and probes the chart-derived
HTTP target. The old single-artifact download and health-output bridge
are retired.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/reusable-security-gate.yml"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def _smoke() -> dict:
    return _workflow()["jobs"]["cluster-smoke"]


def _smoke_run_text() -> str:
    return "\n".join(str(s.get("run", "")) for s in _smoke()["steps"])


# --- bridge retirement (last v0.5 remnants) ------------------------------------


def test_health_bridge_output_retired():
    assert "health" not in _workflow()["jobs"]["plan"]["outputs"]
    assert "needs.plan.outputs.health" not in WORKFLOW.read_text()


def test_v05_image_artifact_retired():
    text = WORKFLOW.read_text()
    assert "IMAGE_ARTIFACT" not in text
    workflow_env = _workflow().get("env") or {}
    assert "IMAGE_ARTIFACT" not in workflow_env


# --- job graph: needs build + helm-check, image_only skip ----------------------


def test_cluster_smoke_needs_build_and_helm_check():
    smoke = _smoke()
    # plan is added directly for needs.plan.outputs.callee_ref; this was
    # already an implicit, transitive dependency, so scheduling is unchanged.
    assert set(smoke["needs"]) == {"plan", "build", "helm-check"}
    condition = str(smoke["if"])
    assert "always()" in condition
    assert "inputs.image_only != true" in condition
    assert "needs.build.result == 'success'" in condition
    assert "needs.helm-check.result == 'success'" in condition


# --- per-leg tar consumption ----------------------------------------------------


def test_cluster_smoke_downloads_per_leg_tars():
    download_steps = [
        s
        for s in _smoke()["steps"]
        if "actions/download-artifact@" in str(s.get("uses", ""))
    ]
    assert len(download_steps) == 1
    with_map = download_steps[0]["with"]
    assert with_map.get("pattern") == "scan-image-*"
    assert "name" not in with_map, "v0.5 single-artifact download must be gone"


def test_cluster_smoke_loads_every_tar_into_kind():
    text = _smoke_run_text()
    assert "docker load" in text
    assert "kind load docker-image" in text


# --- provision -> Ready gate -> helm install --wait -> derived probe -----------


def test_catalog_provision_runs_before_helm_install():
    text = _smoke_run_text()
    assert "smoke_catalog" in text
    assert text.index("smoke_catalog") < text.index('helm install "')


def test_module_readiness_failure_names_the_module_before_install():
    text = _smoke_run_text()
    marker = "smoke resource '${module}' failed readiness before helm install"
    assert marker in text
    assert text.index(marker) < text.index('helm install "')


def test_smoke_resources_input_feeds_the_provision_loop():
    smoke_steps = _smoke()["steps"]
    env_maps = [s.get("env") or {} for s in smoke_steps]
    assert any(
        e.get("SMOKE_RESOURCES") == "${{ inputs.smoke_resources }}" for e in env_maps
    )


def test_helm_install_waits():
    text = _smoke_run_text()
    install = text[text.index('helm install "') :]
    assert "--wait" in install.split("||")[0]


def test_probe_target_is_chart_derived():
    text = _smoke_run_text()
    assert "derive_smoke_target.py" in text
    assert "helm template" in text
    # markers double as greppable evidence in live CI logs
    assert "module ready" in text
    assert "probe 200" in text


# --- warn-only semantics survive the rewiring -----------------------------------


def test_smoke_step_keeps_advisory_gating_and_outcome_output():
    smoke = _smoke()
    assert smoke["outputs"]["smoke_ok"] == "${{ steps.smoke_outcome.outputs.ok }}"
    step = next(s for s in smoke["steps"] if s.get("id") == "smoke")
    assert (
        step["continue-on-error"]
        == "${{ vars.SECURITY_SCAN_BLOCKING != 'true' }}"
    )


# --- helm test hook detection (temporary migration scaffolding) ----------------


def _step(step_id: str) -> dict:
    return next(s for s in _smoke()["steps"] if s.get("id") == step_id)


def test_hook_detect_step_checks_the_already_rendered_file_not_a_rerender():
    step = _step("hook-detect")
    assert step["if"] == "steps.smoke.outcome == 'success'"
    text = str(step.get("run", ""))
    assert "/tmp/rendered-chart.yaml" in text
    assert "helm template" not in text  # static check only, no re-render
    assert "helm.sh/hook" in text


def test_helm_test_and_probe_fallback_are_mutually_exclusive():
    helm_test = _step("helm-test")
    fallback = _step("probe-fallback")
    assert helm_test["if"] == (
        "steps.smoke.outcome == 'success' && steps.hook-detect.outputs.found == 'true'"
    )
    assert fallback["if"] == (
        "steps.smoke.outcome == 'success' && steps.hook-detect.outputs.found == 'false'"
    )


def test_helm_test_step_runs_helm_test_with_logs():
    text = str(_step("helm-test").get("run", ""))
    assert "helm test" in text
    assert "--logs" in text


def test_probe_fallback_keeps_the_pre_migration_derive_and_probe_logic():
    text = str(_step("probe-fallback").get("run", ""))
    assert "derive_smoke_target.py" in text
    assert "port-forward" in text or "kubectl -n" in text
    assert "probe 200" in text


def test_fallback_branches_carry_a_temporary_scaffolding_comment():
    text = WORKFLOW.read_text()
    assert "TEMPORARY migration scaffolding" in text


def test_smoke_outcome_accounts_for_both_hook_and_fallback_branches():
    text = str(_step("smoke_outcome"))
    assert "steps.helm-test.outcome" in text
    assert "steps.probe-fallback.outcome" in text
