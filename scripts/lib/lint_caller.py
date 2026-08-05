# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
"""Fail-closed convention lint for the derived security gate (v0.6).

Replaces the v0.5.x Makefile.ci contract validation: the gate derives the
build/scan set from the consumer's committed Compose file, Dockerfiles, and
rendered Helm chart (see derive_bom.py), and this module enforces the plan's
conventions before any build starts. One function per rule id (rule groups
live in lint_rules/); every finding is a verdict object:

    {"rule_id": ..., "level": "block" | "warn", "message": ...,
     "remediation_ref": "docs/CI-CONTRACT.md#rule-<rule-id>"}

Any block verdict fails the run (exit 1); warn verdicts are reported and
never block.

Rule ids: compose-missing, compose-no-builds, matrix-cap, compose-image-tag,
compose-healthcheck, dependency-shape, build-input-explicit,
build-context-excludes, compose-platform, bake-resolve, hardened-args,
chart-missing, chart-undeclared, chart-resolve, chart-readiness,
smoke-target, ship-set, smoke-resource-unknown, built-unscheduled,
gate-job-id.

Caller structure rules carried over from v0.5.x (load-bearing only):
gate-ref-pin (the reusable-workflow ref is a full 40-hex commit SHA),
gate-job-id (the calling job id is exactly 'security-scan' — half of the
required check context), no-secrets-inherit + missing-secret-map (all four
registry secrets mapped explicitly), unknown-input (the with: surface is
exactly the v0.6 inputs; removed v0.5.x inputs are rejected by name), and
unreadable-caller (fail closed on an unparseable caller).

Remediation refs point at onboarding-doc anchors authored at the docs
cutover; the anchor names are stable now.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any

from compose_facts import classify_services, load_compose
from lint_rules import Verdict, load_gha_workflow, verdict
from lint_rules.chart import (
    built_unscheduled,
    chart_readiness,
    render_chart,
    ship_set,
    smoke_resource_unknown,
    smoke_target,
)
from lint_rules.compose import (
    bake_resolve,
    build_context_excludes,
    build_input_explicit,
    compose_healthcheck,
    compose_image_tag,
    compose_missing,
    compose_no_builds,
    compose_platform,
    dependency_shape,
    hardened_args,
    matrix_cap,
)

GATE_WORKFLOW_BASENAME = "reusable-security-gate.yml"
REQUIRED_SECRETS = (
    "CGR_PULL_TOKEN",
    "CGR_PULL_USERNAME",
    "IRONBANK_TOKEN",
    "IRONBANK_USERNAME",
)
KNOWN_INPUTS = (
    "chart_path",
    "compose_file",
    "image_only",
    "namespace",
    "release",
    "smoke_resources",
    "values_local",
)
REMOVED_INPUTS = ("contract_file", "require_hardened_bases", "scan_image")
_FULL_SHA_RE = re.compile(r"@[0-9a-f]{40}$")
# Helm vendors chart dependencies into a `charts/` subdirectory (tgz or,
# once unpacked, a nested chart tree with its own Chart.yaml) — excluded
# from the repo-wide chart-undeclared glob so a legitimate dependency tree
# never false-positives (e.g. cra's vendored fullstack-template).
_VENDORED_CHART_DIR = "charts"


def chart_missing(chart_path: Path) -> list[Verdict]:
    """A non-image_only consumer's declared chart_path must exist and be a chart."""
    if (chart_path / "Chart.yaml").is_file():
        return []
    return [
        verdict(
            "chart-missing",
            f"no Helm chart at '{chart_path}' (Chart.yaml not found); "
            "image_only is false, so a deployable chart is required",
        )
    ]


