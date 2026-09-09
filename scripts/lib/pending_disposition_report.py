# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Pending-VEX-disposition report for the PR scan-summary comment.

Read-only: never writes under `.openvex/` or authors a VEX statement.
For each service, finds High/Critical Trivy+Grype findings not already
covered by any statement in that leg's `vex-applied.openvex.json`, and
splits them by fix availability:

  - remediate: a fixed version exists (bump, don't suppress).
  - vex-candidate: no fix exists — the only findings worth a `vexctl add`.

Findings from both scanners are deduplicated by CVE id per service,
preferring whichever leg reports a fixed version.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_HIGH_CRIT_TRIVY = ("HIGH", "CRITICAL")
_HIGH_CRIT_GRYPE = ("High", "Critical")


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def covered_ids(vex_applied_path: Path) -> set[str]:
    """CVE ids already carrying a statement (any status) in the applied VEX doc."""
    doc = _load_json(vex_applied_path)
    return {
        name
        for stmt in doc.get("statements") or []
        if isinstance(stmt, dict)
        and (name := (stmt.get("vulnerability") or {}).get("name"))
    }


def trivy_findings(trivy_image_path: Path) -> list[dict[str, str]]:
    doc = _load_json(trivy_image_path)
    out = []
    for result in doc.get("Results") or []:
        for v in result.get("Vulnerabilities") or []:
            if v.get("Severity") in _HIGH_CRIT_TRIVY and v.get("VulnerabilityID"):
                out.append(
                    {
                        "id": v["VulnerabilityID"],
                        "pkg": v.get("PkgName") or "?",
                        "fixed_version": v.get("FixedVersion") or "",
                    }
                )
    return out


def grype_findings(grype_image_path: Path) -> list[dict[str, str]]:
    doc = _load_json(grype_image_path)
    out = []
    for m in doc.get("matches") or []:
        vuln = m.get("vulnerability") or {}
        if vuln.get("severity") in _HIGH_CRIT_GRYPE and vuln.get("id"):
            fix = vuln.get("fix") or {}
            versions = fix.get("versions") or []
            fixed_version = (
                versions[0] if fix.get("state") == "fixed" and versions else ""
            )
            out.append(
                {
                    "id": vuln["id"],
                    "pkg": (m.get("artifact") or {}).get("name") or "?",
                    "fixed_version": fixed_version,
                }
            )
    return out


def pending_for_service(
    service_dir: Path,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Returns (remediate, vex_candidate), both sorted by CVE id."""
    covered = covered_ids(service_dir / "vex-applied.openvex.json")
    by_id: dict[str, dict[str, str]] = {}
    for f in [
        *trivy_findings(service_dir / "trivy-image.json"),
        *grype_findings(service_dir / "grype-image.json"),
    ]:
        if f["id"] in covered:
            continue
        existing = by_id.get(f["id"])
        if existing is None or (not existing["fixed_version"] and f["fixed_version"]):
            by_id[f["id"]] = f
    remediate = sorted(
        (f for f in by_id.values() if f["fixed_version"]), key=lambda f: f["id"]
    )
    vex_candidate = sorted(
        (f for f in by_id.values() if not f["fixed_version"]), key=lambda f: f["id"]
    )
    return remediate, vex_candidate


def _service_name(service_dir: Path) -> str:
    # security-export-<service>-<short-sha> -> <service>; short sha is
    # always 7 hex chars, never dash-bearing, so one rsplit is exact.
    name = service_dir.name.removeprefix("security-export-")
    return name.rsplit("-", 1)[0]


def render(bundle_dir: Path, max_rows: int = 15) -> str:
    remediate_rows: list[tuple[str, str, str, str]] = []
    candidate_rows: list[tuple[str, str, str]] = []
    for service_dir in sorted(bundle_dir.glob("security-export-*")):
        if not service_dir.is_dir():
            continue
        svc = _service_name(service_dir)
        remediate, vex_candidate = pending_for_service(service_dir)
        remediate_rows += [
            (svc, f["id"], f["pkg"], f["fixed_version"]) for f in remediate
        ]
        candidate_rows += [(svc, f["id"], f["pkg"]) for f in vex_candidate]

    lines = ["**Pending disposition (not covered by any VEX statement):**", ""]
    if not remediate_rows and not candidate_rows:
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

    return "\n".join(lines)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle_dir", type=Path, help="security-export-full directory")
    args = parser.parse_args(argv)
    print(render(args.bundle_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
