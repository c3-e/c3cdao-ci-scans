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
        """Test extraction of 'not_affected' verdicts."""
        vex_doc = {
            "statements": [
                {
                    "vulnerability": {"name": "CVE-2026-42533"},
                    "status": "not_affected",
                }
            ]
        }
        result = vex_tracking._extract_human_dispositions(vex_doc)
        assert "CVE-2026-42533" in result

    def test_extract_affected(self):
        """Test extraction of 'affected' verdicts."""
        vex_doc = {
            "statements": [
                {
                    "vulnerability": {"name": "CVE-2026-60005"},
                    "status": "affected",
                }
            ]
        }
        result = vex_tracking._extract_human_dispositions(vex_doc)
        assert "CVE-2026-60005" in result

    def test_extract_fixed(self):
        """Test extraction of 'fixed' verdicts."""
        vex_doc = {
            "statements": [
                {
                    "vulnerability": {"name": "CVE-2026-99999"},
                    "status": "fixed",
                }
            ]
        }
        result = vex_tracking._extract_human_dispositions(vex_doc)
        assert "CVE-2026-99999" in result

    def test_exclude_under_investigation(self):
        """Test that 'under_investigation' status is NOT counted as a disposition."""
        vex_doc = {
            "statements": [
                {
                    "vulnerability": {"name": "CVE-2026-11111"},
                    "status": "under_investigation",
                }
            ]
        }
        result = vex_tracking._extract_human_dispositions(vex_doc)
        assert "CVE-2026-11111" not in result

    def test_empty_doc(self):
        """Test extraction from empty doc."""
        result = vex_tracking._extract_human_dispositions(None)
        assert result == set()


class TestGetCveId:
    """Test CVE ID extraction from findings."""

    def test_trivy_format(self):
        """Test extraction from Trivy format (VulnerabilityID field)."""
        finding = {"VulnerabilityID": "CVE-2026-12345", "Severity": "HIGH"}
        cve_id = vex_tracking._get_cve_id(finding)
        assert cve_id == "CVE-2026-12345"

    def test_grype_format(self):
        """Test extraction from Grype format (vulnerability.id field — verified
        against a real `grype ... -o json` export; Grype has no
        vulnerability.name key at all)."""
        finding = {
            "vulnerability": {"id": "CVE-2026-67890"},
            "severity": "HIGH",
        }
        cve_id = vex_tracking._get_cve_id(finding)
        assert cve_id == "CVE-2026-67890"

    def test_no_cve_id(self):
        """Test handling of finding without CVE ID."""
        finding = {"severity": "HIGH"}
        cve_id = vex_tracking._get_cve_id(finding)
        assert cve_id is None


class TestRealGrypeSchemaRegression:
    """Locks in the bug-10 fix: Grype's REAL export schema (captured live via
    `grype alpine:3.12.0 -o json`) has no vulnerability.name key at all —
    only .id. A prior version of _get_cve_id() checked .name, which is
    always None on real output, silently dropping every Grype finding from
    the tracking doc. This uses a structurally-realistic match object (real
    field names/shapes from that capture), not a minimal shape that could
    pass even if .name were checked again by accident."""

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
        # The bug this guards: if _get_cve_id ever reverts to checking
        # .name instead of .id, this real-shaped object has no .name key
        # and the function would return None instead.
        assert "name" not in real_grype_match["vulnerability"]


