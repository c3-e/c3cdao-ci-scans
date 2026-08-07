"""Contract tests for the export-bundle job's PR scan-summary comment.

Static drift guards on .github/workflows/reusable-security-gate.yml: two
steps in the (existing) export-bundle job build and then post/update a
single PR comment summarizing per-service Trivy/Grype High+Critical counts
and VEX source, a link to the run page, and the consolidated artifact's
name + `gh run download` line (docs/RUNBOOK.md Appendix I), plus a
read-only pending-VEX-disposition report. This is commentary, not a gate:
both steps are pull_request-gated and continue-on-error, and (like the
rest of export-bundle) the job is not in security-gate's needs:, so a
comment-posting failure can never affect the required check. Static YAML
shape only — the actual HTTP find-or-update behavior needs a live
pull_request-triggered run to fully prove (see the PR description).
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/reusable-security-gate.yml"
EVALUATOR = ROOT / "scripts/lib/evaluate_security_gate.py"

FULL_SHA_USES = re.compile(r"@[0-9a-f]{40}$")
MARKER = "<!-- security-export-summary -->"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def _jobs() -> dict:
    return _workflow()["jobs"]


def _export_bundle() -> dict:
    return _jobs()["export-bundle"]


def _step(name: str) -> dict:
    matches = [s for s in _export_bundle()["steps"] if s.get("name") == name]
    assert len(matches) == 1, f"expected exactly one export-bundle step named {name!r}"
    return matches[0]


def _build_step() -> dict:
    return _step("Build PR scan-summary comment body")


def _post_step() -> dict:
    return _step("Post or update PR scan-summary comment")


def test_pr_summary_steps_exist_in_export_bundle():
    names = {s.get("name") for s in _export_bundle()["steps"]}
    assert "Build PR scan-summary comment body" in names
    assert "Post or update PR scan-summary comment" in names


def test_pr_summary_steps_are_pull_request_gated():
    # Must run ONLY on pull_request-triggered calls (never
    # merge_group/schedule/workflow_dispatch/push — the caller template
    # triggers this reusable workflow on all four).
    for step in (_build_step(), _post_step()):
        assert step.get("if") == "github.event_name == 'pull_request'"


def test_pr_summary_steps_are_failure_tolerant():
    # Commentary, not a gate: a posting failure must not fail the job.
    for step in (_build_step(), _post_step()):
        assert step.get("continue-on-error") is True


def test_export_bundle_is_still_excluded_from_the_blocking_fan_in():
    """Unchanged non-goal guard (same assertion as
    test_workflow_export_bundle.py): adding the PR-comment steps to this
    job must not pull it into security-gate's needs: or the evaluator."""
    gate = _jobs()["security-gate"]
    assert "export-bundle" not in gate["needs"]
    evaluator_src = EVALUATOR.read_text()
    assert '"export-bundle"' not in evaluator_src
    assert "'export-bundle'" not in evaluator_src


def test_comment_body_carries_the_hidden_marker():
    run = _build_step()["run"]
    assert MARKER in run


def test_comment_body_reads_bundle_finding_counts_and_vex_source():
    run = _build_step()["run"]
    assert "trivy-image.json" in run
    assert "grype-image.json" in run
    assert "metadata.json" in run
    # Trivy/Grype High+Critical severity filter.
    assert "HIGH" in run and "CRITICAL" in run
    assert "High" in run and "Critical" in run
    assert ".vex.source" in run


def test_comment_body_links_the_run_page_not_a_direct_artifact_url():
    run = _build_step()["run"]
    assert (
        "${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}"
        in run
    )


def test_comment_body_includes_consolidated_artifact_name_and_cli_download_line():
    run = _build_step()["run"]
    assert "security-export-full-${{ steps.sha.outputs.short }}" in run
    assert "gh run download ${{ github.run_id }} -n security-export-full-${{ steps.sha.outputs.short }}" in run


def test_post_step_finds_existing_comment_via_marker_then_patches_or_posts():
    run = _post_step()["run"]
    # Find: GET issue comments, filtered by the marker substring.
    assert "/issues/${PR_NUMBER}/comments" in run
    assert "contains($marker)" in run
    # Update-in-place: PATCH the matched comment id.
    assert "-X PATCH" in run
    assert "/issues/comments/${existing_id}" in run
    # Create when no match: POST to the issue-comments collection.
    assert "-X POST" in run


