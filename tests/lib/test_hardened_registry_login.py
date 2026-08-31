"""Hardened-registry login: declared-tier scoping + fail-closed exit-status.

Two things this module guards, both real bugs/gaps found by fleet survey:

1. (bug) `login_retry`'s exit status was never checked — the step
   unconditionally printed "authenticated" and set the ok-flag whenever a
   credential was merely *present*, regardless of whether the docker login
   actually succeeded. That defeats the fail-closed
   require-hardened-bases check below it.
2. (design gap) the action always attempted both Chainguard and Iron Bank
   logins even for a pilot pinned to exactly one hardened registry, wasting
   retry/backoff time on a registry it never uses. `hardened-base-registry`
   (chainguard | ironbank | both, default both) lets the caller declare its
   actual tier so the unused registry's login is never attempted at all.

Same approach as tests/lib/test_callee_ref_resolver.py: extract the real
`run:` script from the action YAML (not a reimplementation) and execute it
for real via subprocess, against a stub `docker` (and a no-op `sleep`, so
the retry/backoff loop doesn't actually sleep) placed on PATH.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
ACTION = REPO_ROOT / ".github" / "actions" / "hardened-registry-login" / "action.yml"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "reusable-security-gate.yml"

IRONBANK_REGISTRY = "registry1.dso.mil"


def _action() -> dict:
    return yaml.safe_load(ACTION.read_text())


def _login_step() -> dict:
    steps = _action()["runs"]["steps"]
    matches = [s for s in steps if s.get("name") == "Login and resolve base images"]
    assert len(matches) == 1, "expected exactly one 'Login and resolve base images' step"
    return matches[0]


def _login_script() -> str:
    return _login_step()["run"]


# --- structural: input declared correctly -----------------------------------


def test_action_declares_hardened_base_registry_input_default_both():
    inputs = _action()["inputs"]
    assert "hardened-base-registry" in inputs
    spec = inputs["hardened-base-registry"]
    assert spec.get("required", False) is False
    assert spec.get("default") == "both"


def test_workflow_declares_hardened_base_registry_input_default_both():
    wf = yaml.safe_load(WORKFLOW.read_text())
    call = wf[True]["workflow_call"]  # YAML 1.1 parses bare `on` as True
    assert "hardened_base_registry" in call["inputs"]
    spec = call["inputs"]["hardened_base_registry"]
    assert spec["type"] == "string"
    assert spec["default"] == "both"
    desc = spec["description"].lower()
    for value in ("chainguard", "ironbank", "both"):
        assert value in desc, f"allowed value {value!r} not documented in description"


def test_both_call_sites_thread_the_new_input():
    text = WORKFLOW.read_text()
    occurrences = text.count("hardened-base-registry: ${{ inputs.hardened_base_registry }}")
    assert occurrences == 2, (
        f"expected both hardened-registry-login call sites to pass "
        f"hardened-base-registry, found {occurrences}"
    )


# --- behavioral: extract + execute the real script ---------------------------


def _write_stub(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _make_bin_dir(tmp_path: Path) -> Path:
    """A stub `docker` (records invocations, exit code per-registry
    configurable via env) and a no-op `sleep` (so login_retry's real
    15/30/60s backoff never actually sleeps in the test)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_stub(
        bin_dir / "docker",
        "#!/usr/bin/env bash\n"
        'printf "%s\\n" "$*" >> "$DOCKER_LOG"\n'
        'if [ "$1" = "login" ]; then\n'
        '  case "$2" in\n'
        '    cgr.dev) exit "${CGR_LOGIN_EXIT:-0}" ;;\n'
        f'    {IRONBANK_REGISTRY}) exit "${{IB_LOGIN_EXIT:-0}}" ;;\n'
        "  esac\n"
        "fi\n"
        "exit 0\n",
    )
    _write_stub(bin_dir / "sleep", "#!/usr/bin/env bash\nexit 0\n")
    return bin_dir


def run_login_script(
    tmp_path: Path,
    *,
    hardened_base_registry: str = "both",
    cgr_token: str = "",
    ib_token: str = "",
    cgr_login_exit: int = 0,
    ib_login_exit: int = 0,
    require_hardened_bases: str = "true",
) -> tuple[subprocess.CompletedProcess, list[str], str]:
    bin_dir = _make_bin_dir(tmp_path)
    docker_log = tmp_path / "docker.log"
    docker_log.write_text("")
    gh_output = tmp_path / "github_output"
    gh_output.write_text("")

    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "DOCKER_LOG": str(docker_log),
        "GITHUB_OUTPUT": str(gh_output),
        "CGR_LOGIN_EXIT": str(cgr_login_exit),
        "IB_LOGIN_EXIT": str(ib_login_exit),
        "CGR_PULL_TOKEN": cgr_token,
        "CGR_PULL_USERNAME": "cgr-user",
        "IRONBANK_TOKEN": ib_token,
        "IRONBANK_USERNAME": "ib-user",
        "IRONBANK_REGISTRY": IRONBANK_REGISTRY,
        "BUILDER_IMAGE_IN": "cgr.dev/chainguard/python:latest-dev",
        "RUNTIME_IMAGE_IN": "cgr.dev/chainguard/python:latest",
        "IB_BUILDER_IMAGE": "",
        "IB_RUNTIME_IMAGE": "",
        "REQUIRE_HARDENED_BASES": require_hardened_bases,
        "HARDENED_BASE_REGISTRY": hardened_base_registry,
    }
    result = subprocess.run(
        ["bash", "-c", _login_script()],
        capture_output=True,
        text=True,
        env=env,
    )
    invocations = [line for line in docker_log.read_text().splitlines() if line]
    return result, invocations, gh_output.read_text()


