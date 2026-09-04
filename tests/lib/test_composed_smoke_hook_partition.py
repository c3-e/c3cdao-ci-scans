"""composed-smoke.yml's per-pilot hook-partitioning step needs the same
real-yq-parse fix as cluster-smoke's hook-detect step (test_hook_detect.py),
not the old text-grep version. This runs the step's actual script against
real minimal charts rendered by `helm template`, covering:

  - an unquoted annotation key
  - a quoted annotation key (the case the old grep missed)
  - a hook value combined with another hook type
  - no helm.sh/hook annotation anywhere in the rendered chart
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "composed-smoke.yml"

STEP_NAME = "Partition composed pilots by helm.sh/hook test resources"


def _step() -> dict:
    jobs = yaml.safe_load(WORKFLOW.read_text())["jobs"]
    for job in jobs.values():
        for step in job.get("steps", []):
            if step.get("name") == STEP_NAME:
                return step
    raise AssertionError(f"step {STEP_NAME!r} not found")


def _script() -> str:
    return _step()["run"]


def _make_chart(root: Path, name: str, annotation_line: str | None) -> None:
    chart_dir = root / "charts" / name
    (chart_dir / "templates").mkdir(parents=True)
    (chart_dir / "Chart.yaml").write_text(
        f"apiVersion: v2\nname: {name}\nversion: 0.1.0\n"
    )
    annotations_block = (
        f"  annotations:\n    {annotation_line}\n" if annotation_line else ""
    )
    (chart_dir / "templates" / "pod.yaml").write_text(
        "apiVersion: v1\n"
        "kind: Pod\n"
        "metadata:\n"
        f"  name: {name}-probe\n"
        f"{annotations_block}"
        "spec:\n"
        "  containers:\n"
        "  - name: c\n"
        "    image: busybox\n"
    )


def _run(tmp_path: Path, pilots: list[str]) -> subprocess.CompletedProcess:
    pilots_jsonl = "\n".join(json.dumps({"name": p}) for p in pilots) + "\n"
    Path("/tmp/pilots.jsonl").write_text(pilots_jsonl)
    for p in ["/tmp/hook-pilots.txt", "/tmp/nohook-pilots.txt"]:
        Path(p).unlink(missing_ok=True)
    env = {**os.environ, "NAMESPACE": "smoke-ns"}
    return subprocess.run(
        ["bash", "-c", _script()],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )


def _lines(path: str) -> list[str]:
    p = Path(path)
    return p.read_text().splitlines() if p.exists() else []


def test_step_is_a_real_yq_parse_not_a_text_grep():
    text = _script()
    assert "yq" in text
    assert "grep -qE 'helm\\.sh/hook" not in text


def test_unquoted_hook_key_partitions_as_hook_bearing(tmp_path):
    _make_chart(tmp_path, "pilot-a", "helm.sh/hook: test")
    result = _run(tmp_path, ["pilot-a"])
    assert result.returncode == 0, result.stderr
    assert _lines("/tmp/hook-pilots.txt") == ["pilot-a"]
    assert _lines("/tmp/nohook-pilots.txt") == []


def test_quoted_hook_key_partitions_as_hook_bearing(tmp_path):
    """The exact bug the old grep missed: a quoted annotation key."""
    _make_chart(tmp_path, "pilot-b", '"helm.sh/hook": test')
    result = _run(tmp_path, ["pilot-b"])
    assert result.returncode == 0, result.stderr
    assert _lines("/tmp/hook-pilots.txt") == ["pilot-b"]
    assert _lines("/tmp/nohook-pilots.txt") == []


def test_combined_hook_value_partitions_as_hook_bearing(tmp_path):
    _make_chart(tmp_path, "pilot-c", "helm.sh/hook: pre-install,test")
    result = _run(tmp_path, ["pilot-c"])
    assert result.returncode == 0, result.stderr
    assert _lines("/tmp/hook-pilots.txt") == ["pilot-c"]
    assert _lines("/tmp/nohook-pilots.txt") == []


def test_no_hook_partitions_as_hook_less(tmp_path):
    _make_chart(tmp_path, "pilot-d", None)
    result = _run(tmp_path, ["pilot-d"])
    assert result.returncode == 0, result.stderr
    assert _lines("/tmp/hook-pilots.txt") == []
    assert _lines("/tmp/nohook-pilots.txt") == ["pilot-d"]


def test_mixed_hook_and_hookless_pilots_partition_independently(tmp_path):
    _make_chart(tmp_path, "pilot-e", "helm.sh/hook: test")
    _make_chart(tmp_path, "pilot-f", None)
    result = _run(tmp_path, ["pilot-e", "pilot-f"])
    assert result.returncode == 0, result.stderr
    assert _lines("/tmp/hook-pilots.txt") == ["pilot-e"]
    assert _lines("/tmp/nohook-pilots.txt") == ["pilot-f"]
