"""Static shape guards for the digest-verified quarantine publish mechanism.

Covers two files:

- .github/workflows/reusable-security-gate.yml: the `build` job's
  publish_images input plumbing, its job-level packages: write permission,
  and the quarantine-push steps gated on `inputs.publish_images == true`.
- .github/workflows/publish-staging-chart.yml: the `images` input's tuple
  shape (target now required) and the publish-images-deferred job's
  quarantine-verify + imagetools-retag steps replacing the old
  docker/build-push-action rebuild path.

These are drift guards on the YAML shape only (no cluster, no registry) —
tests/fixtures/hello-image plus the selftest-publish-images.yml workflow
prove the real round trip (see that workflow's own run history for live
evidence).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from lint_rules import load_gha_workflow  # noqa: E402

GATE_WORKFLOW = ROOT / ".github/workflows/reusable-security-gate.yml"
PUBLISH_WORKFLOW = ROOT / ".github/workflows/publish-staging-chart.yml"


def _gate() -> dict:
    return load_gha_workflow(GATE_WORKFLOW)


def _publish() -> dict:
    return load_gha_workflow(PUBLISH_WORKFLOW)


def _build_job() -> dict:
    return _gate()["jobs"]["build"]


def _build_run_text() -> str:
    return "\n".join(str(s.get("run", "")) for s in _build_job()["steps"])


def _deferred_job() -> dict:
    return _publish()["jobs"]["publish-images-deferred"]


def _deferred_run_text() -> str:
    return "\n".join(str(s.get("run", "")) for s in _deferred_job()["steps"])


# --- reusable-security-gate.yml: publish_images input + build job wiring --------


def test_publish_images_input_declared_boolean_default_false():
    inputs = _gate()["on"]["workflow_call"]["inputs"]
    assert inputs["publish_images"]["type"] == "boolean"
    assert inputs["publish_images"]["default"] is False


def test_build_job_has_packages_write_permission_only():
    build = _build_job()
    assert build["permissions"]["packages"] == "write"
    # Workflow-level permissions (contents/pull-requests) are untouched —
    # this job-level block narrows/extends, it does not replace them.
    workflow_perms = _gate()["permissions"]
    assert workflow_perms == {"contents": "read", "pull-requests": "write"}


def test_no_other_job_has_job_level_permissions():
    for job_id, job in _gate()["jobs"].items():
        if job_id == "build":
            continue
        assert "permissions" not in job, f"unexpected job-level permissions: on '{job_id}'"


def test_quarantine_push_steps_gated_on_publish_images_input():
    steps = _build_job()["steps"]
    gated = [s for s in steps if "quarantine" in str(s.get("name", "")).lower()]
    assert gated, "expected at least one quarantine-named step in the build job"
    for step in gated:
        assert step.get("if") == "${{ inputs.publish_images == true }}"


def test_build_job_ghcr_login_reuses_the_pinned_login_action():
    text = str(_build_job()["steps"])
    assert "docker/login-action@c94ce9fb468520275223c153574b00df6fe4bcc9" in text


def test_quarantine_ref_formula_present():
    text = _build_run_text()
    assert "images-quarantine" in text
    assert "docker tag" in text
    assert "docker push" in text
    assert "imagetools inspect" in text


# --- publish-staging-chart.yml: images input shape -------------------------------


def test_images_input_description_requires_target():
    description = _publish()["on"]["workflow_call"]["inputs"]["images"]["description"]
    assert "target" in description
    assert "REQUIRED" in description


def test_publish_images_deferred_matrix_unchanged():
    deferred = _deferred_job()
    assert deferred["strategy"]["matrix"]["image"] == "${{ fromJSON(inputs.images) }}"


def test_publish_images_deferred_uses_imagetools_not_build_push_action():
    text = str(_deferred_job()["steps"])
    assert "imagetools create" in text or "imagetools" in _deferred_run_text()
    assert "docker/build-push-action" not in text


def test_publish_images_deferred_still_has_buildx_setup():
    # imagetools inspect/create both need buildx; the setup step must
    # survive the removal of docker/build-push-action.
    text = str(_deferred_job()["steps"])
    assert "docker/setup-buildx-action" in text


def test_publish_images_deferred_verifies_before_retagging():
    text = _deferred_run_text()
    assert "imagetools inspect" in text
    assert "imagetools create" in text
    assert text.index("imagetools inspect") < text.index("imagetools create")


def test_publish_images_deferred_fails_closed_on_missing_quarantine_image():
    text = _deferred_run_text()
    assert "::error::" in text
    assert "re-scanned via a fresh gate run" in text
    assert "exit 1" in text


def test_publish_images_deferred_derives_ref_from_matrix_target():
    text = _deferred_run_text()
    assert "matrix.image.target" in str(_deferred_job()["steps"]) or "TARGET" in text
    assert "images-quarantine" in text
