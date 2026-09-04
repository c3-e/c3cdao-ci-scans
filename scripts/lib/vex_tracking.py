#!/usr/bin/env python3
"""Pending-disposition age tracker: carry each undispositioned CVE's first-seen
date across scan runs.

Not OpenVEX. Scanner-level VEX suppression is handled natively (Grype
GRYPE_VEX_DOCUMENTS / Trivy vulnerability.vex); this only answers "how long has
this finding been pending a human verdict", which no VEX standard models. Output
is a plain cve->{first_seen,last_seen} map (see SCHEMA_KIND).
"""

import json
import sys
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

SCHEMA_VERSION = 1
SCHEMA_KIND = "c3cdao-ci-scans/pending-disposition-tracking"


def _get_cve_id(finding: Dict[str, Any]) -> Optional[str]:
    """CVE id from a Trivy (VulnerabilityID) or Grype (vulnerability.id) finding."""
    # Grype's real export has no vulnerability.name, only .id — reading .name
    # here silently dropped every Grype finding.
    if "VulnerabilityID" in finding:
        return finding["VulnerabilityID"]

    if "vulnerability" in finding and isinstance(finding["vulnerability"], dict):
        vuln_id = finding["vulnerability"].get("id")
        if vuln_id:
            return vuln_id

    return None


def _extract_human_dispositions(vex_doc: Optional[Dict[str, Any]]) -> set:
    """CVE ids carrying a human verdict in an OpenVEX doc (excludes under_investigation)."""
    if not vex_doc or not isinstance(vex_doc, dict):
        return set()

    dispositioned = set()
    for statement in vex_doc.get("statements", []):
        status = statement.get("status", "").lower()
        if status in ("not_affected", "affected", "fixed"):
            vuln = statement.get("vulnerability", {})
            if isinstance(vuln, dict) and vuln.get("name"):
                dispositioned.add(vuln["name"])

    return dispositioned


def _current_clock() -> str:
    """Current UTC time as an ISO8601 'Z' string."""
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def merge(
    prior_doc: Optional[Dict[str, Any]],
    current_findings: List[Dict[str, Any]],
    human_disposition_doc: Optional[Dict[str, Any]],
    clock: Optional[Callable[[], str]] = None,
) -> Dict[str, Any]:
    """Merge current findings into the prior tracking record.

    Keeps each undispositioned CVE's first_seen from prior_doc (or stamps now for
    new ones), refreshes last_seen, and drops CVEs the human doc already covers.
    """
    if clock is None:
        clock = _current_clock
    now_str = clock() if callable(clock) else str(clock)

    prior_findings = {}
    if prior_doc and isinstance(prior_doc, dict):
        prior_findings = prior_doc.get("findings") or {}

    human_dispositioned = _extract_human_dispositions(human_disposition_doc)

    findings_out: Dict[str, Dict[str, str]] = {}
    for finding in current_findings:
        cve_id = _get_cve_id(finding)
        if not cve_id or cve_id in findings_out or cve_id in human_dispositioned:
            continue
        prior_entry = prior_findings.get(cve_id) or {}
        findings_out[cve_id] = {
            "first_seen": prior_entry.get("first_seen") or now_str,
            "last_seen": now_str,
        }

    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": SCHEMA_KIND,
        "generated": now_str,
        "findings": findings_out,
    }


def _load_findings_file(path: str) -> List[Dict[str, Any]]:
    """Load one Trivy- or Grype-shaped JSON export as a flat findings list.

    '-' means this scanner's export was unavailable this run and yields [].
    """
    if path == "-":
        return []

    with open(path) as f:
        findings_json = json.load(f)

    # Trivy: {"Results": [{"Vulnerabilities": [...]}]}. Grype: {"matches": [...]}.
    if isinstance(findings_json, dict):
        if "Results" in findings_json:
            out: List[Dict[str, Any]] = []
            for result in findings_json["Results"] or []:
                out.extend(result.get("Vulnerabilities") or [])
            return out
        if "matches" in findings_json:
            return findings_json["matches"] or []
        return []
    if isinstance(findings_json, list):
        return findings_json
    return []


def main():
    """CLI: merge prior + current (Trivy AND Grype, always both) + dispositions to stdout."""
    if len(sys.argv) != 5:
        print(
            "Usage: vex_tracking.py <prior-doc|-> <trivy-findings|-> "
            "<grype-findings|-> <human-disposition-doc|->",
            file=sys.stderr,
        )
        print("  '-' means absent. Both scanner paths are read and combined.", file=sys.stderr)
        sys.exit(1)

    prior_path, trivy_path, grype_path, disposition_path = sys.argv[1:]

    prior_doc = None
    if prior_path != "-":
        try:
            with open(prior_path) as f:
                prior_doc = json.load(f)
        except FileNotFoundError:
            pass

    try:
        current_findings = _load_findings_file(trivy_path) + _load_findings_file(grype_path)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error loading current findings (trivy={trivy_path}, grype={grype_path}): {e}", file=sys.stderr)
        sys.exit(1)

    disposition_doc = None
    if disposition_path != "-":
        try:
            with open(disposition_path) as f:
                disposition_doc = json.load(f)
        except FileNotFoundError:
            pass

    merged_doc = merge(prior_doc, current_findings, disposition_doc)
    print(json.dumps(merged_doc, indent=2))


if __name__ == "__main__":
    main()
