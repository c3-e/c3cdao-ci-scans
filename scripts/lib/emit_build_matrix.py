# /// script
# requires-python = ">=3.11"
# ///
"""Derive the GitHub Actions build matrix from a published bake plan.

The plan job's derivation step (derive_bom.py) publishes `bake-plan.json`
(untouched `docker buildx bake --print` JSON); this module maps that plan
into the `[{target, tag, dockerfile, context}]` matrix the `build` and
`image-scan` jobs fan out over via `fromJSON(...)`, plus the single
`source_sbom_target` leg. It was previously an inline Python heredoc in
the workflow YAML; that location put it outside `scripts/lib/`'s ruff/mypy
coverage and its own pytest suite. Pure stdlib: no PyYAML dependency, since
its only input is already-parsed JSON.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

__all__ = ["build_matrix", "main"]


def build_matrix(plan: dict[str, Any]) -> tuple[list[dict[str, str]], str]:
    """The build matrix and designated source-SBOM target from a bake plan.

    Sorted by target name for determinism (never empty: compose-no-builds
    lint blocks a zero-target plan before this ever runs). The first
    target in sorted order is the designated source_sbom_target.
    """
    matrix = [
        {
            "target": name,
            "tag": tgt["tags"][0],
            "dockerfile": tgt.get("dockerfile", "Dockerfile"),
            "context": tgt.get("context", "."),
        }
        for name, tgt in sorted(plan["target"].items())
    ]
    return matrix, matrix[0]["target"]


def main(argv: list[str]) -> int:
    usage = "usage: emit_build_matrix.py <bake-plan.json>"
    if len(argv) != 1:
        raise SystemExit(usage)
    plan = json.loads(Path(argv[0]).read_text())
    matrix, source_sbom_target = build_matrix(plan)
    sep = (",", ":")
    matrix_json = json.dumps(matrix, separators=sep)
    print("plan: build matrix:", matrix_json)
    print("plan: source-SBOM leg:", source_sbom_target)
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as out:
            out.write(f"matrix={matrix_json}\n")
            out.write(f"source_sbom_target={source_sbom_target}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
