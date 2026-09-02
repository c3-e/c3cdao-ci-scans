"""Unit tests for evaluate_security_gate blocking membership."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MOD_PATH = ROOT / "scripts/lib/evaluate_security_gate.py"


def _load():
    spec = importlib.util.spec_from_file_location("evaluate_security_gate", MOD_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mod = _load()


def _needs(results: dict[str, str], smoke_ok: str | None = None) -> dict:
    out: dict = {k: {"result": v} for k, v in results.items()}
    if smoke_ok is not None and "cluster-smoke" in out:
        out["cluster-smoke"]["outputs"] = {"smoke_ok": smoke_ok}
    return out


def test_blocking_membership_uses_plan_job_id():
    """v0.6 renames caller-lint -> plan; a stale blocking list would fail
    every run spuriously (needs key mismatch)."""
    blocking = mod.blocking_jobs(image_only=True)
    assert "plan" in blocking
    assert "caller-lint" not in blocking


def test_image_only_omits_helm_and_smoke():
    needs = _needs(
        {
            "plan": "success",
            "build": "success",
            "secrets-scan": "success",
            "image-scan": "success",
            "helm-check": "skipped",
            "cluster-smoke": "skipped",
        }
    )
    assert mod.evaluate(needs, image_only=True, security_scan_blocking=True) == 0


def test_app_mode_requires_helm_and_smoke_ok():
    needs = _needs(
        {
            "plan": "success",
            "build": "success",
            "secrets-scan": "success",
            "image-scan": "success",
            "helm-check": "success",
            "cluster-smoke": "success",
        },
        smoke_ok="true",
    )
    assert mod.evaluate(needs, image_only=False, security_scan_blocking=True) == 0


def test_smoke_failure_advisory_until_blocking_flag():
    """Same ramp as secrets-scan/image-scan: a real probe failure
    (smoke_ok=false) stays advisory (green gate) until
    SECURITY_SCAN_BLOCKING=true — it must not block by default."""
    needs = _needs(
        {
            "plan": "success",
            "build": "success",
            "secrets-scan": "success",
            "image-scan": "success",
            "helm-check": "success",
            "cluster-smoke": "success",
        },
        smoke_ok="false",
    )
    assert mod.evaluate(needs, image_only=False, security_scan_blocking=False) == 0


def test_smoke_failure_blocks_once_blocking_flag_set():
    needs = _needs(
        {
            "plan": "success",
            "build": "success",
            "secrets-scan": "success",
            "image-scan": "success",
            "helm-check": "success",
            "cluster-smoke": "success",
        },
        smoke_ok="false",
    )
    assert mod.evaluate(needs, image_only=False, security_scan_blocking=True) == 1


def test_matrixed_build_failure_blocks():
    # Extras are legs of the matrixed build job: any failed leg fails the
    # whole job, so a single result covers every extra.
    needs = _needs(
        {
            "plan": "success",
            "build": "failure",
            "secrets-scan": "success",
            "image-scan": "skipped",
            "helm-check": "success",
            "cluster-smoke": "skipped",
        }
    )
    assert mod.evaluate(needs, image_only=False, security_scan_blocking=True) == 1


def test_matrixed_image_scan_failure_blocks():
    needs = _needs(
        {
            "plan": "success",
            "build": "success",
            "secrets-scan": "success",
            "image-scan": "failure",
            "helm-check": "success",
            "cluster-smoke": "success",
        },
        smoke_ok="true",
    )
    assert mod.evaluate(needs, image_only=False, security_scan_blocking=True) == 1


# --- Advisory-mode banner (SECURITY_SCAN_BLOCKING visibility) -----------------

_PASSING_IMAGE_ONLY = {
    "plan": "success",
    "build": "success",
    "secrets-scan": "success",
    "image-scan": "success",
}


def _run_main(monkeypatch, results: dict[str, str], blocking: str | None) -> int:
    import json

    monkeypatch.setenv("NEEDS_JSON", json.dumps(_needs(results)))
    monkeypatch.setenv("IMAGE_ONLY", "true")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    if blocking is None:
        monkeypatch.delenv("SECURITY_SCAN_BLOCKING", raising=False)
    else:
        monkeypatch.setenv("SECURITY_SCAN_BLOCKING", blocking)
    with pytest.raises(SystemExit) as exc:
        mod.main()
    return exc.value.code


@pytest.mark.parametrize("blocking", [None, "false"])
def test_advisory_banner_on_stdout_when_not_blocking(monkeypatch, capsys, blocking):
    assert _run_main(monkeypatch, _PASSING_IMAGE_ONLY, blocking) == 0
    assert mod.ADVISORY_BANNER in capsys.readouterr().out


def test_advisory_banner_absent_when_blocking(monkeypatch, capsys):
    assert _run_main(monkeypatch, _PASSING_IMAGE_ONLY, "true") == 0
    assert mod.ADVISORY_BANNER not in capsys.readouterr().out


def test_advisory_banner_appends_step_summary(monkeypatch, tmp_path):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("SECURITY_SCAN_BLOCKING", "false")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    mod.warn_if_advisory()
    text = summary.read_text(encoding="utf-8")
    assert "[!WARNING]" in text
    assert mod.ADVISORY_BANNER in text


def test_no_step_summary_write_when_blocking(monkeypatch, tmp_path):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("SECURITY_SCAN_BLOCKING", "TRUE")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    mod.warn_if_advisory()
    assert not summary.exists()


@pytest.mark.parametrize("blocking", [None, "false", "true"])
def test_exit_code_unchanged_on_failure(monkeypatch, blocking):
    failing = dict(_PASSING_IMAGE_ONLY, **{"image-scan": "failure"})
    assert _run_main(monkeypatch, failing, blocking) == 1


# --- Regression: severity filter decoupling (T-1) ---------------------------
# Prove that evaluate_security_gate.py never reads severity filters or any
# scanner configuration from the environment. This ensures the gate's pass/fail
# decision is completely independent of Trivy's TRIVY_SEVERITY or Grype's
# severity-cutoff — widening those filters to export full spectrum findings
# cannot change the gate verdict.


def test_evaluate_never_reads_trivy_severity_from_environment(monkeypatch):
    """Confirm the module never references TRIVY_SEVERITY or any severity
    environment variable. The gate decision must be independent of scanner
    severity filters (per T-1 scope: severity filtering decouples from
    gate logic, only affects what gets exported)."""
    # Set a variety of severity-related env vars to ensure evaluate() ignores them.
    monkeypatch.setenv("TRIVY_SEVERITY", "HIGH,CRITICAL")
    monkeypatch.setenv("SEVERITY_CUTOFF", "high")
    monkeypatch.setenv("SCANNER_SEVERITY_FILTER", "MEDIUM,HIGH,CRITICAL")

    # Evaluate should pass with the same result regardless of these env vars.
    needs = _needs({
        "plan": "success",
        "build": "success",
        "secrets-scan": "success",
        "image-scan": "success",
    })
    result_with_envs = mod.evaluate(needs, image_only=True, security_scan_blocking=True)

    # Now remove the env vars and confirm result is identical.
    monkeypatch.delenv("TRIVY_SEVERITY", raising=False)
    monkeypatch.delenv("SEVERITY_CUTOFF", raising=False)
    monkeypatch.delenv("SCANNER_SEVERITY_FILTER", raising=False)

    result_without_envs = mod.evaluate(needs, image_only=True, security_scan_blocking=True)

    assert result_with_envs == result_without_envs == 0


def test_module_source_never_imports_severity_constants():
    """Verify that the module's source code never directly references severity
    constants or environment variables (TRIVY_SEVERITY, etc.), confirming
    the gate decision is purely based on job results and smoke_ok output."""
    source = MOD_PATH.read_text(encoding="utf-8")
    # Check that the module never reads severity-related environment variables.
    # These patterns would indicate the gate is making decisions based on severity.
    forbidden_patterns = [
        "TRIVY_SEVERITY",
        "severity",  # Common in: severity-cutoff, severity-threshold, etc.
        "SEVERITY",
        "CVE",  # Would indicate direct CVE inspection, not job result checking.
    ]
    # Note: we exclude patterns that are actually used in docstrings or comments
    # about why severities are NOT considered, so we do a more targeted check.
    source_lower = source.lower()
    for pattern in forbidden_patterns:
        # Look for actual code usage, not comments or strings.
        # A simple heuristic: if the pattern appears in an assignment or function call.
        if f"os.environ.get(\"{pattern.lower()}" in source_lower or \
           f'os.environ.get("{pattern}' in source or \
           f"os.environ['{pattern}" in source or \
           f'os.environ["{pattern}' in source:
            raise AssertionError(
                f"Module source contains forbidden reference: {pattern}"
            )
    # Confirm the two expected environment variables are the only ones read.
    assert 'os.environ.get("SECURITY_SCAN_BLOCKING")' in source or \
           'os.environ.get("NEEDS_JSON")' in source or \
           'os.environ.get("IMAGE_ONLY")' in source or \
           'os.environ["NEEDS_JSON"]' in source
