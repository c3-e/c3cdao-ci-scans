"""Cross-checks docs/INPUTS.md's hand-authored reference against the
reusable workflow's real workflow_call inputs/secrets."""

import re
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
INPUTS_DOC = REPO_ROOT / "docs" / "INPUTS.md"
README = REPO_ROOT / "README.md"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "reusable-security-gate.yml"

MARKER_STEM = "GENERATED: security-gate-inputs"


def _workflow_call() -> dict:
    wf = yaml.safe_load(WORKFLOW.read_text())
    return wf[True]["workflow_call"]  # YAML 1.1 parses bare `on` as True


def test_all_inputs_documented():
    """Every workflow_call input appears in docs/INPUTS.md."""
    text = INPUTS_DOC.read_text()
    missing = {k for k in _workflow_call()["inputs"] if f"`{k}`" not in text}
    assert not missing, f"inputs absent from docs/INPUTS.md: {sorted(missing)}"


def test_all_secrets_documented():
    """Every workflow_call secret appears in docs/INPUTS.md."""
    text = INPUTS_DOC.read_text()
    missing = {k for k in _workflow_call()["secrets"] if f"`{k}`" not in text}
    assert not missing, f"secrets absent from docs/INPUTS.md: {sorted(missing)}"


def test_defaults_documented():
    """Every non-empty input default appears in the doc's field reference."""
    text = INPUTS_DOC.read_text()
    for name, spec in _workflow_call()["inputs"].items():
        default = spec.get("default")
        shown = ("true" if default else "false") if isinstance(default, bool) else str(default)
        if shown:
            assert shown in text, f"default {shown!r} for input {name!r} not documented"


def test_no_generated_markers_remain():
    """The retired generator's marker block is gone from the doc set."""
    assert MARKER_STEM not in INPUTS_DOC.read_text()
    assert MARKER_STEM not in README.read_text()


def test_removed_inputs_migration_table_present():
    """v0.5 consumers get a by-name migration table for deleted inputs."""
    text = INPUTS_DOC.read_text()
    assert re.search(r"^## Removed inputs", text, re.MULTILINE)
    for name in ("contract_file", "scan_image", "require_hardened_bases"):
        assert f"`{name}`" in text, f"removed input {name!r} missing from the migration table"


def test_readme_pointer():
    """The README points readers at docs/INPUTS.md."""
    assert "docs/INPUTS.md" in README.read_text()


if __name__ == "__main__":
    sys.exit(subprocess.call(["pytest", "-q", __file__]))
