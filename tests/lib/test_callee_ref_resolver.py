"""The callee-ref resolver appears once per gate job — guard against drift.

The reusable workflow resolves which ci-scans ref to check its own scripts
and composite actions out at by parsing the caller's `uses:` pin (see the
"Resolve callee (ci-scans) ref" steps). It queries the caller file as real
YAML via `yq` (only `uses:`-keyed values, matched against the workflow's
own filename) rather than grep+sed against the raw text — comments and
quoting are handled by the YAML parser itself, not by hand-written
character-class hacks. The block is duplicated per job, so this guard
asserts (a) every copy is byte-identical and (b) the parse only matches a
real `uses:` value, never a commented-out old pin or unrelated text that
happens to mention the filename.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "reusable-security-gate.yml"

RESOLVER_LINE_RE = re.compile(r'^\s*ref="\$\(yq .*reusable-security-gate.*$')


def resolver_lines() -> list[str]:
    return [
        line.strip()
        for line in WORKFLOW.read_text().splitlines()
        if RESOLVER_LINE_RE.match(line)
    ]


def _resolve(caller: Path) -> str:
    """Execute the workflow's own parse line verbatim against a fixture."""
    (line,) = set(resolver_lines())
    script = line.replace('"$caller"', f'"{caller}"')
    return subprocess.run(
        ["bash", "-c", script + '; printf %s "$ref"'],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def test_resolver_sites_identical():
    lines = resolver_lines()
    assert len(lines) == 7, f"expected 7 resolver sites, found {len(lines)}"
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
    assert _resolve(caller) == "v0.5.1"


def test_resolver_strips_quotes(tmp_path):
    """The YAML-legal quoted form must not leak the quote into the ref."""
    caller = tmp_path / "security-gate.yml"
    caller.write_text(
        "jobs:\n"
        "  security-scan:\n"
        '    uses: "c3-e/c3cdao-ci-scans/.github/workflows/'
        'reusable-security-gate.yml@v0.5.1"\n'
    )
    assert _resolve(caller) == "v0.5.1"


def test_resolver_ignores_non_uses_text_mentioning_the_filename(tmp_path):
    """A job/step name that happens to mention the filename must not be
    mistaken for a real pin — only a `uses:` value counts."""
    caller = tmp_path / "security-gate.yml"
    caller.write_text(
        "jobs:\n"
        "  docs-job:\n"
        '    name: "See reusable-security-gate.yml@v9.9.9 for details"\n'
        "    uses: actions/checkout@v4\n"
    )
    assert _resolve(caller) == ""


def test_resolver_handles_real_sha_pin(tmp_path):
    caller = tmp_path / "security-gate.yml"
    caller.write_text(
        "jobs:\n"
        "  security-scan:\n"
        "    uses: c3-e/c3cdao-ci-scans/.github/workflows/"
        "reusable-security-gate.yml"
        "@4c23da8d296cc7f519cabf8023df8d9933da95b2  # v0.7.4\n"
    )
    assert _resolve(caller) == "4c23da8d296cc7f519cabf8023df8d9933da95b2"
