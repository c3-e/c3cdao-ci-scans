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

import json
import re
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/reusable-security-gate.yml"
EVALUATOR = ROOT / "scripts/lib/evaluate_security_gate.py"

FULL_SHA_USES = re.compile(r"@[0-9a-f]{40}$")
MARKER = "<!-- security-export-summary -->"
ISSUE_MARKER = "<!-- security-export-issue -->"


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


def _issue_step() -> dict:
    return _step("Post or update tracking Issue")


def test_pr_summary_steps_exist_in_export_bundle():
    names = {s.get("name") for s in _export_bundle()["steps"]}
    assert "Build PR scan-summary comment body" in names
    assert "Post or update PR scan-summary comment" in names


def test_pr_summary_steps_are_pull_request_gated():
    # Build step runs for both PR comments and issues (output_channel is either).
    # Post step runs only for PR comments. Neither runs for summary_only.
    build_step = _build_step()
    post_step = _post_step()
    assert (
        build_step.get("if")
        == "needs.plan.outputs.output_channel == 'pr_comment' || needs.plan.outputs.output_channel == 'issue'"
    )
    assert post_step.get("if") == "needs.plan.outputs.output_channel == 'pr_comment'"


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
    # Runs for both pr_comment and issue — both channels' shared
    # "Build PR scan-summary comment body" step needs this report's
    # output_file; gating it to pr_comment-only would silently leave
    # scheduled/issue-channel runs with an empty report body.
    step = _pending_report_step()
    assert (
        step.get("if")
        == "needs.plan.outputs.output_channel == 'pr_comment' || needs.plan.outputs.output_channel == 'issue'"
    )
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
    """The cross-repo checkout + setup-uv steps this report needs must run
    on exactly the same channels as the report step itself — pr_comment
    AND issue, never summary_only. export-bundle carries no other
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
        assert (
            step.get("if")
            == "needs.plan.outputs.output_channel == 'pr_comment' || needs.plan.outputs.output_channel == 'issue'"
        )


# --- T-5: persistent tracking Issue path (output_channel == 'issue') ---------


def test_issue_step_exists_and_is_issue_channel_gated():
    step = _issue_step()
    assert step.get("if") == "needs.plan.outputs.output_channel == 'issue'"


def test_issue_step_carries_a_distinct_marker_from_the_pr_comment():
    """The Issue path must use its own hidden marker, not accidentally
    reuse the PR-comment's — a shared marker string would make the
    find-or-create lookups on the two independent surfaces (PR comments
    vs. repo issues) impossible to tell apart if either API ever returned
    cross-contaminated results."""
    run = _issue_step()["run"]
    assert ISSUE_MARKER in run
    assert ISSUE_MARKER != MARKER


def test_issue_step_finds_existing_open_issue_via_marker_then_patches_or_creates():
    run = _issue_step()["run"]
    # Find: GET open issues, filtered by the marker substring, excluding PRs
    # (GitHub's issues API returns pull requests too unless filtered out).
    assert "/repos/${REPO}/issues?state=open" in run
    assert "contains($marker)" in run
    assert "pull_request == null" in run
    # Update-in-place: PATCH the matched issue number.
    assert "-X PATCH" in run
    assert "/issues/${existing_number}" in run
    # Create when no match: POST to the issues collection.
    assert "-X POST" in run
    assert '"${api}/repos/${REPO}/issues"' in run


def test_issue_step_search_is_paginated():
    """Same requirement as the PR-comment step's own find-or-create loop
    (per this ticket's Exemplar-Files instruction to mirror it exactly) —
    a single 100-item page would silently miss the tracking issue on a
    repo with more than 100 open issues, creating a duplicate every run
    instead of updating the one that already exists."""
    run = _issue_step()["run"]
    assert "page=${page}" in run
    assert "page=$((page + 1))" in run


def test_issue_step_failures_are_loud_not_swallowed():
    """AC-6: a permissions problem or transient API error must surface as
    an explicit ::error:: with a non-zero exit — never complete green
    with no Issue created. continue-on-error is False (unlike the
    PR-comment steps) so the step's own failure is visible in the job's
    conclusion, not just its log."""
    step = _issue_step()
    assert step.get("continue-on-error") is False
    run = step["run"]
    assert run.count("::error::") >= 3  # missing body, list-failure, create/update-failure
    assert "exit 1" in run


def test_issue_step_uses_github_token_no_new_secret():
    step = _issue_step()
    assert step.get("env", {}).get("GITHUB_TOKEN") == "${{ secrets.GITHUB_TOKEN }}"


def test_issue_step_reuses_the_shared_comment_body_not_a_second_report_run():
    """Both output channels must read from the SAME pending-disposition
    report and the SAME body-builder step's output — never re-run the
    report or duplicate the SLA-banner logic for the Issue path."""
    step = _issue_step()
    assert step.get("env", {}).get("BODY_FILE") == "${{ steps.pr-summary.outputs.body_file }}"


def test_sla_breach_banner_present_in_build_step_and_gated_on_real_report_content():
    """AC-1: the banner must be conditional on the pending-disposition
    report actually containing a breach string (T-4's own output), never
    unconditionally present — and the build step must be the one place
    this logic lives, since both channels share it."""
    run = _build_step()["run"]
    assert "SLA breach — 90-day threshold exceeded" in run
    assert "⚠️" in run
    # Conditional, not unconditional: the banner echo must be inside an
    # `if` block that checks the report file for that exact string.
    assert 'grep -q "SLA breach — 90-day threshold exceeded"' in run


# --- Regression: real jq execution against the issue-step's own filters ----
#
# Found live via IG-2's real schedule-triggered dispatch on c3cdao-landing
# (run 33799427136): a repo issue with body: null crashed the find-loop's
# jq filter with "null (null) and string (...) cannot have their
# containment checked", failing the whole export-bundle job — and the
# null body existed in the first place because the create-branch's own
# jq invocation bound `.body` against the `-n` flag's null input instead
# of the `--argjson body` variable, so every created issue had body: null.
# Both bugs are silent at the string-assertion level above (they only
# surface when jq actually runs), so these tests execute the real jq
# filters extracted from the step's own script — not a hand-copied
# duplicate that could drift from the fix.


def _extract_single_quoted(pattern: str, run: str) -> str:
    match = re.search(pattern, run)
    assert match, f"pattern not found in issue step run script: {pattern!r}"
    return match.group(1)


def _find_loop_filter() -> str:
    run = _issue_step()["run"]
    return _extract_single_quoted(r"jq -r --arg marker \"\$marker\" '([^']+)'", run)


def _create_body_filter() -> str:
    run = _issue_step()["run"]
    return _extract_single_quoted(
        r"jq -n --arg title \"Security scan results — scheduled\" --argjson body \"\$issue_body\" '([^']+)'",
        run,
    )


def test_find_loop_jq_filter_tolerates_a_null_body_issue():
    """An issue with body: null (exactly what the create-branch bug used
    to produce) must not crash the marker search — it must be skipped,
    and a later issue whose body actually contains the marker must still
    be found."""
    resp = json.dumps(
        [
            {"number": 5, "pull_request": None, "body": None},
            {
                "number": 7,
                "pull_request": None,
                "body": "stuff <!-- security-export-issue --> more",
            },
        ]
    )
    result = subprocess.run(
        ["jq", "-r", "--arg", "marker", ISSUE_MARKER, _find_loop_filter()],
        input=resp,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "7"


def test_create_body_jq_filter_binds_the_argjson_variable_not_null_input():
    """jq -n sets the implicit input document to null — `.body` on that
    input is null regardless of what --argjson body carries. The filter
    must reference the bound variable ($body.body), not the null input,
    or every created issue silently gets body: null forever."""
    issue_body = json.dumps({"body": "real tracking-issue content"})
    result = subprocess.run(
        [
            "jq",
            "-n",
            "--arg",
            "title",
            "Security scan results — scheduled",
            "--argjson",
            "body",
            issue_body,
            _create_body_filter(),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    created = json.loads(result.stdout)
    assert created["body"] == "real tracking-issue content"