def chart_undeclared(repo_root: Path) -> list[Verdict]:
    """An image_only consumer must not carry an undeclared chart anywhere.

    Repo-wide glob (not chart_path-only): an image_only caller has no
    chart_path checked by anything downstream, so a chart living at any
    other path in the repo would otherwise evade detection entirely —
    the exact rescreen pre-rollout shape (owned `helm/resume-screener`
    while declaring image_only: true).
    """
    found = [
        p
        for p in sorted(repo_root.rglob("Chart.yaml"))
        if _VENDORED_CHART_DIR not in p.relative_to(repo_root).parts[:-1]
    ]
    if not found:
        return []
    return [
        verdict(
            "chart-undeclared",
            "image_only is true but the repo declares a Helm chart at "
            + ", ".join(str(p) for p in found)
            + "; either remove the chart or set image_only: false and "
            "declare chart_path",
        )
    ]


def chart_resolve(
    chart_path: Path, values: list[Path] | None = None
) -> tuple[list[dict[str, Any]] | None, list[Verdict]]:
    """Resolve the rendered chart, converting a render failure into a verdict.

    Mirrors `bake_resolve`: `helm template` fails closed (SystemExit) when
    a chart's dependencies were never built — missing repo/path, or simply
    not vendored (F-C1; the plan job now runs `helm dependency build`
    first, but a genuinely broken dependency still fails here) — this
    converts that failure into a named, remediation-linked block instead
    of letting the SystemExit surface as a raw stack trace.
    """
    try:
        return render_chart(chart_path, values), []
    except SystemExit as e:
        return None, [verdict("chart-resolve", str(e.code))]


