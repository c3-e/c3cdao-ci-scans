"""Unit tests for pending_disposition_report.py — read-only enumeration
of High/Critical findings not covered by any VEX statement, split by the
scanners' own fix metadata into remediate vs. VEX-candidate buckets.

Invariant under test throughout: the module never writes to disk under
.openvex/ and never constructs a VEX statement — it only reads bundle
JSON and renders markdown.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MOD_PATH = ROOT / "scripts/lib/pending_disposition_report.py"


def _load():
    spec = importlib.util.spec_from_file_location("pending_disposition_report", MOD_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mod = _load()


def _trivy_doc(vulns: list[dict]) -> dict:
    return {"Results": [{"Vulnerabilities": vulns}]}


def _grype_doc(matches: list[dict]) -> dict:
    return {"matches": matches}


def _vex_doc(cve_ids: list[str]) -> dict:
    return {
        "statements": [
            {"vulnerability": {"name": cve}, "status": "under_investigation"}
            for cve in cve_ids
        ]
    }


def _write(path: Path, doc: dict) -> None:
    path.write_text(json.dumps(doc))


# --- covered_ids ------------------------------------------------------------


def test_covered_ids_reads_any_status(tmp_path):
    vex = tmp_path / "vex-applied.openvex.json"
    _write(vex, _vex_doc(["CVE-2024-1"]))
    assert mod.covered_ids(vex) == {"CVE-2024-1"}


def test_covered_ids_empty_when_absent(tmp_path):
    assert mod.covered_ids(tmp_path / "missing.json") == set()


def test_covered_ids_empty_on_malformed_json(tmp_path):
    bad = tmp_path / "vex-applied.openvex.json"
    bad.write_text("{not json")
    assert mod.covered_ids(bad) == set()


# --- trivy_findings / grype_findings -----------------------------------------


def test_trivy_findings_returns_all_severities(tmp_path):
    """trivy_findings returns all severities, including severity field."""
    path = tmp_path / "trivy-image.json"
    _write(
        path,
        _trivy_doc(
            [
                {"VulnerabilityID": "CVE-1", "Severity": "HIGH", "PkgName": "a"},
                {"VulnerabilityID": "CVE-2", "Severity": "MEDIUM", "PkgName": "b"},
                {"VulnerabilityID": "CVE-3", "Severity": "CRITICAL", "PkgName": "c", "FixedVersion": "1.2.3"},
            ]
        ),
    )
    findings = mod.trivy_findings(path)
    assert {f["id"] for f in findings} == {"CVE-1", "CVE-2", "CVE-3"}
    # Check severity field is present
    assert {f["severity"] for f in findings} == {"HIGH", "MEDIUM", "CRITICAL"}
    fixed = next(f for f in findings if f["id"] == "CVE-3")
    assert fixed["fixed_version"] == "1.2.3"
    assert fixed["severity"] == "CRITICAL"


def test_grype_findings_returns_all_severities(tmp_path):
    """grype_findings returns all severities, including severity field."""
    path = tmp_path / "grype-image.json"
    _write(
        path,
        _grype_doc(
            [
                {
                    "vulnerability": {"id": "CVE-1", "severity": "High", "fix": {"state": "not-fixed", "versions": ["9.9.9"]}},
                    "artifact": {"name": "pkg-a"},
                },
                {
                    "vulnerability": {"id": "CVE-2", "severity": "Critical", "fix": {"state": "fixed", "versions": ["2.0.0"]}},
                    "artifact": {"name": "pkg-b"},
                },
                {
                    "vulnerability": {"id": "CVE-3", "severity": "Low", "fix": {"state": "fixed", "versions": ["1.0.0"]}},
                    "artifact": {"name": "pkg-c"},
                },
            ]
        ),
    )
    findings = mod.grype_findings(path)
    assert {f["id"] for f in findings} == {"CVE-1", "CVE-2", "CVE-3"}  # All returned now
    cve1 = next(f for f in findings if f["id"] == "CVE-1")
    assert cve1["fixed_version"] == ""  # state != "fixed" -> not treated as fixed
    assert cve1["severity"] == "High"
    cve2 = next(f for f in findings if f["id"] == "CVE-2")
    assert cve2["fixed_version"] == "2.0.0"
    assert cve2["severity"] == "Critical"
    cve3 = next(f for f in findings if f["id"] == "CVE-3")
    assert cve3["severity"] == "Low"


# --- pending_for_service: covered exclusion + bucket split -------------------


def test_pending_for_service_excludes_covered_ids(tmp_path):
    svc = tmp_path / "security-export-app-abc1234"
    svc.mkdir()
    _write(svc / "trivy-image.json", _trivy_doc([{"VulnerabilityID": "CVE-1", "Severity": "HIGH", "PkgName": "a"}]))
    _write(svc / "grype-image.json", _grype_doc([]))
    _write(svc / "vex-applied.openvex.json", _vex_doc(["CVE-1"]))
    remediate, vex_candidate, medium_low = mod.pending_for_service(svc)
    assert remediate == []
    assert vex_candidate == []
    assert medium_low == []


def test_pending_for_service_splits_by_fix_availability(tmp_path):
    svc = tmp_path / "security-export-app-abc1234"
    svc.mkdir()
    _write(
        svc / "trivy-image.json",
        _trivy_doc(
            [
                {"VulnerabilityID": "CVE-FIXED", "Severity": "HIGH", "PkgName": "a", "FixedVersion": "1.5.0"},
                {"VulnerabilityID": "CVE-NOFIX", "Severity": "CRITICAL", "PkgName": "b"},
            ]
        ),
    )
    _write(svc / "grype-image.json", _grype_doc([]))
    remediate, vex_candidate, medium_low = mod.pending_for_service(svc)
    assert [f["id"] for f in remediate] == ["CVE-FIXED"]
    assert [f["id"] for f in vex_candidate] == ["CVE-NOFIX"]
    assert medium_low == []


def test_pending_for_service_dedupes_across_scanners_preferring_fixed(tmp_path):
    """Same CVE reported by both scanners: if either names a fix, the
    finding must land in remediate, never vex-candidate."""
    svc = tmp_path / "security-export-app-abc1234"
    svc.mkdir()
    _write(
        svc / "trivy-image.json",
        _trivy_doc([{"VulnerabilityID": "CVE-SHARED", "Severity": "HIGH", "PkgName": "a"}]),
    )
    _write(
        svc / "grype-image.json",
        _grype_doc(
            [
                {
                    "vulnerability": {"id": "CVE-SHARED", "severity": "High", "fix": {"state": "fixed", "versions": ["3.0.0"]}},
                    "artifact": {"name": "a"},
                }
            ]
        ),
    )
    remediate, vex_candidate, medium_low = mod.pending_for_service(svc)
    assert [f["id"] for f in remediate] == ["CVE-SHARED"]
    assert vex_candidate == []
    assert medium_low == []


def test_pending_for_service_missing_files_yield_empty_buckets(tmp_path):
    svc = tmp_path / "security-export-app-abc1234"
    svc.mkdir()
    remediate, vex_candidate, medium_low = mod.pending_for_service(svc)
    assert remediate == []
    assert vex_candidate == []
    assert medium_low == []


# --- render: markdown shape + never touches .openvex/ ------------------------


def test_render_reports_none_pending_when_clean(tmp_path):
    bundle = tmp_path / "security-export-full"
    bundle.mkdir()
    out = mod.render(bundle)
    assert "none" in out.lower()
    assert ".openvex" not in out


def test_render_shows_both_buckets(tmp_path):
    bundle = tmp_path / "security-export-full"
    svc = bundle / "security-export-app-abc1234"
    svc.mkdir(parents=True)
    _write(
        svc / "trivy-image.json",
        _trivy_doc(
            [
                {"VulnerabilityID": "CVE-FIXED", "Severity": "HIGH", "PkgName": "a", "FixedVersion": "1.5.0"},
                {"VulnerabilityID": "CVE-NOFIX", "Severity": "CRITICAL", "PkgName": "b"},
            ]
        ),
    )
    _write(svc / "grype-image.json", _grype_doc([]))
    out = mod.render(bundle)
    assert "Remediation available" in out
    assert "CVE-FIXED" in out and "1.5.0" in out
    assert "VEX-disposition candidates" in out
    assert "CVE-NOFIX" in out


def test_render_caps_rows_and_names_overflow(tmp_path):
    bundle = tmp_path / "security-export-full"
    svc = bundle / "security-export-app-abc1234"
    svc.mkdir(parents=True)
    vulns = [
        {"VulnerabilityID": f"CVE-{i:04d}", "Severity": "HIGH", "PkgName": "a"}
        for i in range(20)
    ]
    _write(svc / "trivy-image.json", _trivy_doc(vulns))
    _write(svc / "grype-image.json", _grype_doc([]))
    out = mod.render(bundle, max_rows=5)
    assert "+15 more" in out


def test_render_never_writes_under_openvex(tmp_path):
    """Invariant: rendering a report must not create any .openvex/ path,
    even transiently — enumeration only, never disposition."""
    bundle = tmp_path / "security-export-full"
    bundle.mkdir()
    before = set(tmp_path.rglob("*"))
    mod.render(bundle)
    after = set(tmp_path.rglob("*"))
    assert not any(".openvex" in str(p) for p in after - before)


def test_service_name_strips_prefix_and_short_sha():
    assert mod._service_name(Path("security-export-my-app-abc1234")) == "my-app"


# --- Medium/Low tiering and age tracking ---


def _vex_tracking_doc(cve_id: str, first_issued: str) -> dict:
    """Create a vex-tracking.json doc with a single CVE statement."""
    return {
        "@context": "https://openvex.dev/ns/v0.2.0",
        "@id": "https://openvex.dev/docs/tracking/vex-tracking-2026-09-03",
        "author": "test",
        "timestamp": "2026-09-03T14:47:26Z",
        "version": 1,
        "statements": [
            {
                "vulnerability": {"name": cve_id},
                "first_issued": first_issued,
                "last_updated": "2026-09-03T14:47:26Z",
            }
        ],
    }


def test_medium_low_tier_worked_example(tmp_path):
    """age=32 days renders as 'within 90-day SLA'; a dispositioned High is excluded."""
    bundle = tmp_path / "security-export-full"
    svc = bundle / "security-export-app-abc1234"
    svc.mkdir(parents=True)

    _write(
        svc / "grype-image.json",
        _grype_doc(
            [
                {
                    "vulnerability": {
                        "id": "CVE-2026-42533",
                        "severity": "High",
                        "fix": {"state": "not-fixed", "versions": []},
                    },
                    "artifact": {"name": "nginx"},
                },
                {
                    "vulnerability": {
                        "id": "CVE-2026-99999",
                        "severity": "Medium",
                        "fix": {"state": "not-fixed", "versions": []},
                    },
                    "artifact": {"name": "openssl-libs"},
                },
            ]
        ),
    )
    _write(svc / "trivy-image.json", _trivy_doc([]))

    _write(
        svc / "vex-applied.openvex.json",
        {
            "statements": [
                {
                    "vulnerability": {"name": "CVE-2026-42533"},
                    "status": "not_affected",
                }
            ]
        },
    )

    _write(
        svc / "vex-tracking.json",
        _vex_tracking_doc("CVE-2026-99999", "2026-08-01T00:00:00Z"),
    )

    def fixed_clock():
        return "2026-09-02T00:00:00Z"  # 32 days after first_issued

    output = mod.render(bundle, clock=fixed_clock)

    assert "CVE-2026-42533" not in output
    assert "CVE-2026-99999" in output
    assert "Actively Managed" in output
    assert "32" in output
    assert "within 90-day SLA" in output


def test_medium_low_sla_breach(tmp_path):
    """Same finding with age=95 days shows SLA breach status."""
    bundle = tmp_path / "security-export-full"
    svc = bundle / "security-export-app-abc1234"
    svc.mkdir(parents=True)

    _write(
        svc / "grype-image.json",
        _grype_doc(
            [
                {
                    "vulnerability": {
                        "id": "CVE-2026-99999",
                        "severity": "Medium",
                        "fix": {"state": "not-fixed", "versions": []},
                    },
                    "artifact": {"name": "openssl-libs"},
                }
            ]
        ),
    )
    _write(svc / "trivy-image.json", _trivy_doc([]))
    _write(svc / "vex-applied.openvex.json", {})

    # CVE first_issued on 2026-05-30 (95 days before 2026-09-02)
    _write(
        svc / "vex-tracking.json",
        _vex_tracking_doc("CVE-2026-99999", "2026-05-30T00:00:00Z"),
    )

    def fixed_clock():
        return "2026-09-02T00:00:00Z"

    output = mod.render(bundle, clock=fixed_clock)

    assert "CVE-2026-99999" in output
    assert "95" in output  # age = 95 days
    assert "SLA breach — 90-day threshold exceeded" in output


def test_medium_low_sla_boundary_at_exactly_90_days_is_within(tmp_path):
    """Boundary case flagged by evidence review as untested: age == 90 must
    be treated as within SLA (code uses `<= 90`), not a breach — the
    ticket's own wording ("once age exceeds 90 days") means the breach
    threshold is strictly greater than 90."""
    bundle = tmp_path / "security-export-full"
    svc = bundle / "security-export-app-abc1234"
    svc.mkdir(parents=True)

    _write(
        svc / "grype-image.json",
        _grype_doc(
            [
                {
                    "vulnerability": {
                        "id": "CVE-2026-88888",
                        "severity": "Medium",
                        "fix": {"state": "not-fixed", "versions": []},
                    },
                    "artifact": {"name": "openssl-libs"},
                }
            ]
        ),
    )
    _write(svc / "trivy-image.json", _trivy_doc([]))
    _write(svc / "vex-applied.openvex.json", {})

    # Exactly 90 days before the reference clock (2026-06-04 -> 2026-09-02).
    _write(
        svc / "vex-tracking.json",
        _vex_tracking_doc("CVE-2026-88888", "2026-06-04T00:00:00Z"),
    )

    def fixed_clock():
        return "2026-09-02T00:00:00Z"

    output = mod.render(bundle, clock=fixed_clock)

    assert "CVE-2026-88888" in output
    assert "| 90 | within 90-day SLA |" in output
    assert "SLA breach" not in output


def test_render_high_critical_unchanged_with_no_medium_low(tmp_path):
    """Regression baseline — High/Critical output is byte-identical when no
    Medium/Low findings are present, matching the pre-tiering output
    exactly."""
    bundle = tmp_path / "security-export-full"
    svc = bundle / "security-export-app-abc1234"
    svc.mkdir(parents=True)

    # Only High/Critical findings
    _write(
        svc / "trivy-image.json",
        _trivy_doc(
            [
                {"VulnerabilityID": "CVE-FIXED", "Severity": "HIGH", "PkgName": "a", "FixedVersion": "1.5.0"},
                {"VulnerabilityID": "CVE-NOFIX", "Severity": "CRITICAL", "PkgName": "b"},
            ]
        ),
    )
    _write(svc / "grype-image.json", _grype_doc([]))
    _write(svc / "vex-applied.openvex.json", {})

    output = mod.render(bundle)

    # Full-string equality, not substring checks — those let a real
    # regression through once: an earlier build unconditionally appended
    # a trailing blank line after the candidate_rows table even when
    # nothing followed it, so every fixture with candidate_rows but no
    # Medium/Low findings gained one extra trailing newline that wasn't
    # there before.
    expected = "\n".join(
        [
            "**Pending disposition (not covered by any VEX statement):**",
            "",
            "Remediation available (1) — bump, don't suppress:",
            "",
            "| Service | CVE | Package | Fixed version |",
            "| --- | --- | --- | --- |",
            "| app | CVE-FIXED | a | 1.5.0 |",
            "",
            "No fix available — VEX-disposition candidates (1):",
            "",
            "| Service | CVE | Package |",
            "| --- | --- | --- |",
            "| app | CVE-NOFIX | b |",
        ]
    )
    assert output == expected

    # Belt-and-suspenders: Medium/Low table must not appear at all.
    assert "Actively Managed" not in output


def test_missing_tracking_doc_degrades_gracefully(tmp_path):
    """Missing/malformed tracking doc shows age 'unknown', doesn't crash.

    When vex-tracking.json is missing or invalid:
      - Medium/Low findings still render
      - age_days is None, shows as 'unknown'
      - status is 'unknown'
      - render() does not crash
    """
    bundle = tmp_path / "security-export-full"
    svc = bundle / "security-export-app-abc1234"
    svc.mkdir(parents=True)

    _write(
        svc / "grype-image.json",
        _grype_doc(
            [
                {
                    "vulnerability": {
                        "id": "CVE-2026-99999",
                        "severity": "Medium",
                        "fix": {"state": "not-fixed", "versions": []},
                    },
                    "artifact": {"name": "openssl-libs"},
                }
            ]
        ),
    )
    _write(svc / "trivy-image.json", _trivy_doc([]))
    _write(svc / "vex-applied.openvex.json", {})
    # NO vex-tracking.json file

    output = mod.render(bundle)

    # Should not crash, should still show the Medium/Low table
    assert "CVE-2026-99999" in output
    assert "Actively Managed" in output
    assert "unknown" in output  # age_days is None


def test_malformed_tracking_doc_degrades_gracefully(tmp_path):
    """Malformed JSON in vex-tracking.json still renders Medium/Low."""
    bundle = tmp_path / "security-export-full"
    svc = bundle / "security-export-app-abc1234"
    svc.mkdir(parents=True)

    _write(
        svc / "grype-image.json",
        _grype_doc(
            [
                {
                    "vulnerability": {
                        "id": "CVE-2026-99999",
                        "severity": "Low",
                        "fix": {"state": "not-fixed", "versions": []},
                    },
                    "artifact": {"name": "openssl-libs"},
                }
            ]
        ),
    )
    _write(svc / "trivy-image.json", _trivy_doc([]))
    _write(svc / "vex-applied.openvex.json", {})

    # Write malformed JSON
    (svc / "vex-tracking.json").write_text("{not valid json")

    output = mod.render(bundle)

    # Should not crash, should still show the Medium/Low table
    assert "CVE-2026-99999" in output
    assert "Actively Managed" in output
    assert "unknown" in output  # Unable to parse, age_days is None


def test_medium_low_multiple_findings(tmp_path):
    """Multiple Medium/Low findings are all shown with their own age/status."""
    bundle = tmp_path / "security-export-full"
    svc = bundle / "security-export-app-abc1234"
    svc.mkdir(parents=True)

    _write(
        svc / "grype-image.json",
        _grype_doc(
            [
                {
                    "vulnerability": {
                        "id": "CVE-1",
                        "severity": "Medium",
                        "fix": {"state": "not-fixed", "versions": []},
                    },
                    "artifact": {"name": "pkg-a"},
                },
                {
                    "vulnerability": {
                        "id": "CVE-2",
                        "severity": "Low",
                        "fix": {"state": "not-fixed", "versions": []},
                    },
                    "artifact": {"name": "pkg-b"},
                },
            ]
        ),
    )
    _write(svc / "trivy-image.json", _trivy_doc([]))
    _write(svc / "vex-applied.openvex.json", {})

    _write(
        svc / "vex-tracking.json",
        {
            "@context": "https://openvex.dev/ns/v0.2.0",
            "@id": "test",
            "author": "test",
            "timestamp": "2026-09-03T14:47:26Z",
            "version": 1,
            "statements": [
                {
                    "vulnerability": {"name": "CVE-1"},
                    "first_issued": "2026-08-20T00:00:00Z",
                    "last_updated": "2026-09-03T00:00:00Z",
                },
                {
                    "vulnerability": {"name": "CVE-2"},
                    "first_issued": "2026-07-04T00:00:00Z",
                    "last_updated": "2026-09-03T00:00:00Z",
                },
            ],
        },
    )

    def fixed_clock():
        return "2026-09-03T00:00:00Z"

    output = mod.render(bundle, clock=fixed_clock)

    # Both should be present
    assert "CVE-1" in output
    assert "CVE-2" in output
    assert "Actively Managed" in output

    # CVE-1: 14 days (within SLA)
    # CVE-2: 61 days (within SLA, but closer to breach)
    lines = output.split("\n")
    # Find rows with these CVEs
    cve1_line = next(line for line in lines if "CVE-1" in line)
    cve2_line = next(line for line in lines if "CVE-2" in line)

    assert "14" in cve1_line
    assert "within 90-day SLA" in cve1_line

    assert "61" in cve2_line
    assert "within 90-day SLA" in cve2_line
