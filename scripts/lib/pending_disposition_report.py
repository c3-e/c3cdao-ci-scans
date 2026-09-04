# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Pending-VEX-disposition report for the PR scan-summary comment.

Read-only enumeration — never writes anything under `.openvex/`, never
authors a VEX statement. For each per-service export-bundle directory,
finds Trivy+Grype findings not already covered by a statement in that
leg's `vex-applied.openvex.json` (any status counts as covered — this
is not re-litigating a disposition, only surfacing what has none), and
splits the rest by severity and fix availability:

  - High/Critical, fix available: remediate bucket
  - High/Critical, no fix: vex-candidate bucket
  - Medium/Low, any fix status: active management bucket (with age)

Both scanners cover the same image; a CVE seen by both is deduplicated by
id per service, preferring whichever leg reports a fixed version.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _get_cve_age_days(
    cve_id: str,
    service_dir: Path,
    clock: Optional[Callable[[], str]] = None,
) -> Optional[int]:
    """
    Compute age in days from vex-tracking.json's first_seen timestamp.

    Returns None if the tracking doc is missing/malformed or CVE not found.
    Uses the provided clock callable for "now" (default: real UTC now).
    """
    tracking_path = service_dir / "vex-tracking.json"
    tracking_doc = _load_json(tracking_path)
    if not tracking_doc:
        return None

    entry = (tracking_doc.get("findings") or {}).get(cve_id)
    if not isinstance(entry, dict):
        return None
    first_seen_str = entry.get("first_seen")
    if not first_seen_str:
        return None
    try:
        first_seen = datetime.fromisoformat(first_seen_str.replace("Z", "+00:00"))
        if clock is None:
            now = datetime.now(timezone.utc)
        else:
            now = datetime.fromisoformat(clock().replace("Z", "+00:00"))
        return (now - first_seen).days
    except (ValueError, AttributeError):
        return None


def covered_ids(vex_applied_path: Path) -> set[str]:
    """CVE ids already carrying a statement (any status) in the applied VEX doc."""
    doc = _load_json(vex_applied_path)
    return {
        name
        for stmt in doc.get("statements") or []
        if isinstance(stmt, dict)
        and (name := (stmt.get("vulnerability") or {}).get("name"))
    }


def trivy_findings(trivy_image_path: Path) -> list[dict[str, Any]]:
    """Return all findings from Trivy export with id, pkg, severity, fixed_version."""
    doc = _load_json(trivy_image_path)
    out = []
    for result in doc.get("Results") or []:
        for v in result.get("Vulnerabilities") or []:
            if v.get("VulnerabilityID"):
                out.append(
                    {
                        "id": v["VulnerabilityID"],
                        "pkg": v.get("PkgName") or "?",
                        "severity": v.get("Severity") or "UNKNOWN",
                        "fixed_version": v.get("FixedVersion") or "",
                    }
                )
    return out


def grype_findings(grype_image_path: Path) -> list[dict[str, Any]]:
    """Return all findings from Grype export with id, pkg, severity, fixed_version."""
    doc = _load_json(grype_image_path)
    out = []
    for m in doc.get("matches") or []:
        vuln = m.get("vulnerability") or {}
        if vuln.get("id"):
            fix = vuln.get("fix") or {}
            versions = fix.get("versions") or []
            fixed_version = (
                versions[0] if fix.get("state") == "fixed" and versions else ""
            )
            out.append(
                {
                    "id": vuln["id"],
                    "pkg": (m.get("artifact") or {}).get("name") or "?",
                    "severity": vuln.get("severity") or "Unknown",
                    "fixed_version": fixed_version,
                }
            )
    return out


def _is_high_or_critical(severity: str) -> bool:
    """Check if severity is High or Critical (case-insensitive for both Trivy and Grype)."""
    normalized = severity.upper()
    return normalized in ("HIGH", "CRITICAL")


