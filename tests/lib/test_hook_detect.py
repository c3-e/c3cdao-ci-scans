"""helm.sh/hook: test detection must be a real yq parse, not a text grep —
a `grep -qE 'helm\\.sh/hook:.*test'` missed a quoted annotation key
(`"helm.sh/hook": test`), a real bug found twice during pilot onboarding.
This extracts the step's actual run script and executes it against real
rendered-chart fixtures, covering:

  - an unquoted annotation key (the case the old grep did handle)
  - a quoted annotation key (the case the old grep missed)
  - a hook value combined with another hook type (still a match)
  - no helm.sh/hook annotation anywhere in the rendered chart
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "reusable-security-gate.yml"

STEP_ID = "hook-detect"
RENDERED_PATH = Path("/tmp/rendered-chart.yaml")


def _step() -> dict:
    jobs = yaml.safe_load(WORKFLOW.read_text())["jobs"]
    steps = jobs["cluster-smoke"]["steps"]
    return next(s for s in steps if s.get("id") == STEP_ID)


def _script() -> str:
    return _step()["run"]


def _run(rendered_yaml: str, tmp_path: Path) -> tuple[subprocess.CompletedProcess, str]:
    RENDERED_PATH.write_text(rendered_yaml)
    output_file = tmp_path / "output"
    env = {**os.environ, "GITHUB_OUTPUT": str(output_file)}
    result = subprocess.run(
        ["bash", "-c", _script()],
        env=env,
        capture_output=True,
        text=True,
    )
    output_text = output_file.read_text() if output_file.exists() else ""
    return result, output_text


def _found(output_text: str) -> str:
    for line in output_text.splitlines():
        if line.startswith("found="):
            return line[len("found="):]
    return ""


def test_step_is_a_real_yq_parse_not_a_text_grep():
    active_lines = [
        line
        for line in _script().splitlines()
        if not line.strip().startswith("#")
    ]
    active_text = "\n".join(active_lines)
    assert "yq" in active_text
    assert "grep -qE 'helm\\.sh/hook" not in active_text


def test_unquoted_hook_key_detected(tmp_path):
    rendered = """\
apiVersion: v1
kind: Pod
metadata:
  name: a
  annotations:
    helm.sh/hook: test
"""
    result, output = _run(rendered, tmp_path)
    assert result.returncode == 0, result.stderr
    assert _found(output) == "true"


def test_quoted_hook_key_detected(tmp_path):
    """The exact bug the old grep missed: a quoted annotation key."""
    rendered = """\
apiVersion: v1
kind: Pod
metadata:
  name: a
  annotations:
    "helm.sh/hook": test
"""
    result, output = _run(rendered, tmp_path)
    assert result.returncode == 0, result.stderr
    assert _found(output) == "true"


def test_hook_value_combined_with_another_hook_type_detected(tmp_path):
    """`helm.sh/hook: pre-install,test` is valid Helm — "test" is one of
    several comma-separated hook types on the same resource."""
    rendered = """\
apiVersion: v1
kind: Pod
metadata:
  name: a
  annotations:
    helm.sh/hook: pre-install,test
"""
    result, output = _run(rendered, tmp_path)
    assert result.returncode == 0, result.stderr
    assert _found(output) == "true"


def test_no_hook_present_not_detected(tmp_path):
    rendered = """\
apiVersion: v1
kind: Deployment
metadata:
  name: a
  annotations:
    other: value
---
apiVersion: v1
kind: Service
metadata:
  name: b
"""
    result, output = _run(rendered, tmp_path)
    assert result.returncode == 0, result.stderr
    assert _found(output) == "false"


def test_legacy_helm2_test_success_value_does_not_match():
    """Helm 3 only recognizes the exact value "test"; a naive substring
    match would wrongly match Helm 2's legacy "test-success"."""
    rendered = """\
apiVersion: v1
kind: Pod
metadata:
  name: a
  annotations:
    helm.sh/hook: test-success
"""
    RENDERED_PATH.write_text(rendered)
    result = subprocess.run(
        ["bash", "-c", _script()],
        env={**os.environ, "GITHUB_OUTPUT": "/tmp/hook-detect-legacy.output"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    out = Path("/tmp/hook-detect-legacy.output").read_text()
    assert _found(out) == "false"
