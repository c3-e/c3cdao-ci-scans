"""Guards the README as a slim landing page, not a full runbook."""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
README = REPO_ROOT / "README.md"


def _text() -> str:
    return README.read_text()


def test_no_deprecated_secret_spellings():
    """No deprecated `*_IDENTITY` / `*_CLI_SECRET` spellings remain."""
    text = _text()
    assert "_CLI_SECRET" not in text
    assert "_IDENTITY" not in text


def test_readme_under_110_lines():
    """README stays a landing page, not a full runbook."""
    line_count = len(README.read_text().splitlines())
    assert line_count <= 110, f"README has {line_count} lines (> 110)"


def test_ruleset_named_plainly():
    """The ruleset step names a GitHub repository ruleset."""
    assert "repository ruleset" in _text().lower()


def test_prereqs_reference_contract():
    """Prerequisites reference the derived consumer contract."""
    text = _text()
    assert "docker-compose" in text or "Compose" in text
    assert "docs/CI-CONTRACT.md" in text


def test_caller_lint_framed():
    """caller-lint is framed as a pre-flight config check."""
    text = _text().lower()
    assert "pre-flight" in text or "configuration" in text


def test_links_docs_pages():
    """README links all three docs pages."""
    text = _text()
    assert "docs/INPUTS.md" in text
    assert "docs/RUNBOOK.md" in text
    assert "docs/REQUIREMENTS-MAP.md" in text


def test_required_check_preserved():
    """The one required-check name is preserved verbatim."""
    assert "security-scan / Security Gate" in _text()


if __name__ == "__main__":
    sys.exit(subprocess.call(["pytest", "-q", __file__]))