def pending_for_service(
    service_dir: Path,
    clock: Optional[Callable[[], str]] = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Returns (remediate, vex_candidate, medium_low_managed), all sorted by CVE id.

    remediate: High/Critical with fixed_version
    vex_candidate: High/Critical without fixed_version
    medium_low_managed: Medium/Low findings with computed age and SLA status
    """
    covered = covered_ids(service_dir / "vex-applied.openvex.json")
    by_id: dict[str, dict[str, Any]] = {}
    for f in [
        *trivy_findings(service_dir / "trivy-image.json"),
        *grype_findings(service_dir / "grype-image.json"),
    ]:
        if f["id"] in covered:
            continue
        existing = by_id.get(f["id"])
        if existing is None or (not existing["fixed_version"] and f["fixed_version"]):
            by_id[f["id"]] = f

    # Separate High/Critical from Medium/Low
    remediate = []
    vex_candidate = []
    medium_low_managed = []

    for f in by_id.values():
        is_high_crit = _is_high_or_critical(f.get("severity", "UNKNOWN"))
        if is_high_crit:
            if f["fixed_version"]:
                remediate.append(f)
            else:
                vex_candidate.append(f)
        else:
            # Medium/Low: compute age and add status
            age_days = _get_cve_age_days(f["id"], service_dir, clock)
            status = "unknown"
            if age_days is not None:
                if age_days <= 90:
                    status = "within 90-day SLA"
                else:
                    status = "SLA breach — 90-day threshold exceeded"
            entry = dict(f)
            entry["age_days"] = age_days
            entry["age_status"] = status
            medium_low_managed.append(entry)

    remediate = sorted(remediate, key=lambda f: f["id"])
    vex_candidate = sorted(vex_candidate, key=lambda f: f["id"])
    medium_low_managed = sorted(medium_low_managed, key=lambda f: f["id"])
    return remediate, vex_candidate, medium_low_managed


def _service_name(service_dir: Path) -> str:
    # security-export-<service>-<short-sha> -> <service>; short sha is
    # always 7 hex chars, never dash-bearing, so one rsplit is exact.
    name = service_dir.name.removeprefix("security-export-")
    return name.rsplit("-", 1)[0]


def render(bundle_dir: Path, max_rows: int = 15, clock: Optional[Callable[[], str]] = None) -> str:
    remediate_rows: list[tuple[str, str, str, str]] = []
    candidate_rows: list[tuple[str, str, str]] = []
    medium_low_rows: list[tuple[str, str, str, Optional[int], str]] = []
    for service_dir in sorted(bundle_dir.glob("security-export-*")):
        if not service_dir.is_dir():
            continue
        svc = _service_name(service_dir)
        remediate, vex_candidate, medium_low_managed = pending_for_service(service_dir, clock)
        remediate_rows += [
            (svc, f["id"], f["pkg"], f["fixed_version"]) for f in remediate
        ]
        candidate_rows += [(svc, f["id"], f["pkg"]) for f in vex_candidate]
        medium_low_rows += [
            (svc, f["id"], f["pkg"], f.get("age_days"), f.get("age_status", "unknown"))
            for f in medium_low_managed
        ]

    lines = ["**Pending disposition (not covered by any VEX statement):**", ""]
    if not remediate_rows and not candidate_rows and not medium_low_rows:
        lines.append(
            "_none — every High/Critical finding is either dispositioned or absent._"
        )
        return "\n".join(lines)

    if remediate_rows:
        lines += [
            f"Remediation available ({len(remediate_rows)}) — bump, don't suppress:",
            "",
            "| Service | CVE | Package | Fixed version |",
            "| --- | --- | --- | --- |",
        ]
        lines += [
            f"| {s} | {c} | {p} | {fv} |" for s, c, p, fv in remediate_rows[:max_rows]
        ]
        if len(remediate_rows) > max_rows:
            lines.append(f"| _+{len(remediate_rows) - max_rows} more_ | | | |")
        lines.append("")

    if candidate_rows:
        lines += [
            f"No fix available — VEX-disposition candidates ({len(candidate_rows)}):",
            "",
            "| Service | CVE | Package |",
            "| --- | --- | --- |",
        ]
        lines += [f"| {s} | {c} | {p} |" for s, c, p in candidate_rows[:max_rows]]
        if len(candidate_rows) > max_rows:
            lines.append(f"| _+{len(candidate_rows) - max_rows} more_ | | | |")
        # Trailing blank only when the Medium/Low table follows — the
        # pre-T4 code never emitted one here at all (candidate_rows was
        # always the last section then). Unconditionally appending it
        # regardless of what follows was a real regression caught by
        # evidence review: it changed existing output for every fixture
        # with candidate_rows but no Medium/Low findings.
        if medium_low_rows:
            lines.append("")

    if medium_low_rows:
        lines += [
            f"Actively Managed (Medium/Low) ({len(medium_low_rows)}):",
            "",
            "| Service | CVE | Package | Age (days) | Status |",
            "| --- | --- | --- | --- | --- |",
        ]
        for s, c, p, age, status in medium_low_rows[:max_rows]:
            age_str = str(age) if age is not None else "unknown"
            lines.append(f"| {s} | {c} | {p} | {age_str} | {status} |")
        if len(medium_low_rows) > max_rows:
            lines.append(f"| _+{len(medium_low_rows) - max_rows} more_ | | | | |")

    return "\n".join(lines)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle_dir", type=Path, help="security-export-full directory")
    args = parser.parse_args(argv)
    print(render(args.bundle_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
