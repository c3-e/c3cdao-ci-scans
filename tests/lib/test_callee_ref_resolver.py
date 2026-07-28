"""The callee-ref resolver appears once per gate job — guard against drift.

The reusable workflow resolves which ci-scans ref to check its own scripts
and composite actions out at by parsing the caller's `uses:` pin (see the
"Resolve callee (ci-scans) ref" steps). The block is duplicated per job, so
this guard asserts (a) every copy is byte-identical and (b) the parse line
only matches real `uses:` lines — a commented-out old pin must never win.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "reusable-security-gate.yml"

RESOLVER_LINE_RE = re.compile(r'^\s*ref="\$\(grep .*reusable-security-gate.*$')


def resolver_lines() -> list[str]:
    return [
        line.strip()
        for line in WORKFLOW.read_text().splitlines()
        if RESOLVER_LINE_RE.match(line)
    ]


def test_resolver_sites_identical():
    lines = resolver_lines()
    assert len(lines) == 5, f"expected 5 resolver sites, found {len(lines)}"
    assert len(set(lines)) == 1, "resolver sites drifted:\n" + "\n".join(set(lines))


def test_resolver_ignores_commented_pins(tmp_path):
    """A commented-out old pin above the live one must not hijack the ref."""
    caller = tmp_path / "security-gate.yml"
    caller.write_text(
        "jobs:\n"
        "  security-scan:\n"
        "    # uses: c3-e/c3cdao-ci-scans/.github/workflows/"
        "reusable-security-gate.yml@v0.4.0\n"
        "    uses: c3-e/c3cdao-ci-scans/.github/workflows/"
        "reusable-security-gate.yml@v0.5.1  # pinned\n"
    )
    (line,) = set(resolver_lines())
    # Execute the workflow's own parse line verbatim against the fixture.
    script = line.replace('"$caller"', f'"{caller}"')
    ref = subprocess.run(
        ["bash", "-c", script + '; printf %s "$ref"'],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert ref == "v0.5.1", f"resolver picked {ref!r} (commented pin hijack?)"


def test_resolver_strips_quotes(tmp_path):
    """The YAML-legal quoted form must not leak the quote into the ref."""
    caller = tmp_path / "security-gate.yml"
    caller.write_text(
        "jobs:\n"
        "  security-scan:\n"
        '    uses: "c3-e/c3cdao-ci-scans/.github/workflows/'
        'reusable-security-gate.yml@v0.5.1"\n'
    )
    (line,) = set(resolver_lines())
    script = line.replace('"$caller"', f'"{caller}"')
    ref = subprocess.run(
        ["bash", "-c", script + '; printf %s "$ref"'],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert ref == "v0.5.1", f"resolver picked {ref!r} (quote leak?)"
