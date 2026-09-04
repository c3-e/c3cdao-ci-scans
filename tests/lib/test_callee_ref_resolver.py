"""Executes each workflow's "Resolve callee (ci-scans) ref" step verbatim
against fixture callers, parametrized across all three copies (kept as
one shared, hardened script so a fix to one can't drift from the others).

Covers: single resolver site per workflow, fail-closed on an unresolvable
pin (no silent default to main), and quote/comment/sha parsing. Decoy-job
protection is enforced by lint_caller.py / lint_caller_publish.py, not
tested here.
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
    # caller path is derived from WORKFLOW_REF relative to CWD, so run with
    # the fixture's own directory as cwd and a bare filename in WORKFLOW_REF.
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
    """External caller with unparseable pin and no job_workflow_sha must fail
    closed with a named error, never silently default to main."""
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
    """ci-scans' own fixture/selftest callers may still resolve to main;
    everyone else fails closed (see test above)."""
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
    """A name field mentioning the filename must not be mistaken for a pin;
    only uses: counts. job_wf_sha is empty to force the parse fallback."""
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
