# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
"""Fail-closed convention lint for the publish-staging-chart caller.

`lint_caller.py` gates the `reusable-security-gate.yml` caller's shape
(ref-pin discipline, required secrets, known inputs, decoy-job
detection). There was no equivalent for `publish-staging-chart.yml`'s
caller — every real bug found onboarding Phase 2 pilots (a missing
`target` field on the old hand-typed `images[]` tuple, a missing
caller-side `packages: write` permission, a missing `routes:` key in the
chart's `values.yaml`) was discovered ad hoc, per pilot, at merge time
instead of caught mechanically at lint time. This module is that
equivalent, scoped to `publish-staging-chart.yml`'s own actual shape
rather than a generalization of `lint_caller.py`'s security-gate-specific
internals (GATE_WORKFLOW_BASENAME, the four registry secrets, the
compose/Dockerfile/chart-render convention pipeline) — this workflow has
none of that: no build matrix, no image_only mode. The shared verdict
infrastructure (`lint_rules.verdict`/`load_gha_workflow`) is reused; the
rule set below is independent.

NOTE on the retired `images[]` rules: Issue I (single source of truth
for the publish target list) replaced the caller's hand-typed
`images[]` JSON array entirely with a `derive-publish-targets` job that
re-derives the target list from `compose_file` at merge time — so the
two rules this module originally had for that shape
(`publish-images-target-required`, `publish-images-unparseable`) no
longer apply to anything a caller declares and have been removed. A
caller-side `compose_file`/`publish_targets` mismatch is now caught by
`derive-publish-targets`' own fail-closed runtime check (see
docs/PUBLISH-STAGING-CHART.md), not by this lint — there is no
consumer-repo-independent way to validate a CSV of target names against
a compose file's actual build targets without checking out that repo,
which is exactly what `--consumer-root` plus a real `docker buildx bake
--print` would require; not worth duplicating plan's own derivation here
for a lint-time nice-to-have.

Every finding is a verdict object:

    {"rule_id": ..., "level": "block" | "warn", "message": ...,
     "remediation_ref": "docs/PUBLISH-STAGING-CHART.md#rule-<rule-id>"}

Any block verdict fails the run (exit 1); warn verdicts are reported and
never block.

Rule ids:
  publish-ref-pin        block  uses: not pinned by a full 40-hex SHA
                                 (mirrors lint_caller.py's gate-ref-pin)
  publish-decoy-job       block  more than one job in the caller calls
                                 publish-staging-chart.yml (mirrors
                                 lint_caller.py's decoy-gate-job — this
                                 workflow's own "Resolve callee (ci-scans)
                                 ref" step does the identical first-match
                                 uses: parse the gate's resolver does, so
                                 it is equally exposed to a second,
                                 differently-pinned decoy job)
  publish-packages-write-missing
                          block  publish_images: true is set but neither
                                 the caller's workflow-level nor
                                 job-level permissions: block grants
                                 packages: write — the exact bug that
                                 caused a real, hard-to-diagnose failure
                                 in production onboarding (a missing
                                 grant, not a missing declaration: GitHub
                                 Actions caps a reusable workflow's
                                 granted permissions at whatever the
                                 caller itself grants, independent of the
                                 callee's own permissions)
  publish-permissions-both-levels
                          block  permissions: declared at BOTH the
                                 workflow level and the calling job level
                                 — confirmed live (see
                                 docs/PUBLISH-STAGING-CHART.md's "Caller
                                 gotcha") to silently produce
                                 'conclusion: startup_failure' with zero
                                 jobs allocated and no error message
                                 anywhere
  publish-chart-routes-missing
                          warn   the consumer chart's values.yaml has no
                                 non-empty routes: key (top-level or
                                 nested under fullstack-template.routes:)
                                 — currently only discovered at actual
                                 merge time by publish-staging-chart.yml's
                                 own runtime chart-shape check, not at
                                 lint time; warn, not block, since the
                                 --consumer-root chart_path may not exist
                                 yet at lint time for a brand-new pilot
  unreadable-caller       block  the caller workflow cannot be parsed, or
                                 no job's uses: matches
                                 publish-staging-chart.yml
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import yaml
from lint_rules import Verdict, load_gha_workflow, verdict

PUBLISH_WORKFLOW_BASENAME = "publish-staging-chart.yml"
ONBOARDING_DOC = "docs/PUBLISH-STAGING-CHART.md"
_FULL_SHA_RE = re.compile(r"@[0-9a-f]{40}$")


def _v(rule_id: str, message: str, level: str = "block") -> Verdict:
    return verdict(rule_id, message, level=level, doc=ONBOARDING_DOC)


def _find_publish_jobs(jobs: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    return [
        (job_id, job)
        for job_id, job in jobs.items()
        if isinstance(job, dict)
        and PUBLISH_WORKFLOW_BASENAME in str(job.get("uses") or "")
    ]


def _permissions_map(block: Any) -> dict[str, Any]:
    return block if isinstance(block, dict) else {}


def _ref_pin_verdicts(job_id: str, job: dict[str, Any]) -> list[Verdict]:
    uses = str(job.get("uses"))
    if _FULL_SHA_RE.search(uses):
        return []
    return [
        _v(
            "publish-ref-pin",
            f"job '{job_id}' uses '{uses}'; the publish-staging-chart ref "
            "must be pinned by a full 40-hex commit SHA (a release tag may "
            "be recorded as a trailing comment)",
        )
    ]


def _permissions_verdicts(
    wf: dict[str, Any], job: dict[str, Any], publish_images: bool
) -> list[Verdict]:
    workflow_perms = _permissions_map(wf.get("permissions"))
    job_perms = _permissions_map(job.get("permissions"))
    verdicts: list[Verdict] = []
    if publish_images:
        has_write = (
            workflow_perms.get("packages") == "write"
            or job_perms.get("packages") == "write"
        )
        if not has_write:
            verdicts.append(
                _v(
                    "publish-packages-write-missing",
                    "publish_images is true but neither the caller's "
                    "workflow-level nor job-level permissions: block "
                    "grants 'packages: write'; GitHub Actions caps a "
                    "reusable workflow's granted permissions at whatever "
                    "the caller itself grants, independent of the "
                    "callee's own permissions -- without this grant, "
                    "publish-images-deferred's imagetools push fails at "
                    "merge time",
                )
            )
    if workflow_perms and job_perms:
        verdicts.append(
            _v(
                "publish-permissions-both-levels",
                "permissions: is declared at BOTH the workflow level and "
                "the calling job level; confirmed live to silently "
                "produce 'conclusion: startup_failure' with zero jobs "
                "allocated and no error message anywhere -- keep "
                "permissions: at the workflow level only",
            )
        )
    return verdicts


def lint_caller_workflow(caller_path: Path) -> list[Verdict]:
    try:
        wf = load_gha_workflow(caller_path)
    except SystemExit as e:
        return [_v("unreadable-caller", str(e.code))]
    jobs = wf.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        return [_v("unreadable-caller", f"{caller_path}: no jobs mapping")]
    matches = _find_publish_jobs(jobs)
    if not matches:
        return [
            _v(
                "unreadable-caller",
                f"{caller_path}: no job whose 'uses:' matches "
                f"{PUBLISH_WORKFLOW_BASENAME}",
            )
        ]

    verdicts: list[Verdict] = []
    if len(matches) > 1:
        # Same decoy-vector rationale as lint_caller.py's decoy-gate-job:
        # this workflow's own "Resolve callee (ci-scans) ref" step takes
        # the FIRST uses: match in the caller file (see
        # publish-staging-chart.yml), so a second, differently-pinned job
        # calling this workflow can hijack which ci-scans ref the real
        # run resolves its own tooling from.
        verdicts.append(
            _v(
                "publish-decoy-job",
                f"{len(matches)} jobs call {PUBLISH_WORKFLOW_BASENAME} "
                f"({', '.join(j for j, _ in matches)}); exactly one is "
                "allowed per caller, run or not",
            )
        )
    job_id, job = matches[0]
    with_map = job.get("with") if isinstance(job.get("with"), dict) else {}
    publish_images = with_map.get("publish_images") is True

    verdicts += _ref_pin_verdicts(job_id, job)
    verdicts += _permissions_verdicts(wf, job, publish_images)
    return verdicts


def chart_routes_missing(values_path: Path) -> list[Verdict]:
    """Warn-level: mirrors publish-staging-chart.yml's own runtime
    check-jsonschema routes-contract validation (its "Validate chart
    shape" step), but at lint time instead of merge time. Warn, not
    block: a brand-new pilot's chart may not exist yet at lint time
    (chart_path is caller-repo-relative, and lint runs against a
    checkout that may predate the chart), so this can't fail closed the
    way the real merge-time check does.
    """
    if not values_path.is_file():
        return [
            _v(
                "publish-chart-routes-missing",
                f"'{values_path}' does not exist; cannot verify a "
                "non-empty 'routes:' key. This will fail at merge time in "
                "publish-staging-chart.yml's own runtime chart-shape "
                "check if the chart still has no values.yaml by then",
                level="warn",
            )
        ]
    try:
        values = yaml.safe_load(values_path.read_text()) or {}
    except yaml.YAMLError as e:
        return [
            _v(
                "publish-chart-routes-missing",
                f"'{values_path}' is not valid YAML: {e}",
                level="warn",
            )
        ]
    if not isinstance(values, dict):
        values = {}
    top = values.get("routes")
    engine = values.get("fullstack-template")
    nested = engine.get("routes") if isinstance(engine, dict) else None
    if (isinstance(top, list) and top) or (isinstance(nested, list) and nested):
        return []
    return [
        _v(
            "publish-chart-routes-missing",
            f"'{values_path}' declares no non-empty 'routes:' key (either "
            "top-level or nested under 'fullstack-template.routes:'); "
            "publish-staging-chart.yml's own runtime chart-shape check "
            "will block the merge on this -- fix it now rather than "
            "discovering it at merge time",
            level="warn",
        )
    ]


def convention_verdicts(consumer_root: Path, chart_path: Path | None) -> list[Verdict]:
    if chart_path is None:
        return []
    return chart_routes_missing(chart_path / "values.yaml")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Fail-closed convention lint for the "
        "publish-staging-chart caller."
    )
    parser.add_argument("caller", type=Path, help="caller workflow YAML to lint")
    parser.add_argument(
        "--consumer-root",
        type=Path,
        default=None,
        help="consumer repo root; enables the values.yaml routes-key check",
    )
    args = parser.parse_args(argv)
    verdicts = lint_caller_workflow(args.caller)
    if args.consumer_root is not None:
        with_map: dict[str, Any] = {}
        try:
            wf = load_gha_workflow(args.caller)
            jobs = wf.get("jobs") or {}
            matches = _find_publish_jobs(jobs)
            if matches and isinstance(matches[0][1].get("with"), dict):
                with_map = matches[0][1]["with"]
        except SystemExit:
            pass  # already a fail-closed unreadable-caller verdict
        chart = with_map.get("chart_path")
        verdicts.extend(
            convention_verdicts(
                args.consumer_root,
                args.consumer_root / str(chart) if chart else None,
            )
        )
    for v in verdicts:
        print(
            f"{v['rule_id']}: {v['level']}: {v['message']} "
            f"(remediation: {v['remediation_ref']})"
        )
    if any(v["level"] == "block" for v in verdicts):
        return 1
    print(f"OK: {args.caller}: caller lint clean")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
