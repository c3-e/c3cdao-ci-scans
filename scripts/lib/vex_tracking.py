#!/usr/bin/env python3
"""
VEX tracking document merge: combine prior tracking state with current scan findings.

Preserves first_issued timestamps across runs for undispositioned findings,
excludes findings already covered by human verdicts.
"""

import json
import sys
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional


def _get_cve_id(finding: Dict[str, Any]) -> Optional[str]:
    """Extract CVE ID from a Trivy or Grype finding dict.

    Handles both formats:
    - Trivy: finding['VulnerabilityID']
    - Grype: finding['vulnerability']['name']
    """
    # Try Trivy format
    if "VulnerabilityID" in finding:
        return finding["VulnerabilityID"]

    # Try Grype format
    if "vulnerability" in finding and isinstance(finding["vulnerability"], dict):
        vuln_name = finding["vulnerability"].get("name")
        if vuln_name:
            return vuln_name

    return None


def _extract_human_dispositions(vex_doc: Optional[Dict[str, Any]]) -> set:
    """Extract the set of CVE IDs already covered by human dispositions.

    A human disposition is a statement in an OpenVEX doc with a status
    of 'not_affected', 'affected', or 'fixed'.
    """
    if not vex_doc or not isinstance(vex_doc, dict):
        return set()

    dispositioned = set()
    statements = vex_doc.get("statements", [])

    for statement in statements:
        # Only count statements with human verdicts (non-investigational)
        status = statement.get("status", "").lower()
        if status in ("not_affected", "affected", "fixed"):
            vuln = statement.get("vulnerability", {})
            if isinstance(vuln, dict):
                cve_name = vuln.get("name")
                if cve_name:
                    dispositioned.add(cve_name)

    return dispositioned


def _current_clock() -> str:
    """Return current UTC time as ISO8601 string."""
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def merge(
    prior_doc: Optional[Dict[str, Any]],
    current_findings: List[Dict[str, Any]],
    human_disposition_doc: Optional[Dict[str, Any]],
    clock: Optional[Callable[[], str]] = None,
) -> Dict[str, Any]:
    """
    Merge current scan findings into prior tracking record.

    Args:
        prior_doc: Prior VEX tracking document (or None for first run).
        current_findings: List of findings from current Trivy/Grype scan.
        human_disposition_doc: Human-authored OpenVEX verdicts to exclude.
        clock: Callable that returns ISO8601 timestamp. Defaults to real UTC now.

    Returns:
        Merged OpenVEX tracking document with:
        - Findings from current_findings that aren't human-dispositioned
        - Preserved first_issued for findings in prior_doc
        - New first_issued = clock value for new findings
        - last_updated always set to clock value
        - No signature or attestation field
    """
    if clock is None:
        clock = _current_clock

    now_str = clock() if callable(clock) else str(clock)

    # Build map of prior findings by CVE ID
    prior_by_cve = {}
    if prior_doc and isinstance(prior_doc, dict):
        for stmt in prior_doc.get("statements", []):
            vuln = stmt.get("vulnerability", {})
            if isinstance(vuln, dict):
                cve_id = vuln.get("name")
                if cve_id:
                    prior_by_cve[cve_id] = stmt

    # Get the set of human-dispositioned CVEs to exclude
    human_dispositioned = _extract_human_dispositions(human_disposition_doc)

    # Build the merged statements
    merged_statements = []
    seen_cves = set()

    for finding in current_findings:
        cve_id = _get_cve_id(finding)
        if not cve_id:
            # Skip findings without a CVE ID
            continue

        # Skip if already seen (dedup)
        if cve_id in seen_cves:
            continue
        seen_cves.add(cve_id)

        # Skip if already covered by human disposition
        if cve_id in human_dispositioned:
            continue

        # Build the tracking statement
        stmt: Dict[str, Any] = {
            "vulnerability": {"name": cve_id},
        }

        # Preserve first_issued if this finding was in the prior doc
        if cve_id in prior_by_cve:
            prior_stmt = prior_by_cve[cve_id]
            if "first_issued" in prior_stmt:
                stmt["first_issued"] = prior_stmt["first_issued"]

        # Set first_issued to now if we didn't preserve it from prior
        if "first_issued" not in stmt:
            stmt["first_issued"] = now_str

        # Always update last_updated to now
        stmt["last_updated"] = now_str

        merged_statements.append(stmt)

    # Return unsigned OpenVEX document
    now_date = now_str.split("T")[0]  # Extract date for timestamp
    output_doc: Dict[str, Any] = {
        "@context": "https://openvex.dev/ns/v0.2.0",
        "@id": f"https://openvex.dev/docs/tracking/vex-tracking-{now_date}",
        "author": "c3cdao-ci-scans vex-tracking (machine-derived, unsigned)",
        "timestamp": now_str,
        "version": 1,
        "statements": merged_statements,
    }

    return output_doc


def main():
    """CLI entry point: merge prior + current + dispositions, write merged doc to stdout."""
    if len(sys.argv) != 4:
        print(
            "Usage: vex_tracking.py <prior-doc-path|-> <current-findings-path> <human-disposition-doc-path|->",
            file=sys.stderr,
        )
        print(
            "  prior-doc-path: path to prior tracking doc (or '-' for none/empty)",
            file=sys.stderr,
        )
        print("  current-findings-path: path to current Trivy/Grype findings JSON", file=sys.stderr)
        print(
            "  human-disposition-doc-path: path to human VEX doc (or '-' for none)",
            file=sys.stderr,
        )
        sys.exit(1)

    prior_path, findings_path, disposition_path = sys.argv[1:]

    # Load prior doc
    prior_doc = None
    if prior_path != "-":
        try:
            with open(prior_path) as f:
                prior_doc = json.load(f)
        except FileNotFoundError:
            pass

    # Load current findings
    current_findings = []
    try:
        with open(findings_path) as f:
            findings_json = json.load(f)
            # Trivy exports as {"Results": [...]} with each result's "Misconfigurations" or "Vulnerabilities"
            # Grype exports as {"matches": [...]}
            if isinstance(findings_json, dict):
                if "Results" in findings_json:
                    # Trivy format
                    for result in findings_json["Results"]:
                        if "Vulnerabilities" in result:
                            current_findings.extend(result["Vulnerabilities"])
                elif "matches" in findings_json:
                    # Grype format
                    current_findings = findings_json["matches"]
            elif isinstance(findings_json, list):
                current_findings = findings_json
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error loading current findings from {findings_path}: {e}", file=sys.stderr)
        sys.exit(1)

    # Load human disposition doc
    disposition_doc = None
    if disposition_path != "-":
        try:
            with open(disposition_path) as f:
                disposition_doc = json.load(f)
        except FileNotFoundError:
            pass

    # Perform merge
    merged_doc = merge(prior_doc, current_findings, disposition_doc)

    # Write merged doc to stdout
    print(json.dumps(merged_doc, indent=2))


if __name__ == "__main__":
    main()
