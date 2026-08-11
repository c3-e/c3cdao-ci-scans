"""Unit tests for the build-matrix emission (emit_build_matrix.py).

Plan fixtures are the same real `bake --print` captures test_derive_bom.py
uses (tests/fixtures/bake/) — never hand-authored. This module was
previously an inline Python heredoc in reusable-security-gate.yml with no
ruff/mypy coverage and no test; extracting it to scripts/lib/ closes that
gap.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

from emit_build_matrix import build_matrix, main  # noqa: E402

FIXTURES = REPO_ROOT / "tests" / "fixtures" / "bake"
N3 = FIXTURES / "n3-local-profile"
N1 = FIXTURES / "n1"


def _load_plan(fixture_dir: Path) -> dict:
    return json.loads((fixture_dir / "bake-print.json").read_text())


def test_single_target_matrix_and_source_sbom_target():
    matrix, source_sbom_target = build_matrix(_load_plan(N1))
    assert matrix == [
        {
            "target": "app",
            "tag": "bake-spike/app:0.1.0",
            "dockerfile": "Dockerfile",
            "context": ".",
        }
    ]
    assert source_sbom_target == "app"


def test_multi_target_matrix_sorted_by_name():
    matrix, source_sbom_target = build_matrix(_load_plan(N3))
    assert [entry["target"] for entry in matrix] == ["svc-a", "svc-b", "svc-c"]
    assert matrix[0] == {
        "target": "svc-a",
        "tag": "bake-spike/svc-a:0.1.0",
        "dockerfile": "Dockerfile",
        "context": ".",
    }
    # Designated source-SBOM leg is the first target in sorted order.
    assert source_sbom_target == "svc-a"


def test_matrix_uses_first_tag_and_defaults_dockerfile_context():
    plan = {
        "target": {
            "svc": {
                "tags": ["repo/svc:1.0.0", "repo/svc:latest"],
            }
        }
    }
    matrix, source_sbom_target = build_matrix(plan)
    assert matrix == [
        {
            "target": "svc",
            "tag": "repo/svc:1.0.0",
            "dockerfile": "Dockerfile",
            "context": ".",
        }
    ]
    assert source_sbom_target == "svc"


def test_main_writes_github_output_and_prints_matrix(tmp_path, capsys):
    plan_path = tmp_path / "bake-plan.json"
    plan_path.write_text(json.dumps(_load_plan(N1)))
    output_path = tmp_path / "github_output"
    output_path.write_text("")
    os.environ["GITHUB_OUTPUT"] = str(output_path)
    try:
        rc = main([str(plan_path)])
    finally:
        del os.environ["GITHUB_OUTPUT"]
    assert rc == 0
    written = output_path.read_text()
    assert 'matrix=[{"target":"app","tag":"bake-spike/app:0.1.0"' in written
    assert "source_sbom_target=app" in written
    captured = capsys.readouterr()
    assert "plan: build matrix:" in captured.out
    assert "plan: source-SBOM leg: app" in captured.out


def test_main_requires_exactly_one_arg():
    try:
        main([])
        raised = False
    except SystemExit:
        raised = True
    assert raised
