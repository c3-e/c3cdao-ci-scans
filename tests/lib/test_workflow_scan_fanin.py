"""Contract tests for the v0.6 scan matrix, caller surface, and fan-in.

Static drift guards on .github/workflows/reusable-security-gate.yml and
templates/callers/security-gate.yml: the workflow_call surface is exactly
the v0.6 inputs (the original 7, plus hardened_base_registry for
caller-declared registry tier and publish_images for the digest-verified
quarantine publish mechanism) + 4 secrets, image-scan fans out over the
plan matrix consuming per-leg artifacts with one designated source-SBOM leg, and the
fan-in required-check context `security-scan / Security Gate` survives
byte-for-byte. The smoke rewiring modifies the same file; these
assertions keep the scan/fan-in surface from regressing.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/reusable-security-gate.yml"

V06_INPUTS = {
    "chart_path",
    "compose_file",
    "hardened_base_registry",
    "image_only",
    "namespace",
    "publish_images",
    "release",
    "smoke_resources",
    "values_local",
}
V06_SECRETS = {
    "CGR_PULL_TOKEN",
    "CGR_PULL_USERNAME",
    "IRONBANK_TOKEN",
    "IRONBANK_USERNAME",
}
REMOVED_INPUTS = (
    "builder_image",
    "cluster_name",
    "contract_file",
    "ironbank_builder_image",
    "ironbank_registry",
    "ironbank_runtime_image",
    "require_hardened_bases",
    "runtime_image",
    "scan_image",
    "smoke_secrets",
)


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def test_workflow_call_inputs_are_exactly_the_v06_set():
    call = _workflow()[True]["workflow_call"]  # YAML parses bare `on` as True
    assert set(call["inputs"]) == V06_INPUTS


def test_workflow_call_secrets_are_exactly_the_four():
    call = _workflow()[True]["workflow_call"]
    assert set(call["secrets"]) == V06_SECRETS


def test_no_job_references_a_removed_input():
    text = WORKFLOW.read_text()
    for name in REMOVED_INPUTS:
        pattern = rf"inputs\.{name}\b"
        assert not re.search(pattern, text), f"workflow still references inputs.{name}"


# --- fan-in / required-check context (byte-locked) ----------------------------

FAN_IN_NEEDS = {
    "plan",
    "build",
    "secrets-scan",
    "sast-semgrep",
    "sast-sonarqube",
    "helm-check",
    "cluster-smoke",
    "image-scan",
}


def test_fanin_check_context_survives_byte_for_byte():
    gate = _workflow()["jobs"]["security-gate"]
    assert gate["name"] == "Security Gate"
    assert gate["if"] == "always()"
    assert set(gate["needs"]) == FAN_IN_NEEDS


def test_fanin_evaluates_via_gate_evaluator():
    gate = _workflow()["jobs"]["security-gate"]
    text = "\n".join(str(s.get("run", "")) for s in gate["steps"])
    assert "evaluate_security_gate.py" in text


def test_caller_template_keeps_required_check_job_id():
    caller = yaml.safe_load(
        (ROOT / "templates/callers/security-gate.yml").read_text()
    )
    # `security-scan` is half of the required check context
    # `security-scan / Security Gate`; renaming it un-gates merges.
    assert "security-scan" in caller["jobs"]


# --- image-scan per-leg wiring --------------------------------------------------


def test_image_scan_is_matrix_over_plan_output():
    scan = _workflow()["jobs"]["image-scan"]
    strategy = scan["strategy"]
    assert strategy["fail-fast"] is False
    include = strategy["matrix"]["include"]
    assert include == "${{ fromJSON(needs.plan.outputs.matrix) }}"


def test_image_scan_leg_consumes_per_target_artifacts():
    scan = _workflow()["jobs"]["image-scan"]
    vuln_steps = [
        s for s in scan["steps"] if "image-vuln-scan" in str(s.get("uses", ""))
    ]
    assert len(vuln_steps) == 1
    with_map = vuln_steps[0]["with"]
    assert with_map["image-tag"] == "${{ matrix.tag }}"
    assert with_map["image-artifact-name"] == "scan-image-${{ matrix.target }}"
    assert with_map["sbom-artifact-name"] == "sbom-image-${{ matrix.target }}"


def test_exactly_one_designated_source_sbom_leg():
    jobs = _workflow()["jobs"]
    assert "source_sbom_target" in jobs["plan"]["outputs"]
    designated_if = (
        "${{ matrix.target == needs.plan.outputs.source_sbom_target }}"
    )
    scan = jobs["image-scan"]
    source_steps = [
        s
        for s in scan["steps"]
        if "sbom-source" in str(s.get("with", "")) or "source SBOM" in str(s.get("name", ""))
    ]
    assert len(source_steps) == 3, "generate + Trivy + Grype source-SBOM steps"
    for step in source_steps:
        assert step.get("if") == designated_if, (
            f"source-SBOM step '{step.get('name')}' must be guarded by the "
            "designated-leg condition"
        )


def test_containers_bridge_outputs_retired():
    plan_outputs = _workflow()["jobs"]["plan"]["outputs"]
    # health joined the retired set when cluster-smoke was rewired.
    for retired in ("containers", "has_extras", "chart", "health"):
        assert retired not in plan_outputs, f"bridge output '{retired}' must be retired"
    assert "matrix" in plan_outputs
    assert "needs.plan.outputs.containers" not in WORKFLOW.read_text()


# --- plan-time helm dependency build --------------------------------------------


def test_plan_builds_chart_dependencies_before_lint():
    """helm dependency build must run before lint_caller.py so a chart with a
    file://-or-remote dependency and no committed charts/ still lints."""
    plan = _workflow()["jobs"]["plan"]
    steps = plan["steps"]
    dep_build_idx = next(
        i
        for i, s in enumerate(steps)
        if "helm dependency build" in str(s.get("run", ""))
    )
    lint_idx = next(
        i
        for i, s in enumerate(steps)
        if s.get("name") == "Lint caller against v0.6 conventions"
    )
    assert dep_build_idx < lint_idx, (
        "helm dependency build must run before the lint step"
    )
    dep_step = steps[dep_build_idx]
    assert dep_step.get("if") == "${{ inputs.image_only != true }}"


