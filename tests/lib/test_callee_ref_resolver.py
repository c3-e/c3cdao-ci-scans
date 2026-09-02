"""The callee-ref resolver is a single site per workflow file (the first
job that needs the ci-scans checkout), consumed by later jobs via
needs.<job>.outputs.<ref-output> — not duplicated per job. This guard
extracts each workflow's "Resolve callee (ci-scans) ref" step in full
(not just its yq line, since the fail-closed logic below it spans several
lines) and executes it against fixture callers with real env vars,
exactly as the step itself runs.

Parametrized over all three copies of this resolver
(reusable-security-gate.yml, publish-staging-chart.yml,
composed-smoke.yml) — kept as one shared, hardened script across all
three so a fix to one can't silently drift from the others. Was two
separate modules (this file, only covering reusable-security-gate.yml;
test_callee_ref_resolver_publish.py, covering the other two with a
weaker, line-only extraction, because those two copies predated the
fail-closed hardening below). Folded into one now that all three copies
carry the same hardening.

Covers three properties of each resolver:
  A decoy job can't hijack which ref it resolves from: out of scope for
    THIS test module — enforced by lint_caller.py's decoy-gate-job rule
    (reusable-security-gate.yml callers) and lint_caller_publish.py's
    publish-decoy-job rule (publish-staging-chart.yml callers), not by
    the resolver itself. There is no reliable runtime signal here for
    "which caller job is actually executing", so the fix is structural
    (at most one candidate can ever exist in a passing caller) rather
    than a smarter parse. composed-smoke.yml callers have no equivalent
    lint rule yet — a separate, not-yet-built gap, not covered here.
  Fail-closed: an external caller with an unresolvable pin and no
    job_workflow_sha fails the run with a named error instead of silently
    defaulting to main. ci-scans' own fixture callers keep the main
    fallback (gated on GITHUB_REPOSITORY) since they intentionally
    exercise these workflows against themselves.
  Single site: asserted directly — exactly one resolver step exists per
    workflow file.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

STEP_NAME = "Resolve callee (ci-scans) ref"
WORKFLOW_FILENAMES = [
    "reusable-security-gate.yml",
    "publish-staging-chart.yml",
    "composed-smoke.yml",
]


def _resolver_steps(workflow_filename: str) -> list[dict]:
    jobs = yaml.safe_load((WORKFLOWS_DIR / workflow_filename).read_text())["jobs"]
    return [
        step
        for job in jobs.values()
        for step in job.get("steps", [])
        if step.get("name") == STEP_NAME
    ]


def _resolver_script(workflow_filename: str) -> str:
    (step,) = _resolver_steps(workflow_filename)
    return step["run"]


def _run(
    workflow_filename: str,
    caller: Path,
    *,
    repository: str = "c3-e/some-pilot",
    workflow_ref: str | None = None,
    job_wf_sha: str = "",
) -> subprocess.CompletedProcess:
    if workflow_ref is None:
        workflow_ref = f"{repository}/{caller.name}@feature-branch"
    env = {
        **os.environ,
        "GITHUB_REPOSITORY": repository,
        "GITHUB_OUTPUT": str(caller.with_suffix(".output")),
        "WORKFLOW_REF": workflow_ref,
        "JOB_WF_SHA": job_wf_sha,
    }
    # The real caller path is derived from WORKFLOW_REF relative to CWD
    # (see `caller="${WORKFLOW_REF#...}"`), so run with the fixture's own
    # directory as cwd and a bare filename in WORKFLOW_REF.
    return subprocess.run(
        ["bash", "-c", _resolver_script(workflow_filename)],
        cwd=caller.parent,
        env=env,
        capture_output=True,
        text=True,
    )


def _output_ref(caller: Path) -> str:
    output_file = caller.with_suffix(".output")
    text = output_file.read_text() if output_file.exists() else ""
    for line in text.splitlines():
        if line.startswith("ref="):
            return line[len("ref="):]
    return ""


@pytest.mark.parametrize("workflow_filename", WORKFLOW_FILENAMES)
def test_single_resolver_site(workflow_filename):
    """Exactly one resolver step per workflow file."""
    assert len(_resolver_steps(workflow_filename)) == 1


@pytest.mark.parametrize("workflow_filename", WORKFLOW_FILENAMES)
def test_resolver_ignores_commented_pins(workflow_filename, tmp_path):
    stem = workflow_filename.removesuffix(".yml")
    caller = tmp_path / "caller.yml"
    caller.write_text(
        "jobs:\n"
        "  some-job:\n"
        f"    # uses: c3-e/c3cdao-ci-scans/.github/workflows/{stem}.yml@v0.4.0\n"
        f"    uses: c3-e/c3cdao-ci-scans/.github/workflows/{stem}.yml@v0.5.1  # pinned\n"
    )
    result = _run(workflow_filename, caller)
    assert result.returncode == 0, result.stderr
    assert _output_ref(caller) == "v0.5.1"


@pytest.mark.parametrize("workflow_filename", WORKFLOW_FILENAMES)
def test_resolver_strips_quotes(workflow_filename, tmp_path):
    stem = workflow_filename.removesuffix(".yml")
    caller = tmp_path / "caller.yml"
    caller.write_text(
        "jobs:\n"
        "  some-job:\n"
        f'    uses: "c3-e/c3cdao-ci-scans/.github/workflows/{stem}.yml@v0.5.1"\n'
    )
    result = _run(workflow_filename, caller)
    assert result.returncode == 0, result.stderr
    assert _output_ref(caller) == "v0.5.1"


@pytest.mark.parametrize("workflow_filename", WORKFLOW_FILENAMES)
def test_resolver_handles_real_sha_pin(workflow_filename, tmp_path):
    stem = workflow_filename.removesuffix(".yml")
    caller = tmp_path / "caller.yml"
    caller.write_text(
        "jobs:\n"
        "  some-job:\n"
        f"    uses: c3-e/c3cdao-ci-scans/.github/workflows/{stem}.yml"
        "@4c23da8d296cc7f519cabf8023df8d9933da95b2  # v0.7.4\n"
    )
    result = _run(workflow_filename, caller)
    assert result.returncode == 0, result.stderr
    assert _output_ref(caller) == "4c23da8d296cc7f519cabf8023df8d9933da95b2"


@pytest.mark.parametrize("workflow_filename", WORKFLOW_FILENAMES)
def test_resolver_prefers_job_workflow_sha_over_parse(workflow_filename, tmp_path):
    stem = workflow_filename.removesuffix(".yml")
    caller = tmp_path / "caller.yml"
    caller.write_text(
        "jobs:\n"
        "  some-job:\n"
        f"    uses: c3-e/c3cdao-ci-scans/.github/workflows/{stem}.yml@v0.5.1\n"
    )
    result = _run(workflow_filename, caller, job_wf_sha="3" * 40)
    assert result.returncode == 0, result.stderr
    assert _output_ref(caller) == "3" * 40


@pytest.mark.parametrize("workflow_filename", WORKFLOW_FILENAMES)
def test_resolver_fails_closed_for_external_caller_with_no_signal(
    workflow_filename, tmp_path
):
    """An external pilot whose pin can't be parsed and has no
    job_workflow_sha must fail the run with a named error, never
    silently default to main."""
    stem = workflow_filename.removesuffix(".yml")
    caller = tmp_path / "caller.yml"
    caller.write_text(
        "jobs:\n"
        "  some-job:\n"
        "    uses: >-\n"
        f"      c3-e/c3cdao-ci-scans/.github/workflows/{stem}.yml\n"
        "      @v0.5.1\n"
    )
    result = _run(workflow_filename, caller, repository="c3-e/some-pilot", job_wf_sha="")
    assert result.returncode != 0
    assert "could not resolve" in result.stdout
    assert _output_ref(caller) == ""


@pytest.mark.parametrize("workflow_filename", WORKFLOW_FILENAMES)
def test_resolver_falls_back_to_main_only_for_ci_scans_itself(
    workflow_filename, tmp_path
):
    """The fail-closed carve-out: ci-scans' own fixture/selftest callers
    may still resolve to main when nothing else is available — everyone
    else fails closed (see test above)."""
    stem = workflow_filename.removesuffix(".yml")
    caller = tmp_path / "caller.yml"
    caller.write_text(
        "jobs:\n"
        "  some-job:\n"
        "    uses: >-\n"
        f"      c3-e/c3cdao-ci-scans/.github/workflows/{stem}.yml\n"
        "      @v0.5.1\n"
    )
    result = _run(
        workflow_filename, caller, repository="c3-e/c3cdao-ci-scans", job_wf_sha=""
    )
    assert result.returncode == 0, result.stderr
    assert _output_ref(caller) == "main"


@pytest.mark.parametrize("workflow_filename", WORKFLOW_FILENAMES)
def test_resolver_ignores_non_uses_text_mentioning_the_filename(
    workflow_filename, tmp_path
):
    """A job/step name that happens to mention the filename must not be
    mistaken for a real pin — only a uses: value counts. job_wf_sha is
    deliberately empty so the yq parse fallback actually runs; otherwise
    job_workflow_sha would short-circuit before the parse ever executes."""
    caller = tmp_path / "caller.yml"
    caller.write_text(
        "jobs:\n"
        "  docs-job:\n"
        f'    name: "See {workflow_filename}@v9.9.9 for details"\n'
        "    uses: actions/checkout@v4\n"
    )
    result = _run(
        workflow_filename, caller, repository="c3-e/c3cdao-ci-scans", job_wf_sha=""
    )
    assert result.returncode == 0, result.stdout
    assert _output_ref(caller) == "main"
