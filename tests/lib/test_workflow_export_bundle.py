"""Contract tests for the consolidated security-export-full bundle job.

Static drift guards on .github/workflows/reusable-security-gate.yml: the
export-bundle job runs after image-scan (`if: always()`), pattern-downloads
the per-service security-export-*, sbom-source, and plan-bom artifacts
(merge-multiple: false so services can't collide), and re-uploads them as
one security-export-full-<sha> artifact. It is purely additive: it must
never appear in security-gate's needs:, so an assembly failure can never
fail the required check.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/reusable-security-gate.yml"
EVALUATOR = ROOT / "scripts/lib/evaluate_security_gate.py"

FULL_SHA_USES = re.compile(r"@[0-9a-f]{40}$")


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def _jobs() -> dict:
    return _workflow()["jobs"]


def _export_bundle() -> dict:
    return _jobs()["export-bundle"]


def test_export_bundle_job_exists():
    assert "export-bundle" in _jobs()


def test_export_bundle_runs_always_and_needs_image_scan():
    job = _export_bundle()
    assert job["if"] == "always()"
    # Depends on jobs that produce the bundled artifacts (plan -> plan-bom,
    # image-scan -> security-export-* + sbom-source), not on their success.
    assert set(job["needs"]) == {"plan", "image-scan"}


def test_export_bundle_is_excluded_from_the_blocking_fan_in():
    """export-bundle must never influence evaluate_security_gate.py's NEEDS_JSON:
    the evaluator can't see a job's result unless security-gate needs: it."""
    gate = _jobs()["security-gate"]
    assert "export-bundle" not in gate["needs"]

    evaluator_src = EVALUATOR.read_text()
    assert '"export-bundle"' not in evaluator_src
    assert "'export-bundle'" not in evaluator_src


def test_export_bundle_downloads_the_documented_artifacts_only():
    job = _export_bundle()
    download_steps = [
        s
        for s in job["steps"]
        if "actions/download-artifact@" in str(s.get("uses", ""))
    ]
    assert len(download_steps) == 1
    with_map = download_steps[0]["with"]
    pattern = with_map["pattern"]
    assert "security-export-*" in pattern
    assert "sbom-source" in pattern
    assert "plan-bom" in pattern
    # Explicitly not the raw per-leg / duplicate / unrelated artifacts.
    for excluded in (
        "semgrep-results",
        "sonarqube-",
        "scan-image-",
        "sbom-image-",
    ):
        assert excluded not in pattern, (
            f"export-bundle pattern must not pull in {excluded!r}"
        )
    # Each service keeps its own subdirectory so two services' metadata.json
    # (etc.) can't collide.
    assert with_map.get("merge-multiple") is False


def test_export_bundle_uploads_one_combined_artifact():
    job = _export_bundle()
    upload_steps = [
        s
        for s in job["steps"]
        if "actions/upload-artifact@" in str(s.get("uses", ""))
    ]
    assert len(upload_steps) == 1
    with_map = upload_steps[0]["with"]
    assert with_map["name"] == "security-export-full-${{ steps.sha.outputs.short }}"
    assert with_map.get("if-no-files-found") == "warn", (
        "a convenience bundle with zero matched artifacts must not error"
    )
    assert upload_steps[0].get("if") == "always()"


def test_export_bundle_download_step_is_failure_tolerant():
    job = _export_bundle()
    download_step = next(
        s
        for s in job["steps"]
        if "actions/download-artifact@" in str(s.get("uses", ""))
    )
    assert download_step.get("continue-on-error") is True


def test_export_bundle_remote_actions_pinned_by_full_sha():
    for step in _export_bundle()["steps"]:
        uses = str(step.get("uses", ""))
        if not uses or uses.startswith("./"):
            continue
        assert FULL_SHA_USES.search(uses), f"export-bundle: '{uses}' not SHA-pinned"


def test_per_service_export_artifact_upload_is_unchanged():
    """Non-goal guard: the per-service security-export upload in
    image-vuln-scan/action.yml is untouched; this job only reads/re-packages."""
    action = ROOT / ".github/actions/image-vuln-scan/action.yml"
    steps = yaml.safe_load(action.read_text())["runs"]["steps"]
    upload = next(s for s in steps if s.get("name") == "Upload security export bundle")
    assert upload["with"]["name"] == "security-export-${{ env.EXPORT_LEG }}-${{ env.EXPORT_SHORT_SHA }}"
    assert upload["if"] == "always()"
