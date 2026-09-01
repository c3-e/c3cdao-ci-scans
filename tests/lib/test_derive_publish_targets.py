"""Behavioral tests for publish-staging-chart.yml's derive-publish-targets
job (Issue I: single source of truth for the publish target list).

Same extraction pattern as test_callee_ref_resolver.py: pull the job's
"Derive publish targets from compose_file (no hand-typed images:)" step's
real run script out of the workflow YAML and execute it against real
compose fixtures under tests/fixtures/bake/ via a real `docker buildx
bake --print` + derive_bom.py invocation (no mocking) -- the same
fixtures test_lint_rules.py/test_derive_bom.py already use, so a future
edit to those fixtures is caught here too.

Requires `docker buildx` on PATH; skipped otherwise (CI runners always
have it, matching this repo's other bake-dependent tests).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "publish-staging-chart.yml"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "bake"

STEP_NAME = "Derive publish targets from compose_file (no hand-typed images:)"

requires_buildx = pytest.mark.skipif(
    shutil.which("docker") is None
    or subprocess.run(
        ["docker", "buildx", "version"], capture_output=True
    ).returncode
    != 0,
    reason="docker buildx not available",
)


def _step() -> dict:
    jobs = yaml.safe_load(WORKFLOW.read_text())["jobs"]
    steps = jobs["derive-publish-targets"]["steps"]
    return next(s for s in steps if s.get("name") == STEP_NAME)


def _script() -> str:
    return _step()["run"]


def _run(
    workspace: Path,
    compose_file: str,
    publish_targets: str = "",
) -> tuple[subprocess.CompletedProcess, str]:
    output_file = workspace / "output.txt"
    env = {
        **os.environ,
        "GITHUB_WORKSPACE": str(workspace),
        "GATE_COMPOSE_FILE": compose_file,
        "PUBLISH_TARGETS": publish_targets,
        "GITHUB_OUTPUT": str(output_file),
    }
    result = subprocess.run(
        ["bash", "-c", _script()],
        cwd=workspace,
        env=env,
        capture_output=True,
        text=True,
    )
    output_text = output_file.read_text() if output_file.exists() else ""
    return result, output_text


def _targets(output_text: str) -> list[str] | None:
    for line in output_text.splitlines():
        if line.startswith("targets="):
            return json.loads(line[len("targets="):])
    return None


def _workspace_for(fixture_dir: Path, tmp_path: Path) -> Path:
    """derive_bom.py is invoked via `.ci-scans/scripts/lib/derive_bom.py`
    relative to $GITHUB_WORKSPACE -- symlink this checkout in as
    `.ci-scans` (the same tree the real "Resolve callee (ci-scans) ref" +
    checkout steps produce) and copy the fixture's compose file in
    alongside it, exactly like the real job's own two checkouts land."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".ci-scans").symlink_to(REPO_ROOT)
    shutil.copy(fixture_dir / "docker-compose.yml", workspace / "docker-compose.yml")
    dockerfile = fixture_dir / "Dockerfile"
    if dockerfile.is_file():
        shutil.copy(dockerfile, workspace / "Dockerfile")
    return workspace


def test_step_reuses_derive_bom_not_a_reimplementation():
    text = _script()
    assert "derive_bom.py" in text
    assert "images-quarantine" not in text  # that's publish-images-deferred's job


@requires_buildx
def test_single_target_fixture_with_no_allow_list(tmp_path):
    workspace = _workspace_for(FIXTURES / "layered-args", tmp_path)
    result, output = _run(workspace, "docker-compose.yml")
    assert result.returncode == 0, result.stderr
    assert _targets(output) == ["layered"]


@requires_buildx
def test_multi_target_fixture_publishes_all_non_local_targets_by_default(tmp_path):
    """svc-local (profiles: [local]) must never appear -- same exclusion
    reusable-security-gate.yml's own plan job enforces."""
    workspace = _workspace_for(FIXTURES / "n3-local-profile", tmp_path)
    result, output = _run(workspace, "docker-compose.yml")
    assert result.returncode == 0, result.stderr
    assert _targets(output) == ["svc-a", "svc-b", "svc-c"]


@requires_buildx
def test_allow_list_filters_to_named_subset(tmp_path):
    workspace = _workspace_for(FIXTURES / "n3-local-profile", tmp_path)
    result, output = _run(workspace, "docker-compose.yml", publish_targets="svc-a, svc-c")
    assert result.returncode == 0, result.stderr
    assert _targets(output) == ["svc-a", "svc-c"]


@requires_buildx
def test_allow_list_naming_an_unknown_target_fails_closed(tmp_path):
    workspace = _workspace_for(FIXTURES / "n3-local-profile", tmp_path)
    result, output = _run(
        workspace, "docker-compose.yml", publish_targets="svc-a,not-a-real-target"
    )
    assert result.returncode == 1
    assert _targets(output) is None
    assert "::error::" in result.stdout
    assert "not-a-real-target" in result.stdout
    assert "svc-a" in result.stdout  # names the real available list too


@requires_buildx
def test_allow_list_naming_the_local_profile_excluded_target_fails_closed(tmp_path):
    """svc-local is a real compose service but never a publishable
    target (profiles: [local]) -- naming it in publish_targets must fail
    the same way an entirely unknown name does, not silently pass."""
    workspace = _workspace_for(FIXTURES / "n3-local-profile", tmp_path)
    result, output = _run(workspace, "docker-compose.yml", publish_targets="svc-local")
    assert result.returncode == 1
    assert _targets(output) is None
    assert "svc-local" in result.stdout
