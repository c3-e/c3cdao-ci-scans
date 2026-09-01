"""Verdict infrastructure shared by the v0.6 convention lint rule modules.

Every rule finding is one verdict object; `block` fails the run, `warn` is
reported and never blocks. Remediation refs point at the rule table in the
onboarding doc (one heading per rule id).

Also home to `load_gha_workflow`, the shared GitHub Actions workflow
loader used by the caller lint.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

Verdict = dict[str, str]

ONBOARDING_DOC = "docs/CI-CONTRACT.md"


def verdict(
    rule_id: str, message: str, level: str = "block", doc: str = ONBOARDING_DOC
) -> Verdict:
    """`doc` lets a second lint module (e.g. the publish-staging-chart
    caller lint) point its remediation_ref at its own rule-table doc
    instead of the security-gate's docs/CI-CONTRACT.md default."""
    return {
        "rule_id": rule_id,
        "level": level,
        "message": message,
        "remediation_ref": f"{doc}#rule-{rule_id}",
    }


def load_gha_workflow(path: Path) -> dict[str, Any]:
    """Parse a GitHub Actions workflow YAML with the trigger key normalized.

    PyYAML (YAML 1.1) parses a bare ``on:`` key as boolean ``True``, so a
    workflow's triggers land under the key ``True`` instead of ``"on"``.
    This helper resolves that quirk in exactly one place: the returned dict
    always carries the triggers under ``"on"``. Side-effect-free, PyYAML
    only — safe to import from sibling scripts.
    """
    try:
        wf = yaml.safe_load(path.read_text())
    except OSError as e:
        raise SystemExit(f"error: {path}: {e}") from e
    except yaml.YAMLError as e:
        raise SystemExit(f"error: {path}: unparseable workflow: {e}") from e
    if not isinstance(wf, dict):
        raise SystemExit(f"error: {path}: workflow must be a YAML mapping")
    wf["on"] = wf.get("on") or wf.pop(True, None)
    return wf