class TestMergeFunctionality:
    """Test the core merge() function."""

    def test_first_run_new_finding(self):
        """Test AC-1 part 1: first run stamps first_issued and last_updated to clock value."""
        clock_value = "2026-08-01T13:00:00Z"

        def mock_clock():
            return clock_value

        current_findings = [{"VulnerabilityID": "CVE-2026-99999"}]

        result = vex_tracking.merge(None, current_findings, None, clock=mock_clock)

        # Verify the finding is in the output
        assert len(result["statements"]) == 1
        stmt = result["statements"][0]
        assert stmt["vulnerability"]["name"] == "CVE-2026-99999"

        # Verify both first_issued and last_updated are set to the clock value
        assert stmt["first_issued"] == clock_value
        assert stmt["last_updated"] == clock_value

    def test_preserved_first_issued_across_runs(self):
        """Test AC-1 part 2: second run preserves first_issued, updates last_updated."""
        first_clock = "2026-08-01T13:00:00Z"
        second_clock = "2026-09-02T13:00:00Z"

        # First run: create a prior doc with a finding
        prior_doc = {
            "@context": "https://openvex.dev/ns/v0.2.0",
            "@id": "https://openvex.dev/docs/tracking/vex-tracking-2026-08-01",
            "author": "c3cdao-ci-scans vex-tracking",
            "timestamp": first_clock,
            "version": 1,
            "statements": [
                {
                    "vulnerability": {"name": "CVE-2026-99999"},
                    "first_issued": first_clock,
                    "last_updated": first_clock,
                }
            ],
        }

        # Second run: process the same CVE again with a different clock
        current_findings = [{"VulnerabilityID": "CVE-2026-99999"}]

        def mock_clock():
            return second_clock

        result = vex_tracking.merge(prior_doc, current_findings, None, clock=mock_clock)

        # Verify the finding is in the output
        assert len(result["statements"]) == 1
        stmt = result["statements"][0]
        assert stmt["vulnerability"]["name"] == "CVE-2026-99999"

        # Verify first_issued is preserved, last_updated is updated
        assert stmt["first_issued"] == first_clock
        assert stmt["last_updated"] == second_clock

    def test_human_dispositioned_cve_excluded(self):
        """Test AC-2: CVEs covered by human verdicts are excluded from tracking doc."""
        current_findings = [
            {"VulnerabilityID": "CVE-2026-42533"},  # In human disposition
            {"VulnerabilityID": "CVE-2026-99999"},  # Not in human disposition
        ]

        human_disposition_doc = {
            "statements": [
                {
                    "vulnerability": {"name": "CVE-2026-42533"},
                    "status": "not_affected",
                }
            ]
        }

        clock_value = "2026-09-02T13:00:00Z"

        def mock_clock():
            return clock_value

        result = vex_tracking.merge(None, current_findings, human_disposition_doc, clock=mock_clock)

        # Verify only the non-dispositioned CVE is in the output
        assert len(result["statements"]) == 1
        assert result["statements"][0]["vulnerability"]["name"] == "CVE-2026-99999"

    def test_first_run_no_prior_doc(self):
        """Test AC-3: first run (no prior doc) works without error."""
        current_findings = [
            {"VulnerabilityID": "CVE-2026-11111"},
            {"VulnerabilityID": "CVE-2026-22222"},
        ]

        clock_value = "2026-09-02T13:00:00Z"

        def mock_clock():
            return clock_value

        # Should not raise any exception
        result = vex_tracking.merge(None, current_findings, None, clock=mock_clock)

        # Verify both findings are in the output with correct timestamps
        assert len(result["statements"]) == 2
        for stmt in result["statements"]:
            assert stmt["first_issued"] == clock_value
            assert stmt["last_updated"] == clock_value

    def test_output_never_has_signature(self):
        """Test AC-4: output never has signature or attestation field."""
        current_findings = [{"VulnerabilityID": "CVE-2026-99999"}]

        result = vex_tracking.merge(None, current_findings, None)

        # Verify no signature/attestation fields exist
        assert "signature" not in result
        assert "attestation" not in result
        assert "signatures" not in result
        assert "attestations" not in result
        assert "protected" not in result

    def test_empty_findings_list(self):
        """Test merging with no current findings."""
        result = vex_tracking.merge(None, [], None)

        # Should have empty statements
        assert result["statements"] == []

    def test_dedup_identical_cves(self):
        """Test that duplicate CVEs in current findings are deduplicated."""
        current_findings = [
            {"VulnerabilityID": "CVE-2026-99999"},
            {"VulnerabilityID": "CVE-2026-99999"},  # Duplicate
        ]

        result = vex_tracking.merge(None, current_findings, None)

        # Should only have one statement
        assert len(result["statements"]) == 1

    def test_grype_format_matching(self):
        """Test that Grype-format findings are correctly matched and merged."""
        prior_doc = {
            "statements": [
                {
                    "vulnerability": {"name": "CVE-2026-grype"},
                    "first_issued": "2026-08-01T13:00:00Z",
                    "last_updated": "2026-08-01T13:00:00Z",
                }
            ]
        }

        current_findings = [
            {
                "vulnerability": {"id": "CVE-2026-grype"},
                "severity": "HIGH",
            }
        ]

        clock_value = "2026-09-02T13:00:00Z"

        def mock_clock():
            return clock_value

        result = vex_tracking.merge(prior_doc, current_findings, None, clock=mock_clock)

        # Verify Grype-format finding is correctly matched and merged
        assert len(result["statements"]) == 1
        stmt = result["statements"][0]
        assert stmt["vulnerability"]["name"] == "CVE-2026-grype"
        assert stmt["first_issued"] == "2026-08-01T13:00:00Z"
        assert stmt["last_updated"] == clock_value

    def test_openvex_document_structure(self):
        """Test that output is a valid OpenVEX document structure."""
        current_findings = [{"VulnerabilityID": "CVE-2026-99999"}]

        result = vex_tracking.merge(None, current_findings, None)

        # Verify required OpenVEX fields
        assert "@context" in result
        assert result["@context"] == "https://openvex.dev/ns/v0.2.0"
        assert "@id" in result
        assert "author" in result
        assert "timestamp" in result
        assert "version" in result
        assert result["version"] == 1
        assert "statements" in result
        assert isinstance(result["statements"], list)

    def test_mixed_trivy_grype_findings(self):
        """Test handling a mix of Trivy and Grype format findings."""
        current_findings = [
            {"VulnerabilityID": "CVE-2026-trivy"},
            {"vulnerability": {"id": "CVE-2026-grype"}},
        ]

        result = vex_tracking.merge(None, current_findings, None)

        # Verify both are in the output
        assert len(result["statements"]) == 2
        cve_names = {s["vulnerability"]["name"] for s in result["statements"]}
        assert cve_names == {"CVE-2026-trivy", "CVE-2026-grype"}

    def test_clock_parameter_defaults_to_real_utc(self):
        """Test that clock parameter defaults to real UTC time when not provided."""
        current_findings = [{"VulnerabilityID": "CVE-2026-99999"}]

        result = vex_tracking.merge(None, current_findings, None)

        stmt = result["statements"][0]
        # Verify the timestamp looks like a valid ISO8601 string
        assert "T" in stmt["first_issued"]
        assert "Z" in stmt["first_issued"]
        # Verify it parses as a valid datetime
        parsed = datetime.fromisoformat(stmt["first_issued"].replace("Z", "+00:00"))
        assert isinstance(parsed, datetime)


