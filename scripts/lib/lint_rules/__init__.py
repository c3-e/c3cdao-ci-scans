"""Verdict infrastructure shared by the v0.6 convention lint rule modules.

Every rule finding is one verdict object; `block` fails the run, `warn` is
reported and never blocks. Remediation refs point at onboarding-doc anchors
authored at the docs cutover (anchor names are stable now).
"""

from __future__ import annotations

Verdict = dict[str, str]

ONBOARDING_DOC = "docs/CI-CONTRACT.md"


def verdict(rule_id: str, message: str, level: str = "block") -> Verdict:
    return {
        "rule_id": rule_id,
        "level": level,
        "message": message,
        "remediation_ref": f"{ONBOARDING_DOC}#rule-{rule_id}",
    }
