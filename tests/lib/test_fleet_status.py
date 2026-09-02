"""Unit tests for fleet_status.py's pure logic (no network calls).

The gh-api-calling functions aren't covered here — they're exercised for
real every time someone runs the script itself, and mocking `gh` output
convincingly would test the mock more than the code. This covers the two
functions a caller-file edit is most likely to silently break: pin
extraction (a real bug this session — resolving the ref against the wrong
repo) and markdown rendering.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "fleet_status", ROOT / "scripts" / "fleet_status.py"
)
fleet_status = importlib.util.module_from_spec(SPEC)
sys.modules["fleet_status"] = fleet_status
SPEC.loader.exec_module(fleet_status)


def test_extract_pin_from_sha_pin():
    content = (
        "    uses: c3-e/c3cdao-ci-scans/.github/workflows/"
        "reusable-security-gate.yml@a86b1141bff6f5028e75e01e7181d83c00e9b6f6  # main\n"
    )
    assert (
        fleet_status._extract_pin(content)
        == "a86b1141bff6f5028e75e01e7181d83c00e9b6f6"
    )


def test_extract_pin_from_tag_pin_strips_comment():
    content = (
        "    uses: c3-e/c3cdao-ci-scans/.github/workflows/"
        "reusable-security-gate.yml@4c23da8d296cc7f519cabf8023df8d9933da95b2  # v0.7.4\n"
    )
    assert (
        fleet_status._extract_pin(content)
        == "4c23da8d296cc7f519cabf8023df8d9933da95b2"
    )


def test_extract_pin_returns_none_when_no_uses_line():
    assert fleet_status._extract_pin("name: Security Scan\non:\n  pull_request:\n") is None


def test_extract_pin_ignores_unrelated_uses_lines():
    content = "    uses: actions/checkout@v4\n"
    assert fleet_status._extract_pin(content) is None


def test_render_markdown_produces_one_row_per_input():
    rows = [
        {
            "pilot": "petegpt",
            "branch": "main",
            "gate_pin": "abc123 @ abc123ab",
            "hook_mechanism": "yes",
            "publish_contract": "compose_file (current)",
            "vex": "yes",
            "ruleset": "evaluate",
            "last_run": "2026-09-01 (success)",
        }
    ]
    table = fleet_status.render_markdown(rows)
    lines = table.splitlines()
    assert len(lines) == 3  # header + separator + 1 row
    assert "petegpt" in lines[2]
    assert "compose_file (current)" in lines[2]
