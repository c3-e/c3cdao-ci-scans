#!/usr/bin/env python3
"""Unit tests for vex_tracking.merge() and related functions."""

import json
import pytest
from datetime import datetime, timezone

# Import the module under test
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../scripts/lib"))
import vex_tracking


class TestExtractHumanDispositions:
    """Test extraction of human-dispositioned CVEs from VEX docs."""

    def test_extract_not_affected(self):
        vex_doc = {"statements": [{"vulnerability": {"name": "CVE-2026-42533"}, "status": "not_affected"}]}
        assert "CVE-2026-42533" in vex_tracking._extract_human_dispositions(vex_doc)

    def test_extract_affected(self):
        vex_doc = {"statements": [{"vulnerability": {"name": "CVE-2026-60005"}, "status": "affected"}]}
        assert "CVE-2026-60005" in vex_tracking._extract_human_dispositions(vex_doc)

    def test_extract_fixed(self):
        vex_doc = {"statements": [{"vulnerability": {"name": "CVE-2026-99999"}, "status": "fixed"}]}
        assert "CVE-2026-99999" in vex_tracking._extract_human_dispositions(vex_doc)

    def test_exclude_under_investigation(self):
        """'under_investigation' is not a verdict yet, so it is NOT a disposition."""
        vex_doc = {"statements": [{"vulnerability": {"name": "CVE-2026-11111"}, "status": "under_investigation"}]}
        assert "CVE-2026-11111" not in vex_tracking._extract_human_dispositions(vex_doc)

    def test_empty_doc(self):
        assert vex_tracking._extract_human_dispositions(None) == set()


class TestGetCveId:
    """Test CVE ID extraction from findings."""

    def test_trivy_format(self):
        assert vex_tracking._get_cve_id({"VulnerabilityID": "CVE-2026-12345", "Severity": "HIGH"}) == "CVE-2026-12345"

    def test_grype_format(self):
        """Grype's real schema has vulnerability.id, no .name key at all."""
        assert vex_tracking._get_cve_id({"vulnerability": {"id": "CVE-2026-67890"}, "severity": "HIGH"}) == "CVE-2026-67890"

    def test_no_cve_id(self):
        assert vex_tracking._get_cve_id({"severity": "HIGH"}) is None


class TestRealGrypeSchemaRegression:
    """Locks in the bug-10 fix: Grype's real export has no vulnerability.name,
    only .id; reading .name returned None and dropped every Grype finding."""

    def test_get_cve_id_reads_real_grype_shape(self):
        real_grype_match = {
            "vulnerability": {
                "id": "CVE-2021-3711",
                "dataSource": "https://security.alpinelinux.org/vuln/CVE-2021-3711",
                "namespace": "alpine:distro:alpine:3.12",
                "severity": "Critical",
                "fix": {"versions": ["1.1.1l-r0"], "state": "fixed"},
            },
            "artifact": {"name": "libcrypto1.1", "version": "1.1.1k-r0"},
        }
        assert vex_tracking._get_cve_id(real_grype_match) == "CVE-2021-3711"
        assert "name" not in real_grype_match["vulnerability"]


