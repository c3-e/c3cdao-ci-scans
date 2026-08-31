"""The callee-ref resolver is a single site (plan job only), consumed by
every other job via needs.plan.outputs.callee_ref — not duplicated per
job. This guard extracts plan's "Resolve callee (ci-scans) ref" step in
full (not just its yq line, since the fail-closed logic below it spans
several lines) and executes it against fixture callers with real env
vars, exactly as the step itself runs.

Covers three properties of this resolver:
  A decoy job can't hijack which ref it resolves from: out of scope for
    THIS test module — enforced by the new decoy-gate-job lint rule
    (test_lint_rules.py), not by the resolver itself. There is no
    reliable runtime signal here for "which caller job is actually
    executing", so the fix is structural (at most one candidate can ever
    exist in a passing caller) rather than a smarter parse.
  Fail-closed: an external caller with an unresolvable pin and no
    job_workflow_sha fails the run with a named error instead of silently
    defaulting to main. ci-scans' own fixture callers keep the main
    fallback (gated on GITHUB_REPOSITORY) since they intentionally
    exercise this workflow against itself.
  Single site: asserted directly — exactly one resolver step exists in
    the whole workflow file.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "reusable-security-gate.yml"

STEP_NAME = "Resolve callee (ci-scans) ref"


def _resolver_steps() -> list[dict]:
    jobs = yaml.safe_load(WORKFLOW.read_text())["jobs"]
    return [
        step
        for job in jobs.values()
        for step in job.get("steps", [])
        if step.get("name") == STEP_NAME
    ]


def _resolver_script() -> str:
    (step,) = _resolver_steps()
    return step["run"]


def _run(
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
        ["bash", "-c", _resolver_script()],
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


def test_single_resolver_site():
    """Exactly one resolver step in the whole workflow (plan only)."""
    assert len(_resolver_steps()) == 1


def test_resolver_ignores_commented_pins(tmp_path):
    caller = tmp_path / "security-gate.yml"
    caller.write_text(
        "jobs:\n"
        "  security-scan:\n"
        "    # uses: c3-e/c3cdao-ci-scans/.github/workflows/"
        "reusable-security-gate.yml@v0.4.0\n"
        "    uses: c3-e/c3cdao-ci-scans/.github/workflows/"
        "reusable-security-gate.yml@v0.5.1  # pinned\n"
    )
    result = _run(caller)
    assert result.returncode == 0, result.stderr
    assert _output_ref(caller) == "v0.5.1"


def test_resolver_strips_quotes(tmp_path):
    caller = tmp_path / "security-gate.yml"
    caller.write_text(
        "jobs:\n"
        "  security-scan:\n"
        '    uses: "c3-e/c3cdao-ci-scans/.github/workflows/'
        'reusable-security-gate.yml@v0.5.1"\n'
    )
    result = _run(caller)
    assert result.returncode == 0, result.stderr
    assert _output_ref(caller) == "v0.5.1"


def test_resolver_handles_real_sha_pin(tmp_path):
    caller = tmp_path / "security-gate.yml"
    caller.write_text(
        "jobs:\n"
        "  security-scan:\n"
        "    uses: c3-e/c3cdao-ci-scans/.github/workflows/"
        "reusable-security-gate.yml"
        "@4c23da8d296cc7f519cabf8023df8d9933da95b2  # v0.7.4\n"
    )
    result = _run(caller)
    assert result.returncode == 0, result.stderr
    assert _output_ref(caller) == "4c23da8d296cc7f519cabf8023df8d9933da95b2"


def test_resolver_prefers_job_workflow_sha_over_parse(tmp_path):
    caller = tmp_path / "security-gate.yml"
    caller.write_text(
        "jobs:\n"
        "  security-scan:\n"
        "    uses: c3-e/c3cdao-ci-scans/.github/workflows/"
        "reusable-security-gate.yml@v0.5.1\n"
    )
    result = _run(caller, job_wf_sha="3" * 40)
    assert result.returncode == 0, result.stderr
    assert _output_ref(caller) == "3" * 40


def test_resolver_fails_closed_for_external_caller_with_no_signal(tmp_path):
    """An external pilot whose pin can't be parsed and has no
    job_workflow_sha must fail the run with a named error, never
    silently default to main."""
    caller = tmp_path / "security-gate.yml"
    caller.write_text(
        "jobs:\n"
        "  security-scan:\n"
        "    uses: >-\n"
        "      c3-e/c3cdao-ci-scans/.github/workflows/reusable-security-gate.yml\n"
        "      @v0.5.1\n"
    )
    result = _run(caller, repository="c3-e/some-pilot", job_wf_sha="")
    assert result.returncode != 0
    assert "could not resolve" in result.stdout
    assert _output_ref(caller) == ""


def test_resolver_falls_back_to_main_only_for_ci_scans_itself(tmp_path):
    """The fail-closed carve-out: ci-scans' own fixture/selftest callers
    may still resolve to main when nothing else is available — everyone
    else fails closed (see test above)."""
    caller = tmp_path / "security-gate.yml"
    caller.write_text(
        "jobs:\n"
        "  security-scan:\n"
        "    uses: >-\n"
        "      c3-e/c3cdao-ci-scans/.github/workflows/reusable-security-gate.yml\n"
        "      @v0.5.1\n"
    )
    result = _run(caller, repository="c3-e/c3cdao-ci-scans", job_wf_sha="")
    assert result.returncode == 0, result.stderr
    assert _output_ref(caller) == "main"


def test_resolver_ignores_non_uses_text_mentioning_the_filename(tmp_path):
    """A job/step name that happens to mention the filename must not be
    mistaken for a real pin — only a uses: value counts. job_wf_sha is
    deliberately empty so the yq parse fallback actually runs; otherwise
    job_workflow_sha would short-circuit before the parse ever executes."""
    caller = tmp_path / "security-gate.yml"
    caller.write_text(
        "jobs:\n"
        "  docs-job:\n"
        '    name: "See reusable-security-gate.yml@v9.9.9 for details"\n'
        "    uses: actions/checkout@v4\n"
    )
    result = _run(caller, repository="c3-e/c3cdao-ci-scans", job_wf_sha="")
    assert result.returncode == 0, result.stdout
    assert _output_ref(caller) == "main"
