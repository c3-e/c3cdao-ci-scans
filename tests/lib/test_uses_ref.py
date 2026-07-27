"""Unit tests for the uses-ref pin rule."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

from lint_caller import check_uses_ref

USES = "c3-e/c3cdao-ci-scans/.github/workflows/reusable-security-gate.yml"


def test_pinned_tag_ok(capsys):
    assert check_uses_ref("security-scan", f"{USES}@v0.5.1") == []
    assert capsys.readouterr().err == ""


def test_main_ok_with_notice(capsys):
    assert check_uses_ref("security-scan", f"{USES}@main") == []
    err = capsys.readouterr().err
    assert "notice: warn: uses-ref" in err
    assert "pilot-window only" in err


def test_missing_ref_violation():
    (violation,) = check_uses_ref("security-scan", USES)
    assert violation.startswith("uses-ref:")
    assert "no @ref" in violation


@pytest.mark.parametrize("ref", ["vX.Y.Z", "EDIT-ME", "<release-tag>", ""])
def test_placeholder_or_empty_ref_violation(ref):
    (violation,) = check_uses_ref("security-scan", f"{USES}@{ref}")
    assert violation.startswith("uses-ref:")


if __name__ == "__main__":
    raise SystemExit(pytest.main(["-q", __file__]))
