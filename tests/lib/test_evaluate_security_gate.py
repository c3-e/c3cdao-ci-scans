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
    assert mod.evaluate(needs, image_only=True) == 0


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
    assert mod.evaluate(needs, image_only=False) == 0


def test_smoke_continue_on_error_false_green():
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
    assert mod.evaluate(needs, image_only=False) == 1


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
    assert mod.evaluate(needs, image_only=False) == 1


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
    assert mod.evaluate(needs, image_only=False) == 1
