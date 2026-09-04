"""Unit tests for scripts/lib/lint_caller_publish.py — the
publish-staging-chart caller lint. Mirrors test_lint_rules.py's style
for lint_caller.py: one rule id under test per group, rule functions
imported directly and exercised with in-memory workflow dicts /
tmp_path chart fixtures. CLI end-to-end verdicts (exit code by
clean-*/bad-* filename convention) are covered separately by
scripts/test-lint-fixtures-publish.sh against
tests/fixtures/callers_publish/.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

from lint_caller_publish import (  # noqa: E402
    chart_routes_missing,
    lint_caller_workflow,
)

FIXTURES = REPO_ROOT / "tests" / "fixtures" / "callers_publish"


def _rule_ids(verdicts: list[dict]) -> set[str]:
    return {v["rule_id"] for v in verdicts}


# --- publish-ref-pin --------------------------------------------------------


def test_ref_pin_rejects_branch_ref():
    verdicts = lint_caller_workflow(FIXTURES / "bad-unpinned-ref.yml")
    assert "publish-ref-pin" in _rule_ids(verdicts)


def test_ref_pin_accepts_full_sha():
    verdicts = lint_caller_workflow(FIXTURES / "clean-minimal.yml")
    assert "publish-ref-pin" not in _rule_ids(verdicts)


# --- publish-packages-write-missing -----------------------------------------


def test_packages_write_missing_flagged_when_absent():
    verdicts = lint_caller_workflow(FIXTURES / "bad-missing-packages-write.yml")
    assert "publish-packages-write-missing" in _rule_ids(verdicts)


def test_packages_write_present_at_workflow_level_passes():
    verdicts = lint_caller_workflow(FIXTURES / "clean-publish-images-true.yml")
    assert "publish-packages-write-missing" not in _rule_ids(verdicts)


def test_packages_write_rule_inert_when_publish_images_false():
    verdicts = lint_caller_workflow(FIXTURES / "clean-minimal.yml")
    assert "publish-packages-write-missing" not in _rule_ids(verdicts)


# --- publish-permissions-both-levels -----------------------------------------


def test_both_permission_levels_flagged():
    verdicts = lint_caller_workflow(FIXTURES / "bad-both-permission-levels.yml")
    assert "publish-permissions-both-levels" in _rule_ids(verdicts)


def test_workflow_level_only_permissions_not_flagged():
    verdicts = lint_caller_workflow(FIXTURES / "clean-publish-images-true.yml")
    assert "publish-permissions-both-levels" not in _rule_ids(verdicts)


# --- publish-decoy-job -------------------------------------------------------


def test_decoy_job_flagged():
    verdicts = lint_caller_workflow(FIXTURES / "bad-decoy-job.yml")
    assert "publish-decoy-job" in _rule_ids(verdicts)


def test_single_job_not_flagged_as_decoy():
    verdicts = lint_caller_workflow(FIXTURES / "clean-minimal.yml")
    assert "publish-decoy-job" not in _rule_ids(verdicts)


# --- publish-chart-routes-missing (warn) ------------------------------------
# Same four cases as test_chart_shape_routes.py's CASES, so lint-time and
# runtime check-jsonschema checks agree on every one.


def _write_values(tmp_path: Path, values: dict) -> Path:
    chart_dir = tmp_path / "chart"
    chart_dir.mkdir()
    values_path = chart_dir / "values.yaml"
    values_path.write_text(yaml.safe_dump(values))
    return values_path


def test_routes_missing_flags_no_routes_key(tmp_path):
    values_path = _write_values(tmp_path, {"image": {"repository": "x", "tag": "1"}})
    verdicts = chart_routes_missing(values_path)
    assert len(verdicts) == 1
    assert verdicts[0]["rule_id"] == "publish-chart-routes-missing"
    assert verdicts[0]["level"] == "warn"


def test_routes_missing_flags_empty_routes_list(tmp_path):
    values_path = _write_values(tmp_path, {"routes": []})
    verdicts = chart_routes_missing(values_path)
    assert len(verdicts) == 1
    assert verdicts[0]["level"] == "warn"


def test_routes_present_top_level_passes(tmp_path):
    values_path = _write_values(
        tmp_path, {"routes": [{"path": "/", "service": "web"}]}
    )
    assert chart_routes_missing(values_path) == []


def test_routes_present_nested_fullstack_template_passes(tmp_path):
    values_path = _write_values(
        tmp_path,
        {"fullstack-template": {"routes": [{"path": "/", "service": "web"}]}},
    )
    assert chart_routes_missing(values_path) == []


def test_routes_missing_file_warns_not_blocks(tmp_path):
    verdicts = chart_routes_missing(tmp_path / "does-not-exist" / "values.yaml")
    assert len(verdicts) == 1
    assert verdicts[0]["level"] == "warn"


def test_routes_check_is_warn_never_blocks_the_cli(tmp_path, capsys):
    """A chart missing routes: must still exit 0; warn findings are reported
    but never block, unlike every block-level rule above."""
    from lint_caller_publish import main

    consumer_root = tmp_path / "consumer"
    consumer_root.mkdir()
    _write_values(consumer_root, {"image": {"repository": "x", "tag": "1"}})
    caller = consumer_root / "caller.yml"
    caller.write_text(
        "name: Publish Staging Chart\n"
        "on:\n  pull_request:\n    types: [closed]\n"
        "permissions:\n  contents: read\n"
        "jobs:\n"
        "  publish-staging-chart:\n"
        "    uses: c3-e/c3cdao-ci-scans/.github/workflows/"
        "publish-staging-chart.yml@" + "0" * 40 + "\n"
        "    with:\n"
        "      chart_path: chart\n"
    )
    rc = main([str(caller), "--consumer-root", str(consumer_root)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "publish-chart-routes-missing" in out
    assert "warn" in out


def test_remediation_ref_points_at_publish_doc():
    verdicts = lint_caller_workflow(FIXTURES / "bad-unpinned-ref.yml")
    assert all(
        v["remediation_ref"].startswith("docs/PUBLISH-STAGING-CHART.md#")
        for v in verdicts
    )