class TestMergeFunctionality:
    """Test the core merge() function."""

    def test_first_run_new_finding(self):
        """First run stamps first_seen and last_seen to the clock value."""
        clock_value = "2026-08-01T13:00:00Z"
        result = vex_tracking.merge(None, [{"VulnerabilityID": "CVE-2026-99999"}], None, clock=lambda: clock_value)
        entry = result["findings"]["CVE-2026-99999"]
        assert entry["first_seen"] == clock_value
        assert entry["last_seen"] == clock_value

    def test_preserved_first_seen_across_runs(self):
        """Second run preserves first_seen, refreshes last_seen."""
        first_clock = "2026-08-01T13:00:00Z"
        second_clock = "2026-09-02T13:00:00Z"
        prior_doc = {
            "schemaVersion": 1,
            "kind": vex_tracking.SCHEMA_KIND,
            "generated": first_clock,
            "findings": {"CVE-2026-99999": {"first_seen": first_clock, "last_seen": first_clock}},
        }
        result = vex_tracking.merge(prior_doc, [{"VulnerabilityID": "CVE-2026-99999"}], None, clock=lambda: second_clock)
        entry = result["findings"]["CVE-2026-99999"]
        assert entry["first_seen"] == first_clock
        assert entry["last_seen"] == second_clock

    def test_human_dispositioned_cve_excluded(self):
        """CVEs covered by human verdicts are excluded from the tracking doc."""
        current_findings = [{"VulnerabilityID": "CVE-2026-42533"}, {"VulnerabilityID": "CVE-2026-99999"}]
        human_disposition_doc = {"statements": [{"vulnerability": {"name": "CVE-2026-42533"}, "status": "not_affected"}]}
        result = vex_tracking.merge(None, current_findings, human_disposition_doc, clock=lambda: "2026-09-02T13:00:00Z")
        assert set(result["findings"]) == {"CVE-2026-99999"}

    def test_first_run_no_prior_doc(self):
        clock_value = "2026-09-02T13:00:00Z"
        current_findings = [{"VulnerabilityID": "CVE-2026-11111"}, {"VulnerabilityID": "CVE-2026-22222"}]
        result = vex_tracking.merge(None, current_findings, None, clock=lambda: clock_value)
        assert set(result["findings"]) == {"CVE-2026-11111", "CVE-2026-22222"}
        for entry in result["findings"].values():
            assert entry["first_seen"] == clock_value
            assert entry["last_seen"] == clock_value

    def test_output_never_has_signature_or_openvex_envelope(self):
        """Output is a plain tracking map — never signed, never an OpenVEX doc."""
        result = vex_tracking.merge(None, [{"VulnerabilityID": "CVE-2026-99999"}], None)
        for forbidden in ("signature", "signatures", "attestation", "attestations", "protected", "@context", "statements"):
            assert forbidden not in result

    def test_empty_findings_list(self):
        assert vex_tracking.merge(None, [], None)["findings"] == {}

    def test_dedup_identical_cves(self):
        current_findings = [{"VulnerabilityID": "CVE-2026-99999"}, {"VulnerabilityID": "CVE-2026-99999"}]
        result = vex_tracking.merge(None, current_findings, None)
        assert list(result["findings"]) == ["CVE-2026-99999"]

    def test_grype_format_matching(self):
        """A Grype-format finding (vulnerability.id) matches its prior entry by CVE id."""
        prior_doc = {"findings": {"CVE-2026-grype": {"first_seen": "2026-08-01T13:00:00Z", "last_seen": "2026-08-01T13:00:00Z"}}}
        current_findings = [{"vulnerability": {"id": "CVE-2026-grype"}, "severity": "HIGH"}]
        clock_value = "2026-09-02T13:00:00Z"
        result = vex_tracking.merge(prior_doc, current_findings, None, clock=lambda: clock_value)
        entry = result["findings"]["CVE-2026-grype"]
        assert entry["first_seen"] == "2026-08-01T13:00:00Z"
        assert entry["last_seen"] == clock_value

    def test_tracking_document_structure(self):
        """Output is the honest custom schema, not OpenVEX."""
        result = vex_tracking.merge(None, [{"VulnerabilityID": "CVE-2026-99999"}], None)
        assert result["schemaVersion"] == vex_tracking.SCHEMA_VERSION
        assert result["kind"] == vex_tracking.SCHEMA_KIND
        assert "generated" in result
        assert isinstance(result["findings"], dict)

    def test_mixed_trivy_grype_findings(self):
        current_findings = [{"VulnerabilityID": "CVE-2026-trivy"}, {"vulnerability": {"id": "CVE-2026-grype"}}]
        result = vex_tracking.merge(None, current_findings, None)
        assert set(result["findings"]) == {"CVE-2026-trivy", "CVE-2026-grype"}

    def test_clock_parameter_defaults_to_real_utc(self):
        result = vex_tracking.merge(None, [{"VulnerabilityID": "CVE-2026-99999"}], None)
        first_seen = result["findings"]["CVE-2026-99999"]["first_seen"]
        assert "T" in first_seen and "Z" in first_seen
        assert isinstance(datetime.fromisoformat(first_seen.replace("Z", "+00:00")), datetime)


