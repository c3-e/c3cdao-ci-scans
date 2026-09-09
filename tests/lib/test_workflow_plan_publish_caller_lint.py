"""Contract + functional tests for the plan job's "Lint publish-staging-chart
caller, if present" step on .github/workflows/reusable-security-gate.yml.

publish-staging-chart.yml only ever runs post-merge (pull_request/closed),
so its own fail-closed chart-shape/routes-contract check — and
lint_caller_publish.py's caller-shape rules — never blocked a PR before
merge; a consumer only discovered a violation (e.g. no non-empty
`routes:`) once the merge had already happened (the exact c3cdao-petegpt
PR #31 failure this step exists to catch earlier). This step runs
lint_caller_publish.py against the consumer's own publish-staging-chart
caller (if one exists) inside the every-PR gate, so the same findings
surface pre-merge instead.

This extracts the step's actual `run:` script from the workflow file
(same style as test_hook_detect.py / test_callee_ref_resolver.py) and
executes it against synthetic consumer checkouts, with `.ci-scans`
symlinked back to this repo so the real (unmodified) lint_caller_publish.py
+ lint_rules run end to end, not a mock.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "reusable-security-gate.yml"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "callers_publish"

STEP_NAME = "Lint publish-staging-chart caller, if present"


def _plan_steps() -> list[dict]:
    return yaml.safe_load(WORKFLOW.read_text())["jobs"]["plan"]["steps"]


def _step() -> dict:
    return next(s for s in _plan_steps() if s.get("name") == STEP_NAME)


def _script() -> str:
    return _step()["run"]


def _make_consumer(tmp_path: Path, caller_fixture: str | None) -> Path:
    """A synthetic consumer checkout: .ci-scans symlinked to this repo (so
    the step's `uv run .ci-scans/scripts/lib/lint_caller_publish.py` call
    resolves to the real, unmodified script), plus an optional caller
    workflow file copied in from tests/fixtures/callers_publish/.
    """
    consumer = tmp_path / "consumer"
    (consumer / ".github" / "workflows").mkdir(parents=True)
    (consumer / ".ci-scans").symlink_to(REPO_ROOT, target_is_directory=True)
    if caller_fixture is not None:
        text = (FIXTURES / caller_fixture).read_text()
        (consumer / ".github" / "workflows" / "publish-staging-chart-caller.yml").write_text(
            text
        )
    return consumer


def _run(consumer: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c", _script()],
        cwd=consumer,
        env={**os.environ, "GITHUB_WORKSPACE": str(consumer)},
        capture_output=True,
        text=True,
    )


# --- static contract: placement + no accidental hard requirement --------------


def test_step_exists_after_gate_caller_lint_and_before_bom_derivation():
    steps = _plan_steps()
    names = [s.get("name") for s in steps]
    assert "Lint caller against v0.6 conventions" in names
    assert STEP_NAME in names
    assert "Derive bake plan + annotated BOM" in names
    gate_idx = names.index("Lint caller against v0.6 conventions")
    publish_idx = names.index(STEP_NAME)
    bom_idx = names.index("Derive bake plan + annotated BOM")
    assert gate_idx < publish_idx < bom_idx


def test_step_has_no_continue_on_error():
    """Same blocking posture as the security-gate caller lint next to it —
    a real caller-shape bug (e.g. an unpinned ref) must fail the PR gate,
    not just print a warning that's easy to miss."""
    assert "continue-on-error" not in _step()


def test_step_invokes_lint_caller_publish_with_consumer_root():
    text = _script()
    assert ".ci-scans/scripts/lib/lint_caller_publish.py" in text
    assert "--consumer-root" in text


# --- functional: real lint_caller_publish.py, real fixtures -------------------


def test_no_caller_present_skips_cleanly(tmp_path):
    consumer = _make_consumer(tmp_path, caller_fixture=None)
    result = _run(consumer)
    assert result.returncode == 0, result.stderr
    assert "no publish-staging-chart caller found" in result.stdout


def test_clean_caller_passes(tmp_path):
    consumer = _make_consumer(tmp_path, "clean-minimal.yml")
    result = _run(consumer)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "caller lint clean" in result.stdout


@pytest.mark.parametrize(
    "bad_fixture,expected_rule",
    [
        ("bad-unpinned-ref.yml", "publish-ref-pin"),
        ("bad-decoy-job.yml", "publish-decoy-job"),
        ("bad-both-permission-levels.yml", "publish-permissions-both-levels"),
    ],
)
def test_block_level_violation_fails_the_step(tmp_path, bad_fixture, expected_rule):
    consumer = _make_consumer(tmp_path, bad_fixture)
    result = _run(consumer)
    assert result.returncode != 0
    assert expected_rule in result.stdout


def test_missing_routes_warns_but_does_not_block(tmp_path):
    """The exact c3cdao-petegpt PR #31 scenario: a clean caller whose
    chart_path values.yaml declares no non-empty routes: must warn, not
    fail the gate — publish-chart-routes-missing is warn-only by design
    (a brand-new pilot's chart may not exist yet at lint time)."""
    consumer = _make_consumer(tmp_path, "clean-minimal.yml")
    chart_dir = consumer / "chart"
    chart_dir.mkdir()
    (chart_dir / "values.yaml").write_text("routes: []\n")
    result = _run(consumer)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "publish-chart-routes-missing" in result.stdout
    assert "warn" in result.stdout


def test_non_empty_routes_reports_no_warning(tmp_path):
    consumer = _make_consumer(tmp_path, "clean-minimal.yml")
    chart_dir = consumer / "chart"
    chart_dir.mkdir()
    (chart_dir / "values.yaml").write_text("routes:\n  - path: /agents/example\n")
    result = _run(consumer)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "publish-chart-routes-missing" not in result.stdout


def test_finds_caller_regardless_of_filename(tmp_path):
    """Discovery matches by uses:, not by a fixed filename convention —
    the template names it publish-staging-chart-caller.yml, but nothing
    enforces that name."""
    consumer = _make_consumer(tmp_path, caller_fixture=None)
    text = (FIXTURES / "clean-minimal.yml").read_text()
    (consumer / ".github" / "workflows" / "some-other-name.yml").write_text(text)
    result = _run(consumer)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "caller lint clean" in result.stdout


def test_ignores_unrelated_workflow_files(tmp_path):
    consumer = _make_consumer(tmp_path, caller_fixture=None)
    (consumer / ".github" / "workflows" / "unrelated.yml").write_text(
        "name: Unrelated\non:\n  push: {}\njobs:\n  build:\n    runs-on: ubuntu-latest\n"
        "    steps:\n      - run: echo hi\n"
    )
    result = _run(consumer)
    assert result.returncode == 0, result.stderr
    assert "no publish-staging-chart caller found" in result.stdout
