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
    raise SystemExit(evaluate(needs, image_only))


if __name__ == "__main__":
    main()
