"""Structural drift guards for the per-run security export bundle (T3).

Each image-scan matrix leg must upload a self-contained evidence bundle —
security-export-<leg>-<short-sha> — holding the image SBOM, machine-readable
Trivy/Grype scan JSONs, the VEX doc exactly as applied (consumer template or
the empty default), and metadata.json. Export steps run `if: always()` so
the bundle survives a blocking-scan failure, and the JSON re-scans carry the
same suppression surface as the gating table scans so the export mirrors
what actually gated.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
ACTION = ROOT / ".github/actions/image-vuln-scan/action.yml"

BUNDLE_FILES = {
    "sbom-image.cdx.json",
    "grype-image.json",
    "vex-applied.openvex.json",
    "metadata.json",
}


def _steps() -> list[dict]:
    return yaml.safe_load(ACTION.read_text())["runs"]["steps"]


def _step(name: str) -> dict:
    matches = [s for s in _steps() if s.get("name") == name]
    assert len(matches) == 1, f"expected exactly one step named {name!r}"
    return matches[0]


def test_export_steps_run_even_when_blocking_scans_fail():
    for name in (
        "Trivy scan — image (JSON for export)",
        "Grype scan — image (JSON for export)",
        "Assemble security export bundle",
        "Upload security export bundle",
    ):
        assert _step(name).get("if") == "always()", (
            f"step {name!r} must be if: always() — a failing (blocking) run "
            "is exactly when the evidence bundle matters"
        )


def test_export_scans_carry_the_same_suppression_surface_as_the_gating_scans():
    trivy = _step("Trivy scan — image (JSON for export)")["with"]
    assert trivy["format"] == "json"
    assert trivy["exit-code"] == "0", "export scan must never drive gating"
    assert trivy["trivyignores"] == ".trivyignore"
    assert trivy["trivy-config"] == "${{ env.VEX_TRIVY_CONFIG }}"
    assert trivy["severity"] == "${{ inputs.trivy-severity }}"

    grype = _step("Grype scan — image (JSON for export)")
    assert grype["with"]["output-format"] == "json"
    assert grype["with"]["fail-build"] is False
    assert grype["with"]["config"] == ".grype.yaml"
    assert grype["env"]["GRYPE_VEX_DOCUMENTS"] == "${{ env.VEX_DOC }}"


def test_bundle_contains_the_five_evidence_files():
    run = _step("Assemble security export bundle")["run"]
    for fname in BUNDLE_FILES:
        assert fname in run, f"bundle must contain {fname}"
    # Fifth file: the Trivy JSON is written straight into the export dir by
    # the export scan step.
    trivy_out = _step("Trivy scan — image (JSON for export)")["with"]["output"]
    assert trivy_out == "${{ runner.temp }}/security-export/trivy-image.json"


def test_metadata_records_the_documented_fields():
    run = _step("Assemble security export bundle")["run"]
    for field in (
        "image_digest",
        "vex_source",
        "blocking",
        "gate_workflow_ref",
        "trivy",
        "grype",
    ):
        assert field in run, f"metadata.json must record {field}"
    # VEX provenance must distinguish a real consumer doc from the default.
    assert "empty-default" in run and "consumer" in run


def test_upload_uses_matrix_safe_per_run_artifact_name():
    upload = _step("Upload security export bundle")
    assert (
        upload["with"]["name"]
        == "security-export-${{ env.EXPORT_LEG }}-${{ env.EXPORT_SHORT_SHA }}"
    )
    assert upload["with"]["if-no-files-found"] == "error"
    # Leg/sha derivation lives in the defaulting step, from the existing
    # scan-image-<name> artifact convention.
    default = _step("Default scanner configs when consumer lacks them")
    assert "scan-image-" in default["run"]
    assert "EXPORT_LEG=" in default["run"]
    assert "EXPORT_SHORT_SHA=" in default["run"]
    assert (
        default["env"]["IMAGE_ARTIFACT_NAME"]
        == "${{ inputs.image-artifact-name }}"
    )


def test_gating_table_scans_unchanged_by_export():
    """The export is additive: the three original scan steps keep table
    output and their blocking semantics."""
    trivy = _step("Trivy scan — image")["with"]
    assert trivy["format"] == "table"
    assert trivy["exit-code"] == "${{ inputs.blocking == 'true' && '1' || '0' }}"
    for name in ("Grype scan — image", "Grype scan — image SBOM"):
        w = _step(name)["with"]
        assert w["output-format"] == "table"
        assert w["fail-build"] == "${{ inputs.blocking == 'true' }}"
