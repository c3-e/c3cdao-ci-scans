"""Callee-ref resolver drift guard for publish-staging-chart.yml and
composed-smoke.yml.

Same mechanism as tests/lib/test_callee_ref_resolver.py (which covers
reusable-security-gate.yml's 7 copies) applied to the two resolver sites
this PR adds. Kept as a separate module rather than folded into that one:
this branch predates the yq-based resolver fix landing on
reusable-security-gate.yml (a separate, already-merged-or-merging PR), so
generalizing the shared test now would assume file content this branch
doesn't have yet. Fold the two into one parametrized module once this
branch is rebased past that fix.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

WORKFLOWS = ["publish-staging-chart.yml", "composed-smoke.yml"]


def resolver_lines(workflow_filename: str) -> list[str]:
    stem = re.escape(workflow_filename.removesuffix(".yml"))
    pattern = re.compile(rf'^\s*ref="\$\(yq .*{stem}.*$')
    text = (WORKFLOWS_DIR / workflow_filename).read_text()
    return [line.strip() for line in text.splitlines() if pattern.match(line)]


def _resolve(workflow_filename: str, caller: Path) -> str:
    (line,) = set(resolver_lines(workflow_filename))
    script = line.replace('"$caller"', f'"{caller}"')
    return subprocess.run(
        ["bash", "-c", script + '; printf %s "$ref"'],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


@pytest.mark.parametrize("workflow_filename", WORKFLOWS)
def test_resolver_site_present_once(workflow_filename):
    assert len(resolver_lines(workflow_filename)) == 1


@pytest.mark.parametrize("workflow_filename", WORKFLOWS)
def test_resolver_ignores_commented_pins(workflow_filename, tmp_path):
    stem = workflow_filename.removesuffix(".yml")
    caller = tmp_path / "caller.yml"
    caller.write_text(
        "jobs:\n"
        "  some-job:\n"
        f"    # uses: c3-e/c3cdao-ci-scans/.github/workflows/{stem}.yml@v0.4.0\n"
        f"    uses: c3-e/c3cdao-ci-scans/.github/workflows/{stem}.yml@v0.5.1  # pinned\n"
    )
    assert _resolve(workflow_filename, caller) == "v0.5.1"


@pytest.mark.parametrize("workflow_filename", WORKFLOWS)
def test_resolver_strips_quotes(workflow_filename, tmp_path):
    stem = workflow_filename.removesuffix(".yml")
    caller = tmp_path / "caller.yml"
    caller.write_text(
        "jobs:\n"
        "  some-job:\n"
        f'    uses: "c3-e/c3cdao-ci-scans/.github/workflows/{stem}.yml@v0.5.1"\n'
    )
    assert _resolve(workflow_filename, caller) == "v0.5.1"


@pytest.mark.parametrize("workflow_filename", WORKFLOWS)
def test_resolver_handles_real_sha_pin(workflow_filename, tmp_path):
    stem = workflow_filename.removesuffix(".yml")
    caller = tmp_path / "caller.yml"
    caller.write_text(
        "jobs:\n"
        "  some-job:\n"
        f"    uses: c3-e/c3cdao-ci-scans/.github/workflows/{stem}.yml"
        "@4c23da8d296cc7f519cabf8023df8d9933da95b2  # v0.7.4\n"
    )
    assert _resolve(workflow_filename, caller) == "4c23da8d296cc7f519cabf8023df8d9933da95b2"
