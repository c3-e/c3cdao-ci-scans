"""Contract tests for the v0.6 cluster-smoke rewiring.

Static drift guards on .github/workflows/reusable-security-gate.yml:
cluster-smoke consumes the per-leg scan-image-<target> tars, provisions
the declared smoke_resources catalog modules (Ready gate, failure names
the module) BEFORE helm install, installs with --wait, and probes the
chart-derived HTTP target (scripts/lib/derive_smoke_target.py). The v0.5
scan-image artifact and the plan job's `health` bridge output are
retired. Build-matrix and scan/fan-in surface guards live in test_workflow_build_matrix.py /
test_workflow_scan_fanin.py.
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
    # plan added directly so needs.plan.outputs.callee_ref is
    # accessible (it was already an implicit, transitive dependency via
    # build/helm-check — this doesn't change scheduling).
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
    # greppable AC-1 evidence markers
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