class TestLoadFindingsFile:
    """Test _load_findings_file(): main() loads EACH scanner's export separately,
    so both combine — never an either/or choice between Trivy and Grype."""

    def test_missing_sentinel_returns_empty(self):
        assert vex_tracking._load_findings_file("-") == []

    def test_loads_trivy_shape(self, tmp_path):
        trivy_doc = {
            "Results": [
                {"Vulnerabilities": [{"VulnerabilityID": "CVE-2026-T1"}]},
                {"Vulnerabilities": [{"VulnerabilityID": "CVE-2026-T2"}]},
                {},  # a result with no Vulnerabilities key at all
            ]
        }
        p = tmp_path / "trivy-image.json"
        p.write_text(json.dumps(trivy_doc))
        ids = {f["VulnerabilityID"] for f in vex_tracking._load_findings_file(str(p))}
        assert ids == {"CVE-2026-T1", "CVE-2026-T2"}

    def test_loads_grype_shape(self, tmp_path):
        p = tmp_path / "grype-image.json"
        p.write_text(json.dumps({"matches": [{"vulnerability": {"id": "CVE-2026-G1"}}]}))
        result = vex_tracking._load_findings_file(str(p))
        assert len(result) == 1
        assert result[0]["vulnerability"]["id"] == "CVE-2026-G1"

    def test_both_files_combine_not_either_or(self, tmp_path):
        """A prior implementation picked ONE scanner and dropped the other;
        loading both must yield the union."""
        trivy_p = tmp_path / "trivy-image.json"
        grype_p = tmp_path / "grype-image.json"
        trivy_p.write_text(json.dumps({"Results": [{"Vulnerabilities": [{"VulnerabilityID": "CVE-2026-TRIVY-ONLY"}]}]}))
        grype_p.write_text(json.dumps({"matches": [{"vulnerability": {"id": "CVE-2026-GRYPE-ONLY"}}]}))

        combined = vex_tracking._load_findings_file(str(trivy_p)) + vex_tracking._load_findings_file(str(grype_p))
        merged = vex_tracking.merge(None, combined, None, clock=lambda: "2026-09-03T00:00:00Z")
        assert set(merged["findings"]) == {"CVE-2026-TRIVY-ONLY", "CVE-2026-GRYPE-ONLY"}


class TestRealWorldScenario:
    """Test a realistic scenario with multiple findings across multiple runs."""

    def test_realistic_multi_run_scenario(self):
        run1_clock = "2026-08-01T12:00:00Z"
        run1_findings = [
            {"VulnerabilityID": "CVE-2026-OLD"},
            {"VulnerabilityID": "CVE-2026-FIXED"},
            {"VulnerabilityID": "CVE-2026-NEW"},
        ]
        run1_result = vex_tracking.merge(None, run1_findings, None, clock=lambda: run1_clock)
        assert set(run1_result["findings"]) == {"CVE-2026-OLD", "CVE-2026-FIXED", "CVE-2026-NEW"}

        run2_clock = "2026-08-15T12:00:00Z"
        run2_findings = [
            {"VulnerabilityID": "CVE-2026-OLD"},        # unchanged from run 1
            # CVE-2026-FIXED is gone (fixed upstream)
            {"VulnerabilityID": "CVE-2026-NEW"},        # still there
            {"VulnerabilityID": "CVE-2026-BRAND-NEW"},  # new finding
            {"VulnerabilityID": "CVE-2026-HUMAN-VERDICT"},  # will be dispositioned
        ]
        human_disposition = {"statements": [{"vulnerability": {"name": "CVE-2026-HUMAN-VERDICT"}, "status": "not_affected"}]}
        run2 = vex_tracking.merge(run1_result, run2_findings, human_disposition, clock=lambda: run2_clock)["findings"]

        assert set(run2) == {"CVE-2026-OLD", "CVE-2026-NEW", "CVE-2026-BRAND-NEW"}
        assert run2["CVE-2026-OLD"] == {"first_seen": run1_clock, "last_seen": run2_clock}
        assert run2["CVE-2026-NEW"] == {"first_seen": run1_clock, "last_seen": run2_clock}
        assert run2["CVE-2026-BRAND-NEW"] == {"first_seen": run2_clock, "last_seen": run2_clock}