def test_post_step_uses_github_token_no_new_secret():
    step = _post_step()
    assert step.get("env", {}).get("GITHUB_TOKEN") == "${{ secrets.GITHUB_TOKEN }}"


def test_post_step_scopes_to_the_triggering_pr_number():
    step = _post_step()
    assert step.get("env", {}).get("PR_NUMBER") == "${{ github.event.pull_request.number }}"


def test_no_actions_github_script_dependency_introduced():
    """Per the task's style-consistency guidance: this file uses shell
    run: steps + composite actions throughout, no actions/github-script
    anywhere; the PR-comment steps follow suit (plain curl + jq against
    the REST API) rather than introducing a new action dependency."""
    workflow_src = WORKFLOW.read_text()
    assert "actions/github-script" not in workflow_src


def test_export_bundle_job_has_no_extra_permissions_block():
    """No job-level permissions: override was added for this job — the
    workflow-level `pull-requests: write` (already granted, see the
    top-level permissions: block) is sufficient for issue-comment
    create/update via the REST API, matching how every other job in this
    file relies on the workflow-level grant rather than declaring its
    own."""
    assert "permissions" not in _export_bundle()


def test_workflow_level_permissions_grant_pull_requests_write():
    perms = _workflow().get("permissions", {})
    assert perms.get("pull-requests") == "write"


def test_pr_summary_steps_come_after_the_bundle_is_assembled():
    """The comment body step must read from the bundle directory this
    job already downloaded/assembled above it, not race the download."""
    steps = _export_bundle()["steps"]
    names = [s.get("name") for s in steps]
    assert names.index("Build PR scan-summary comment body") > names.index(
        "Download this run's export-bundle artifacts"
    )


def test_pr_summary_remote_actions_pinned_by_full_sha():
    """The two new steps are plain run: (curl/jq), not remote actions —
    confirm neither introduces an unpinned `uses:`."""
    for step in (_build_step(), _post_step()):
        assert "uses" not in step


# --- pending-VEX-disposition report (read-only enumeration) ----------------


def _pending_report_step() -> dict:
    return _step("Build pending-disposition report")


def test_pending_disposition_step_exists_and_is_pull_request_gated():
    step = _pending_report_step()
    assert step.get("if") == "github.event_name == 'pull_request'"
    assert step.get("continue-on-error") is True


def test_pending_disposition_step_never_writes_under_openvex():
    """Structural guard mirroring the module-level invariant: the workflow
    step must never construct an .openvex/ path itself (enumeration is
    delegated entirely to pending_disposition_report.py, which is
    unit-tested separately to never write one either)."""
    run = _pending_report_step()["run"]
    assert ".openvex" not in run


def test_pending_disposition_step_calls_the_report_script_read_only():
    run = _pending_report_step()["run"]
    assert "pending_disposition_report.py" in run
    assert "security-export-full" in run


def test_pending_disposition_report_is_appended_to_comment_body():
    run = _build_step()["run"]
    assert "steps.pending-disposition.outputs.out_file" in run


def test_pending_disposition_step_runs_after_bundle_download():
    steps = _export_bundle()["steps"]
    names = [s.get("name") for s in steps]
    assert names.index("Build pending-disposition report") > names.index(
        "Download this run's export-bundle artifacts"
    )
    assert names.index("Build pending-disposition report") < names.index(
        "Build PR scan-summary comment body"
    )


def test_pending_disposition_bootstrap_steps_are_pull_request_gated():
    """The cross-repo checkout + setup-uv steps this report needs must not
    run on non-PR triggers (merge_group/schedule/workflow_dispatch/push),
    matching the report step itself. export-bundle carries no other
    checkout/setup-uv steps, so every match here belongs to this feature."""
    steps = _export_bundle()["steps"]
    bootstrap = [
        s
        for s in steps
        if "actions/checkout@" in str(s.get("uses", ""))
        or "astral-sh/setup-uv@" in str(s.get("uses", ""))
    ]
    assert bootstrap, "expected checkout/setup-uv bootstrap steps for the report"
    for step in bootstrap:
        assert step.get("if") == "github.event_name == 'pull_request'"