class TestLoadFindingsFile:
    """Test _load_findings_file(): the function main() uses to load EACH
    scanner's export separately, so both can be combined — never an
    either/or choice between Trivy and Grype."""

    def test_missing_sentinel_returns_empty(self):
        """'-' means this scanner's export wasn't available; yields []."""
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
        result = vex_tracking._load_findings_file(str(p))
        ids = {f["VulnerabilityID"] for f in result}
        assert ids == {"CVE-2026-T1", "CVE-2026-T2"}

    def test_loads_grype_shape(self, tmp_path):
        grype_doc = {"matches": [{"vulnerability": {"id": "CVE-2026-G1"}}]}
        p = tmp_path / "grype-image.json"
        p.write_text(json.dumps(grype_doc))
        result = vex_tracking._load_findings_file(str(p))
        assert len(result) == 1
        assert result[0]["vulnerability"]["id"] == "CVE-2026-G1"

    def test_both_files_combine_not_either_or(self, tmp_path):
        """The exact regression this fix targets: a prior implementation
        picked ONE scanner's file ('prefer Grype, fall back to Trivy') and
        silently dropped the other. Loading both and concatenating must
        yield the union, not just one scanner's findings."""
        trivy_doc = {"Results": [{"Vulnerabilities": [{"VulnerabilityID": "CVE-2026-TRIVY-ONLY"}]}]}
        grype_doc = {"matches": [{"vulnerability": {"id": "CVE-2026-GRYPE-ONLY"}}]}
        trivy_p = tmp_path / "trivy-image.json"
        grype_p = tmp_path / "grype-image.json"
        trivy_p.write_text(json.dumps(trivy_doc))
        grype_p.write_text(json.dumps(grype_doc))

        combined = vex_tracking._load_findings_file(str(trivy_p)) + vex_tracking._load_findings_file(
            str(grype_p)
        )
        merged = vex_tracking.merge(None, combined, None, clock=lambda: "2026-09-03T00:00:00Z")
        cve_names = {s["vulnerability"]["name"] for s in merged["statements"]}
        # Would fail if either scanner's findings were silently dropped.
        assert cve_names == {"CVE-2026-TRIVY-ONLY", "CVE-2026-GRYPE-ONLY"}


