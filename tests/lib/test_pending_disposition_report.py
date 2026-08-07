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


def test_trivy_findings_filters_high_critical_only(tmp_path):
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
    assert {f["id"] for f in findings} == {"CVE-1", "CVE-3"}
    fixed = next(f for f in findings if f["id"] == "CVE-3")
    assert fixed["fixed_version"] == "1.2.3"


def test_grype_findings_fixed_state_required_for_fixed_version(tmp_path):
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
    assert {f["id"] for f in findings} == {"CVE-1", "CVE-2"}  # CVE-3 filtered (Low)
    cve1 = next(f for f in findings if f["id"] == "CVE-1")
    assert cve1["fixed_version"] == ""  # state != "fixed" -> not treated as fixed
    cve2 = next(f for f in findings if f["id"] == "CVE-2")
    assert cve2["fixed_version"] == "2.0.0"


# --- pending_for_service: covered exclusion + bucket split -------------------


def test_pending_for_service_excludes_covered_ids(tmp_path):
    svc = tmp_path / "security-export-app-abc1234"
    svc.mkdir()
    _write(svc / "trivy-image.json", _trivy_doc([{"VulnerabilityID": "CVE-1", "Severity": "HIGH", "PkgName": "a"}]))
    _write(svc / "grype-image.json", _grype_doc([]))
    _write(svc / "vex-applied.openvex.json", _vex_doc(["CVE-1"]))
    remediate, vex_candidate = mod.pending_for_service(svc)
    assert remediate == []
    assert vex_candidate == []


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
    remediate, vex_candidate = mod.pending_for_service(svc)
    assert [f["id"] for f in remediate] == ["CVE-FIXED"]
    assert [f["id"] for f in vex_candidate] == ["CVE-NOFIX"]


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
    remediate, vex_candidate = mod.pending_for_service(svc)
    assert [f["id"] for f in remediate] == ["CVE-SHARED"]
    assert vex_candidate == []


def test_pending_for_service_missing_files_yield_empty_buckets(tmp_path):
    svc = tmp_path / "security-export-app-abc1234"
    svc.mkdir()
    remediate, vex_candidate = mod.pending_for_service(svc)
    assert remediate == []
    assert vex_candidate == []


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
