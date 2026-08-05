"""Structural drift guards for OpenVEX consumption in image-vuln-scan (T2).

The composite action must consume a consumer-committed
.openvex/templates/main.openvex.json with no-op-when-absent semantics
(mirror of the .trivyignore defaulting): absent the template, an
empty-statements OpenVEX doc is defaulted so consumers without .openvex/
scan bit-identical to before. Wiring routes are the ones T1's spike proved
at the current pins (run 31055413726 on spike/vex-gate): trivy-config: for
Trivy, GRYPE_VEX_DOCUMENTS for the Grype image leg only — the Grype SBOM
leg has no root-component PURL to match and must stay VEX-free (a silent
no-op there would look wired but isn't).
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


# --- per-leg wiring (exactly the routes T1 proved) ------------------------------


def test_trivy_step_consumes_vex_via_trivy_config_input():
    trivy = _step("Trivy scan — image")
    assert trivy["with"]["trivy-config"] == "${{ env.VEX_TRIVY_CONFIG }}"
    # Existing suppression surface untouched.
    assert trivy["with"]["trivyignores"] == ".trivyignore"


def test_grype_image_step_consumes_vex_via_step_scoped_env():
    grype = _step("Grype scan — image")
    assert grype.get("env", {}).get("GRYPE_VEX_DOCUMENTS") == "${{ env.VEX_DOC }}"
    # Route is step-scoped env, not a with: input — keeps the SBOM step's
    # surface identical and the wiring visible on the one leg it applies to.
    assert "vex" not in grype["with"]


def test_grype_sbom_step_has_no_vex_wiring():
    """anchore/sbom-action's CycloneDX root component has no purl at the
    current pin, so VEX cannot match on the SBOM leg (T1 acceptance
    record) — wiring it anyway would be a silent no-op that reads as
    coverage. The step must stay VEX-free, with the exemption explained
    in a comment next to it."""
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
    assert "aquasecurity/trivy-action@57a97c7e7821a5776cebc9bb87c984fa69cba8f1  # v0.35.0" in text
    assert text.count(
        "anchore/scan-action@e1165082ffb1fe366ebaf02d8526e7c4989ea9d2  # v7.4.0"
    ) == 2