def _find_gate_job(jobs: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    for job_id, job in jobs.items():
        if isinstance(job, dict) and GATE_WORKFLOW_BASENAME in str(
            job.get("uses") or ""
        ):
            return job_id, job
    return None


def lint_caller_workflow(caller_path: Path) -> list[Verdict]:
    """Structure rules for the consumer's caller workflow file.

    Carried over from v0.5.x by user decision (load-bearing only):
    gate-ref-pin, no-secrets-inherit + missing-secret-map, unknown-input
    (which also rejects the removed v0.5.x inputs by name), and the
    fail-closed unreadable-caller.
    """
    try:
        wf = load_gha_workflow(caller_path)
    except SystemExit as e:
        return [verdict("unreadable-caller", str(e.code))]
    jobs = wf.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        return [verdict("unreadable-caller", f"{caller_path}: no jobs mapping")]
    gate = _find_gate_job(jobs)
    if gate is None:
        return [
            verdict(
                "unreadable-caller",
                f"{caller_path}: no job whose 'uses:' matches {GATE_WORKFLOW_BASENAME}",
            )
        ]
    gate_id, gate_job = gate

    verdicts = []
    if gate_id != "security-scan":
        verdicts.append(
            verdict(
                "gate-job-id",
                f"gate job id is '{gate_id}', must be 'security-scan' — the "
                "job id is half of the required check context "
                "'security-scan / Security Gate'; a different id reports "
                "under a different context and the ruleset silently no "
                "longer matches",
            )
        )
    uses = str(gate_job.get("uses"))
    if not _FULL_SHA_RE.search(uses):
        verdicts.append(
            verdict(
                "gate-ref-pin",
                f"job '{gate_id}' uses '{uses}'; the gate ref must be pinned "
                "by a full 40-hex commit SHA (a release tag may be recorded "
                "as a trailing comment)",
            )
        )

    secrets = gate_job.get("secrets")
    if secrets == "inherit":
        verdicts.append(
            verdict(
                "no-secrets-inherit",
                f"job '{gate_id}' uses 'secrets: inherit', which silently "
                "passes nothing across owners; map the four gate secrets "
                "explicitly",
            )
        )
    else:
        mapped = secrets if isinstance(secrets, dict) else {}
        verdicts.extend(
            verdict(
                "missing-secret-map",
                f"secret '{name}' not mapped on job '{gate_id}'",
            )
            for name in REQUIRED_SECRETS
            if name not in mapped
        )

    with_map = gate_job.get("with")
    for key in with_map if isinstance(with_map, dict) else {}:
        if key in KNOWN_INPUTS:
            continue
        if key in REMOVED_INPUTS:
            verdicts.append(
                verdict(
                    "unknown-input",
                    f"with: key '{key}' was removed in v0.6 (the gate derives "
                    "build facts from the compose file, Dockerfiles, and "
                    "chart); delete it from the caller",
                )
            )
        else:
            verdicts.append(
                verdict(
                    "unknown-input",
                    f"with: key '{key}' is not a gate input "
                    f"(known: {', '.join(KNOWN_INPUTS)})",
                )
            )
    return verdicts


# --- pipeline / CLI -------------------------------------------------------------


def convention_verdicts(
    compose_path: Path,
    chart_path: Path | None = None,
    values_local: Path | None = None,
    image_only: bool = False,
    smoke_resources: str = "",
    consumer_root: Path | None = None,
) -> list[Verdict]:
    """The full fail-closed convention pipeline for one consumer checkout.

    Chart rules run only for non-image_only consumers; bake resolution
    runs only when the committed shapes are already clean, so shape
    violations surface before bake ever executes. chart-missing/
    chart-undeclared are verified declaration checks (BL-1): image_only
    is either backed by no chart anywhere in the repo, or a real chart
    exists at chart_path — never a stale, unverified flag.
    """
    presence = compose_missing(compose_path)
    if presence:
        return presence
    compose = load_compose(compose_path)
    classified = classify_services(compose)
    verdicts = [
        *compose_no_builds(classified),
        *matrix_cap(classified),
        *compose_image_tag(compose, classified),
        *compose_healthcheck(compose, classified),
        *compose_platform(compose),
        *dependency_shape(classified),
        *build_input_explicit(compose, classified),
        *build_context_excludes(compose_path, compose, classified),
        *hardened_args(compose_path, compose, classified),
        *smoke_resource_unknown(smoke_resources),
    ]
    if not verdicts:
        _, resolve = bake_resolve(compose_path, classified["targets"])
        verdicts.extend(resolve)
    repo_root = consumer_root or compose_path.parent
    if image_only:
        return verdicts + chart_undeclared(repo_root)
    if chart_path is None:
        return verdicts
    verdicts += chart_missing(chart_path)
    if not any(v["level"] == "block" for v in verdicts):
        rendered, resolve = chart_resolve(
            chart_path, [values_local] if values_local else None
        )
        verdicts.extend(resolve)
        if rendered is not None:
            verdicts += [
                *chart_readiness(rendered),
                *smoke_target(rendered),
                *ship_set(compose, classified, rendered),
                *built_unscheduled(compose, classified, rendered),
            ]
    return verdicts


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Fail-closed convention lint for the derived security gate."
    )
    parser.add_argument("caller", type=Path, help="caller workflow YAML to lint")
    parser.add_argument(
        "--consumer-root",
        type=Path,
        default=None,
        help="consumer repo root; enables the compose/Dockerfile/chart rules",
    )
    args = parser.parse_args(argv)
    verdicts = lint_caller_workflow(args.caller)
    if args.consumer_root is not None:
        with_map: dict[str, Any] = {}
        try:
            wf = load_gha_workflow(args.caller)
            gate = _find_gate_job(wf.get("jobs") or {})
            if gate and isinstance(gate[1].get("with"), dict):
                with_map = gate[1]["with"]
        except SystemExit:
            pass  # already a fail-closed unreadable-caller verdict
        chart = with_map.get("chart_path")
        values = with_map.get("values_local")
        verdicts.extend(
            convention_verdicts(
                args.consumer_root
                / str(with_map.get("compose_file", "docker-compose.yml")),
                chart_path=args.consumer_root / str(chart) if chart else None,
                values_local=args.consumer_root / str(values) if values else None,
                image_only=with_map.get("image_only") is True,
                smoke_resources=str(with_map.get("smoke_resources", "")),
                consumer_root=args.consumer_root,
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
    rc = 1
    try:
        rc = main(sys.argv[1:])
        sys.stdout.flush()
    except BrokenPipeError:
        # A downstream reader (e.g. `... | grep -q`) closed the pipe after
        # matching; the verdict in rc is already computed, so keep it.
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
    sys.exit(rc)