# --- sonar.sources fallback for non-monorepo consumers -------------------------


def test_sonarqube_sources_resolved_dynamically_not_hardcoded():
    """sonar.sources must not hardcode packages/,apps/; a flat repo with
    neither directory would make sonar-scanner exit 2. A preceding step
    resolves sonar.sources dynamically instead."""
    scan = _workflow()["jobs"]["sast-sonarqube"]
    scanner_steps = [
        s
        for s in scan["steps"]
        if "sonarqube-scan-action" in str(s.get("uses", ""))
    ]
    assert len(scanner_steps) == 1
    args = str(scanner_steps[0]["with"]["args"])
    assert "packages/,apps/" not in args, (
        "sonar.sources must not hardcode a monorepo-only literal"
    )
    assert "steps.sonar-sources.outputs.sources" in args

    resolve_steps = [s for s in scan["steps"] if s.get("id") == "sonar-sources"]
    assert len(resolve_steps) == 1, (
        "a step id='sonar-sources' must resolve sonar.sources before the scan step"
    )
    resolve_text = str(resolve_steps[0].get("run", ""))
    assert "packages" in resolve_text and "apps" in resolve_text
    scanner_idx = scan["steps"].index(scanner_steps[0])
    resolve_idx = scan["steps"].index(resolve_steps[0])
    assert resolve_idx < scanner_idx, (
        "sonar.sources must be resolved before the scan step runs"
    )


# --- caller template usable verbatim ---------------------------------------------


def test_caller_template_is_thin_surface_and_lint_clean(tmp_path):
    """The template, with its placeholder gate ref pinned to a SHA, must pass
    the v0.6 caller structure lint verbatim."""
    import importlib.util
    import sys

    lib = ROOT / "scripts/lib"
    sys.path.insert(0, str(lib))
    try:
        spec = importlib.util.spec_from_file_location(
            "lint_caller", lib / "lint_caller.py"
        )
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(str(lib))

    template = (ROOT / "templates/callers/security-gate.yml").read_text()
    pinned = re.sub(
        r"(reusable-security-gate\.yml)@\S+",
        r"\1@" + "0" * 40,
        template,
    )
    caller = tmp_path / "security-gate.yml"
    caller.write_text(pinned)
    verdicts = mod.lint_caller_workflow(caller)
    assert verdicts == [], [v["message"] for v in verdicts]

    with_map = yaml.safe_load(pinned)["jobs"]["security-scan"]["with"]
    assert set(with_map) <= V06_INPUTS
