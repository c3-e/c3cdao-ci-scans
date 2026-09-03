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


def _package_job() -> dict:
    return _publish()["jobs"]["publish-staging-chart"]


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


def test_packages_write_lives_at_workflow_level_only():
    # A real regression (found via live bisection, not this test): a
    # job-level permissions: block on `build`, coexisting with the
    # workflow-level block, produced a silent zero-job startup_failure —
    # scoped to ANY job in this file, not just callers that `uses:` a
    # reusable workflow. packages: write must live in the single
    # workflow-level block; `build` must carry no job-level block at all.
    workflow_perms = _gate()["permissions"]
    assert workflow_perms == {
        "contents": "read",
        "pull-requests": "write",
        "packages": "write",
        "issues": "write",
    }


def test_no_job_has_job_level_permissions():
    for job_id, job in _gate()["jobs"].items():
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


# --- publish-staging-chart.yml: publish-staging-chart (chart packaging) --------


def test_package_job_resolves_dependencies_before_packaging():
    """A real, live bug (#34, 8613d62): a pilot chart declaring a
    file://-referenced local dependency (e.g. a sibling fullstack-template
    engine chart) with no pre-vendored charts/ subdir made `helm package`
    fail with "found in Chart.yaml, but missing in charts/ directory".
    `helm dependency build` fixes this for any pilot (a no-op for pilots
    that already pre-vendor — helm validates the existing tgz against
    Chart.lock's digest) but only if it runs before the package step."""
    steps = _package_job()["steps"]
    dep_build_idx = next(
        i
        for i, s in enumerate(steps)
        if "helm dependency build" in str(s.get("run", ""))
    )
    package_idx = next(
        i for i, s in enumerate(steps) if s.get("name") == "Package chart"
    )
    assert dep_build_idx < package_idx, (
        "helm dependency build must run before the Package chart step"
    )


def test_package_job_oci_dest_has_no_trailing_pilot_segment():
    """A real, live bug (#33, 44c8ed6): `helm push` always appends the
    chart's own name (from Chart.yaml) as an extra path component, so a
    DEST that already includes the pilot segment lands the chart at
    charts-staging/<pilot>/<pilot> instead of the locked
    charts-staging/<pilot> shape. DEST must be the bare registry path;
    the pilot segment must appear only in the human-facing echo/summary
    text, never inside the coords.dest output `helm push` actually
    receives."""
    steps = _package_job()["steps"]
    coords_run = next(
        str(s.get("run", "")) for s in steps if s.get("id") == "coords"
    )
    dest_line = next(
        line for line in coords_run.splitlines() if line.strip().startswith("DEST=")
    )
    assert "PILOT" not in dest_line, (
        f"DEST must not embed the pilot segment (helm push appends it "
        f"automatically): {dest_line!r}"
    )
    push_run = next(
        str(s.get("run", "")) for s in steps if s.get("name") == "Push to staging OCI registry"
    )
    assert "coords.outputs.dest" in push_run


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
