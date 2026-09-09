"""Structural drift guards for OpenVEX consumption in image-vuln-scan.

The composite action must consume a consumer-committed
.openvex/templates/main.openvex.json with no-op-when-absent semantics
(mirror of the .trivyignore defaulting): absent the template, an
empty-statements OpenVEX doc is defaulted so consumers without .openvex/
scan bit-identical to before. Wiring routes are the ones proven at the
current pins: trivy-config: for Trivy, GRYPE_VEX_DOCUMENTS for the Grype
image leg only — the Grype SBOM leg has no root-component PURL to match
and must stay VEX-free (a silent no-op there would look wired but isn't).
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
ACTION = ROOT / ".github/actions/image-vuln-scan/action.yml"


def _action() -> dict:
    return yaml.safe_load(ACTION.read_text())


def _steps() -> list[dict]:
    return _action()["runs"]["steps"]


def _step(name: str) -> dict:
    matches = [s for s in _steps() if s.get("name") == name]
    assert len(matches) == 1, f"expected exactly one step named {name!r}"
    return matches[0]


# --- no new caller surface (standalone-composable action) ----------------------

EXPECTED_INPUTS = {
    "image-tag": True,
    "image-artifact-name": True,
    "sbom-artifact-name": True,
    "trivy-severity": True,
    "blocking": False,
}


def test_action_inputs_unchanged_no_new_required_inputs():
    """VEX onboarding is data-only (.openvex/ in the consumer checkout);
    adding an input — required especially — breaks existing callers."""
    inputs = _action()["inputs"]
    assert {
        name: spec.get("required", False) for name, spec in inputs.items()
    } == EXPECTED_INPUTS


# --- defaulting step (no-op-when-absent) ---------------------------------------


def test_defaulting_step_resolves_consumer_template_or_empty_default():
    run = _step("Default scanner configs when consumer lacks them")["run"]
    assert ".openvex/templates/main.openvex.json" in run
    # Empty-statements doc, not a missing path: scan steps reference the
    # resolved doc unconditionally.
    assert '"statements": []' in run
    assert "${RUNNER_TEMP}/empty.openvex.json" in run


def test_defaulting_step_exports_resolved_paths_via_github_env():
    run = _step("Default scanner configs when consumer lacks them")["run"]
    assert "VEX_DOC=" in run
    assert "VEX_TRIVY_CONFIG=" in run
    assert "$GITHUB_ENV" in run
    # Trivy consumes VEX via a generated config file (vulnerability.vex).
    assert "vulnerability:" in run and "vex:" in run


# --- per-leg wiring (exactly the proven routes) ---------------------------------


def test_trivy_step_consumes_vex_via_trivy_config_input():
    trivy = _step("Trivy scan — image")
    assert trivy["with"]["trivy-config"] == "${{ env.VEX_TRIVY_CONFIG }}"
    # Existing suppression surface untouched.
    assert trivy["with"]["trivyignores"] == ".trivyignore"


# --- job-local registry (Grype VEX product identity) -----------------------


def test_registry_publish_step_precedes_scans_and_exports_scan_ref():
    """A docker-load'ed local build has no repoDigest, which Grype's VEX
    matching requires — this step must run before scans and publish one."""
    names = [s.get("name") for s in _steps()]
    publish_idx = names.index("Publish image to job-local registry (VEX product identity)")
    assert names.index("Load image into local daemon") < publish_idx
    assert publish_idx < names.index("Trivy scan — image")
    run = _step("Publish image to job-local registry (VEX product identity)")["run"]
    assert "localhost:5000/" in run
    assert "SCAN_REF=" in run and "$GITHUB_ENV" in run
    # Fail-closed: a missing repoDigest must fail the step, not degrade
    # to a silent no-op.
    assert "RepoDigests" in run and "exit 1" in run


def test_registry_guard_checks_running_state_not_mere_existence():
    """docker inspect success only proves the name is taken, not that the
    registry is serving — a leftover *stopped* vex-registry container (e.g.
    a reused/self-hosted runner) would pass a bare existence check, then
    the readiness loop spins for 30s against a dead endpoint before the
    push fails with a confusing connection error. The guard must check
    State.Running and clear a stale container before recreating it."""
    run = _step("Publish image to job-local registry (VEX product identity)")["run"]
    assert "State.Running" in run, "guard must check the container is actually running"
    assert "docker rm -f vex-registry" in run, (
        "a stopped container must be removed before recreating, not left in place"
    )


def test_registry_image_is_digest_pinned():
    run = _step("Publish image to job-local registry (VEX product identity)")["run"]
    assert "registry@sha256:" in run, (
        "the job-local registry image must be digest-pinned (repo convention: "
        "no floating tags in gate-executed pulls)"
    )


def test_image_scans_target_the_registry_backed_reference():
    """All four image scans (2 gating tables + 2 JSON exports) must scan
    SCAN_REF — scanning the bare load tag reintroduces the digest-less
    identity Grype cannot match."""
    assert _step("Trivy scan — image")["with"]["image-ref"] == "${{ env.SCAN_REF }}"
    assert _step("Grype scan — image")["with"]["image"] == "${{ env.SCAN_REF }}"
    # The always() export steps fall back to the load tag so a failed
    # registry publish still yields an evidence bundle.
    assert (
        _step("Trivy scan — image (JSON for export)")["with"]["image-ref"]
        == "${{ env.SCAN_REF || inputs.image-tag }}"
    )
    assert (
        _step("Grype scan — image (JSON for export)")["with"]["image"]
        == "${{ env.SCAN_REF || inputs.image-tag }}"
    )


def test_grype_image_step_consumes_vex_via_step_scoped_env():
    grype = _step("Grype scan — image")
    assert grype.get("env", {}).get("GRYPE_VEX_DOCUMENTS") == "${{ env.VEX_DOC }}"
    # Route is step-scoped env, not a with: input — keeps the SBOM step's
    # surface identical and the wiring visible on the one leg it applies to.
    assert "vex" not in grype["with"]


def test_grype_sbom_step_has_no_vex_wiring():
    """anchore/sbom-action's CycloneDX root component has no purl at the
    current pin, so VEX cannot match on the SBOM leg — wiring it anyway
    would be a silent no-op that reads as coverage. The step must stay
    VEX-free, with the exemption explained in a comment next to it."""
    sbom = _step("Grype scan — image SBOM")
    assert "vex" not in sbom["with"]
    assert "GRYPE_VEX_DOCUMENTS" not in str(sbom.get("env", {}))
    text = ACTION.read_text()
    idx = text.index("- name: Grype scan — image SBOM")
    preceding = text[:idx].rsplit("- name:", 1)[-1]
    assert "no product identity" in preceding.lower() or "no purl" in preceding.lower(), (
        "the SBOM leg's VEX exemption must be explained in a comment, "
        "not silently omitted"
    )


def test_scan_steps_stay_sha_pinned_with_version_comments():
    text = ACTION.read_text()
    # 2 Trivy steps (gating table + JSON export), 3 Grype steps (image +
    # image SBOM gating tables + JSON export) — every one SHA-pinned with
    # its version comment.
    assert text.count(
        "aquasecurity/trivy-action@57a97c7e7821a5776cebc9bb87c984fa69cba8f1  # v0.35.0"
    ) == 2
    assert text.count(
        "anchore/scan-action@e1165082ffb1fe366ebaf02d8526e7c4989ea9d2  # v7.4.0"
    ) == 3


# --- gate.workflow_sha / gate.workflow_ref source (VEX-9) -------------------


def test_gate_workflow_fields_use_job_context_not_github_context():
    """github.job_workflow_sha never populates for a job invoked from a
    reusable workflow (actions/runner#2417) — it must not appear anywhere
    in the action. github.workflow_ref / $GITHUB_WORKFLOW_REF is
    caller-scoped (resolves to the consumer's own workflow file, not the
    gate's), so it must not back gate.workflow_ref either. job.workflow_sha
    and job.workflow_ref are GitHub's shipped replacement for this exact
    reusable-workflow case."""
    step = _step("Assemble security export bundle")
    assert step["env"]["GATE_WORKFLOW_SHA"] == "${{ job.workflow_sha }}"
    assert step["env"]["GATE_WORKFLOW_REF"] == "${{ job.workflow_ref }}"
    # The bug's explanation stays in a comment (mentions the old, broken
    # fields by name) — only the live expressions/env-reads must be gone.
    assert "${{ github.job_workflow_sha }}" not in ACTION.read_text()
    assert "${GITHUB_WORKFLOW_REF" not in _step("Assemble security export bundle")["run"]


def test_gate_workflow_fields_mapped_via_explicit_env_not_run_block():
    """Same style as every other value the export step consumes: mapped
    through an explicit env: var, not read directly off an ambient
    $GITHUB_* variable inside the run: block."""
    step = _step("Assemble security export bundle")
    run = step["run"]
    assert '"${GATE_WORKFLOW_SHA:-}"' in run
    assert '"${GATE_WORKFLOW_REF:-}"' in run
