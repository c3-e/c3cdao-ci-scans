"""Static shape guards for the digest-verified quarantine publish mechanism.

Covers two files:

- .github/workflows/reusable-security-gate.yml: the `build` job's
  publish_images input plumbing, its job-level packages: write permission,
  and the quarantine-push steps gated on `inputs.publish_images == true`.
- .github/workflows/publish-staging-chart.yml: the derive-publish-targets
  job (Issue I: single source of truth for the publish target list,
  derived from compose_file rather than a hand-typed images[] JSON array)
  and the publish-images-deferred job's quarantine-verify +
  imagetools-retag steps replacing the old docker/build-push-action
  rebuild path.

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


def _derive_job() -> dict:
    return _publish()["jobs"]["derive-publish-targets"]


def _deferred_run_text() -> str:
    return "\n".join(str(s.get("run", "")) for s in _deferred_job()["steps"])


def _derive_run_text() -> str:
    return "\n".join(str(s.get("run", "")) for s in _derive_job()["steps"])


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


# --- publish-staging-chart.yml: derive-publish-targets (Issue I) ----------------


def test_images_input_retired():
    """The old hand-typed images[] JSON array input is gone -- replaced by
    compose_file + publish_targets (Issue I)."""
    inputs = _publish()["on"]["workflow_call"]["inputs"]
    assert "images" not in inputs
    assert inputs["compose_file"]["default"] == "docker-compose.yml"
    assert inputs["publish_targets"]["default"] == ""


def test_derive_publish_targets_job_exists_and_feeds_the_matrix():
    derive = _derive_job()
    assert "targets" in derive["outputs"]
    deferred = _deferred_job()
    assert "derive-publish-targets" in deferred["needs"]


def test_publish_images_deferred_matrix_comes_from_derive_job():
    deferred = _deferred_job()
    assert deferred["strategy"]["matrix"]["target"] == (
        "${{ fromJSON(needs.derive-publish-targets.outputs.targets) }}"
    )


def test_derive_publish_targets_reuses_derive_bom_py():
    """Same derivation reusable-security-gate.yml's own plan job runs --
    single source of truth, not a reimplementation."""
    text = _derive_run_text()
    assert "derive_bom.py" in text


def test_derive_publish_targets_fails_closed_on_unknown_allow_listed_target():
    text = _derive_run_text()
    assert "::error::" in text
    assert "publish_targets" in text
    assert "exit 1" in text


def test_derive_publish_targets_and_gate_share_the_same_ci_scans_ref_resolver_pattern():
    """Duplicated per job (GitHub Actions jobs can't share steps), but
    must be the same yq-based, first-match resolver as
    publish-images-deferred's own copy and reusable-security-gate.yml's
    plan job -- not a third, divergent implementation."""
    derive_steps = _derive_job()["steps"]
    resolver = next(
        s for s in derive_steps if s.get("name") == "Resolve callee (ci-scans) ref"
    )
    assert "publish-staging-chart\\.yml@" in resolver["run"]


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
    steps = _deferred_job()["steps"]
    text = _deferred_run_text()
    assert any(
        (s.get("env") or {}).get("TARGET") == "${{ matrix.target }}" for s in steps
    )
    assert "images-quarantine" in text