class TestRealWorldScenario:
    """Test a realistic scenario with multiple findings across multiple runs."""

    def test_realistic_multi_run_scenario(self):
        """Test a realistic scenario: three runs with changing findings."""
        # Run 1: Initial scan with 3 findings
        run1_clock = "2026-08-01T12:00:00Z"
        run1_findings = [
            {"VulnerabilityID": "CVE-2026-OLD"},
            {"VulnerabilityID": "CVE-2026-FIXED"},
            {"VulnerabilityID": "CVE-2026-NEW"},
        ]

        def clock_run1():
            return run1_clock

        run1_result = vex_tracking.merge(None, run1_findings, None, clock=clock_run1)
        assert len(run1_result["statements"]) == 3

        # Run 2: Some findings fixed, new one added, one human-dispositioned
        run2_clock = "2026-08-15T12:00:00Z"
        run2_findings = [
            {"VulnerabilityID": "CVE-2026-OLD"},  # Unchanged from run 1
            # CVE-2026-FIXED is gone (fixed upstream)
            {"VulnerabilityID": "CVE-2026-NEW"},  # Still there
            {"VulnerabilityID": "CVE-2026-BRAND-NEW"},  # New finding
            {"VulnerabilityID": "CVE-2026-HUMAN-VERDICT"},  # Will be dispositioned
        ]

        human_disposition = {
            "statements": [
                {
                    "vulnerability": {"name": "CVE-2026-HUMAN-VERDICT"},
                    "status": "not_affected",
                }
            ]
        }

        def clock_run2():
            return run2_clock

        run2_result = vex_tracking.merge(
            run1_result, run2_findings, human_disposition, clock=clock_run2
        )

        # Should have 3 findings (excluding the human-dispositioned one)
        assert len(run2_result["statements"]) == 3

        # Verify CVE-2026-OLD preserved its first_issued from run 1
        old_stmt = next(s for s in run2_result["statements"] if s["vulnerability"]["name"] == "CVE-2026-OLD")
        assert old_stmt["first_issued"] == run1_clock
        assert old_stmt["last_updated"] == run2_clock

        # Verify CVE-2026-NEW preserved its first_issued from run 1
        new_stmt = next(s for s in run2_result["statements"] if s["vulnerability"]["name"] == "CVE-2026-NEW")
        assert new_stmt["first_issued"] == run1_clock
        assert new_stmt["last_updated"] == run2_clock

        # Verify CVE-2026-BRAND-NEW got new timestamps
        brand_new_stmt = next(s for s in run2_result["statements"] if s["vulnerability"]["name"] == "CVE-2026-BRAND-NEW")
        assert brand_new_stmt["first_issued"] == run2_clock
        assert brand_new_stmt["last_updated"] == run2_clock

        # Verify CVE-2026-HUMAN-VERDICT is not in the output
        cve_names = {s["vulnerability"]["name"] for s in run2_result["statements"]}
        assert "CVE-2026-HUMAN-VERDICT" not in cve_names
