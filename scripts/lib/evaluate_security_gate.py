# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Evaluate Security Gate blocking membership from needs JSON.

Exit 0 when all blocking jobs succeeded (and cluster-smoke smoke_ok when
applicable). Exit 1 otherwise.
"""

from __future__ import annotations

import json
import os
from typing import Any

ADVISORY_BANNER = (
    "⚠ ADVISORY MODE — SECURITY_SCAN_BLOCKING is not 'true': cluster-smoke and "
    "image-scan findings warn instead of failing. A green gate does not certify "
    "vulnerability/smoke posture. "
    "Flip with: gh variable set SECURITY_SCAN_BLOCKING --body true"
)


def warn_if_advisory() -> None:
    """Surface advisory mode loudly; never changes exit-code semantics."""
    if (os.environ.get("SECURITY_SCAN_BLOCKING") or "").lower() == "true":
        return
    print(f"{'=' * 78}\n{ADVISORY_BANNER}\n{'=' * 78}")
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        try:
            with open(summary_path, "a", encoding="utf-8") as fh:
                fh.write(f"> [!WARNING]\n> {ADVISORY_BANNER}\n\n")
        except OSError as e:
            # Cosmetic write only — the stdout banner above already fired;
            # a summary-file failure must not decide the gate verdict.
            print(f"::warning::could not write advisory banner to step summary: {e}")


def blocking_jobs(image_only: bool) -> list[str]:
    # build and image-scan are matrixed (one leg per plan-derived build
    # target): the job fails when any leg fails, so every leg is covered
    # without per-leg job entries. 'plan' is the v0.6 rename of caller-lint.
    blocking = ["plan", "build", "secrets-scan", "image-scan"]
    if not image_only:
        blocking[3:3] = ["helm-check", "cluster-smoke"]
    return blocking


def evaluate(needs: dict[str, Any], image_only: bool) -> int:
    blocking = blocking_jobs(image_only)
    bad = {
        k: needs.get(k, {}).get("result")
        for k in blocking
        if needs.get(k, {}).get("result") != "success"
    }
    if bad:
        print("Blocking jobs not successful:", bad)
        return 1
    if "cluster-smoke" in blocking:
        smoke = needs.get("cluster-smoke") or {}
        smoke_ok = (smoke.get("outputs") or {}).get("smoke_ok")
        if smoke_ok != "true":
            print(
                "Blocking cluster-smoke step failed "
                f"(smoke_ok={smoke_ok!r}, result={smoke.get('result')!r})"
            )
            return 1
    print("All blocking security scans passed.")
    return 0


def main() -> None:
    needs = json.loads(os.environ["NEEDS_JSON"])
    image_only = (os.environ.get("IMAGE_ONLY") or "").lower() == "true"
    warn_if_advisory()
    raise SystemExit(evaluate(needs, image_only))


if __name__ == "__main__":
    main()