def test_chainguard_tier_only_attempts_chainguard_login(tmp_path):
    """Both credentials present, but the tier is chainguard-only: Iron Bank
    must never even be invoked."""
    result, invocations, _ = run_login_script(
        tmp_path,
        hardened_base_registry="chainguard",
        cgr_token="cgr-tok",
        ib_token="ib-tok",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert any("login cgr.dev" in line for line in invocations)
    assert not any(IRONBANK_REGISTRY in line for line in invocations), (
        f"Iron Bank must not be attempted under hardened-base-registry=chainguard: {invocations}"
    )
    assert "Chainguard (cgr.dev) authenticated" in result.stdout
    assert "Iron Bank" not in result.stdout


def test_chainguard_tier_login_failure_fails_closed_and_is_not_reported_authenticated(tmp_path):
    """Regression test for the exit-status bug: a failed docker login under
    a chainguard-only tier must not be reported as authenticated, and (since
    Iron Bank is never attempted) must fail the run closed."""
    result, invocations, _ = run_login_script(
        tmp_path,
        hardened_base_registry="chainguard",
        cgr_token="cgr-tok",
        cgr_login_exit=1,
    )
    assert any("login cgr.dev" in line for line in invocations)
    assert "authenticated" not in result.stdout
    assert result.returncode != 0, "no successful login under a scoped tier must fail closed"
    assert "::error::" in result.stdout


def test_ironbank_tier_only_attempts_ironbank_login(tmp_path):
    result, invocations, _ = run_login_script(
        tmp_path,
        hardened_base_registry="ironbank",
        cgr_token="cgr-tok",
        ib_token="ib-tok",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert any(IRONBANK_REGISTRY in line for line in invocations)
    assert not any("login cgr.dev" in line for line in invocations), (
        f"Chainguard must not be attempted under hardened-base-registry=ironbank: {invocations}"
    )
    assert f"Iron Bank ({IRONBANK_REGISTRY}) authenticated" in result.stdout
    assert "Chainguard" not in result.stdout


def test_ironbank_tier_login_failure_fails_closed_and_is_not_reported_authenticated(tmp_path):
    result, invocations, _ = run_login_script(
        tmp_path,
        hardened_base_registry="ironbank",
        ib_token="ib-tok",
        ib_login_exit=1,
    )
    assert any(IRONBANK_REGISTRY in line for line in invocations)
    assert "authenticated" not in result.stdout
    assert result.returncode != 0
    assert "::error::" in result.stdout


def test_both_tier_attempts_both_by_default(tmp_path):
    result, invocations, _ = run_login_script(
        tmp_path,
        hardened_base_registry="both",
        cgr_token="cgr-tok",
        ib_token="ib-tok",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert any("login cgr.dev" in line for line in invocations)
    assert any(IRONBANK_REGISTRY in line for line in invocations)
    assert "Chainguard (cgr.dev) authenticated" in result.stdout
    assert f"Iron Bank ({IRONBANK_REGISTRY}) authenticated" in result.stdout


def test_both_tier_one_failure_one_success_still_passes(tmp_path):
    """At-least-one semantics: a failure on one attempted registry with a
    success on the other must still pass under the default tier."""
    result, invocations, _ = run_login_script(
        tmp_path,
        hardened_base_registry="both",
        cgr_token="cgr-tok",
        ib_token="ib-tok",
        cgr_login_exit=1,
        ib_login_exit=0,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Chainguard (cgr.dev) authenticated" not in result.stdout
    assert f"Iron Bank ({IRONBANK_REGISTRY}) authenticated" in result.stdout


def test_both_tier_total_failure_fails_closed(tmp_path):
    """Regression test for the exit-status bug: both registries attempted,
    both logins fail -> must fail closed, neither reported authenticated."""
    result, invocations, _ = run_login_script(
        tmp_path,
        hardened_base_registry="both",
        cgr_token="cgr-tok",
        ib_token="ib-tok",
        cgr_login_exit=1,
        ib_login_exit=1,
    )
    assert any("login cgr.dev" in line for line in invocations)
    assert any(IRONBANK_REGISTRY in line for line in invocations)
    assert "authenticated" not in result.stdout
    assert result.returncode != 0
    assert "::error::" in result.stdout


def test_warn_posture_still_no_false_authenticated_claim(tmp_path):
    """With require_hardened_bases=false the run doesn't fail, but a failed
    login must still never be reported as authenticated (the bug's exact
    shape: ok-flag set unconditionally on credential presence)."""
    result, invocations, _ = run_login_script(
        tmp_path,
        hardened_base_registry="chainguard",
        cgr_token="cgr-tok",
        cgr_login_exit=1,
        require_hardened_bases="false",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "authenticated" not in result.stdout
    assert "::warning::" in result.stdout
