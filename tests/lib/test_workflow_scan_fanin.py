"""Contract tests for the v0.6 scan matrix, caller surface, and fan-in.

Static drift guards on .github/workflows/reusable-security-gate.yml and
templates/callers/security-gate.yml: the workflow_call surface is exactly
the 7 v0.6 inputs + 4 secrets, image-scan fans out over the plan matrix
consuming per-leg artifacts with one designated source-SBOM leg, and the
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
    "image_only",
    "namespace",
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


def test_workflow_call_inputs_are_exactly_the_v06_seven():
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
    # `security-scan / Security Gate` — renaming it un-gates merges.
    assert "security-scan" in caller["jobs"]


# --- image-scan per-leg wiring (AC-1) -----------------------------------------


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


# --- caller template usable verbatim (AC-4) -----------------------------------


def test_caller_template_is_thin_surface_and_lint_clean(tmp_path):
    """The template (with only the placeholder gate ref pinned to a SHA —
    a repo-specific value per AC-4) must pass the v0.6 caller structure
    lint: known inputs only, four secrets mapped, no removed v0.5 inputs."""
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
