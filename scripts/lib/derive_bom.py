# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
"""Derive the annotated Image BOM from a Compose file plus bake's plan.

The plan document is `docker buildx bake --print` JSON, untouched — the
gate defines no build-plan schema of its own. This module adds the
sibling annotation document: build targets, `excluded[]` (compose
services filtered by `profiles: [local]`, with reasons), `dependencies[]`
(image-only services declaring `x-downloaded-dependency`, each with
digest pin and chart-facing tag), `unmarked[]` (image-only services
lacking the declaration — routed to lint, never scanned), a derived
smoke-target placeholder, and provenance comments. The annotated
document is canonically serialized and hashed for publication.

Compose parsing, service classification, and bake resolution live in the
header-less library `compose_facts` (shared with the lint rules); this
file is the PEP 723 entry point over it.
"""

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from compose_facts import (
    DEPENDENCY_KEY,
    LOCAL_PROFILE,
    PLATFORM_PIN,
    bake_print_command,
    classify_services,
    load_compose,
    run_bake_print,
)

__all__ = [
    "DEPENDENCY_KEY",
    "LOCAL_PROFILE",
    "PLATFORM_PIN",
    "bake_print_command",
    "bom_sha256",
    "canonical_json",
    "classify_services",
    "derive_bom",
    "load_compose",
    "run_bake_print",
]


def canonical_json(doc: dict[str, Any]) -> str:
    """Serialize canonically: sorted keys, fixed separators, ASCII, newline."""
    return (
        json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    )


def bom_sha256(doc: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(doc).encode("ascii")).hexdigest()


def derive_bom(compose_path: Path, plan: dict[str, Any]) -> dict[str, Any]:
    """Build the annotation document for a compose file and its bake plan.

    The plan stays untouched (sibling documents, never merged); the
    annotation records the plan's canonical sha256 so publication binds
    the pair.
    """
    roles = classify_services(load_compose(compose_path))
    planned = sorted(plan.get("target", {}))
    if planned != roles["targets"]:
        raise SystemExit(
            f"error: {compose_path}: plan/derivation target mismatch: "
            f"compose derives {roles['targets']}, plan resolves {planned}"
        )
    return {
        "targets": roles["targets"],
        "excluded": roles["excluded"],
        "dependencies": roles["dependencies"],
        "unmarked": roles["unmarked"],
        # Filled by the smoke-target derivation from the rendered chart;
        # a placeholder here so the published shape is stable.
        "smoke_target": None,
        "plan_sha256": bom_sha256(plan),
        "provenance": {
            "targets": (
                "non-local compose 'build:' services, sorted; passed "
                "explicitly to every bake --print and bake invocation"
            ),
            "excluded": (
                f"compose services filtered by 'profiles: [{LOCAL_PROFILE}]', "
                "with reasons — visible, never silent"
            ),
            "dependencies": (
                f"compose 'image:'-only services declaring {DEPENDENCY_KEY} "
                "with a sha256 digest pin and chart-facing tag; downloaded "
                "runtime dependencies, not scanned release artifacts"
            ),
            "unmarked": (
                "compose 'image:'-only services lacking a conforming "
                f"{DEPENDENCY_KEY} declaration; routed to lint "
                "(dependency-shape), never built or scanned"
            ),
            "smoke_target": (
                "single Service-backed HTTP readiness target derived from "
                "the rendered chart; placeholder in this document"
            ),
            "plan_sha256": (
                "sha256 of the canonically serialized bake --print plan "
                "published alongside this annotation document"
            ),
        },
    }


def main(argv: list[str]) -> int:
    """Derive and write the sibling documents: bake plan + annotated BOM."""
    usage = "usage: derive_bom.py <compose-file> [--out-dir DIR] [--set KEY=VAL ...]"
    args = list(argv)
    out_dir = Path(".")
    if "--out-dir" in args:
        i = args.index("--out-dir")
        try:
            out_dir = Path(args[i + 1])
        except IndexError:
            raise SystemExit(usage)
        del args[i : i + 2]
    overrides: list[str] = []
    while "--set" in args:
        i = args.index("--set")
        try:
            overrides.append(args[i + 1])
        except IndexError:
            raise SystemExit(usage)
        del args[i : i + 2]
    if len(args) != 1:
        raise SystemExit(usage)
    compose_path = Path(args[0])
    roles = classify_services(load_compose(compose_path))
    plan = run_bake_print(compose_path, roles["targets"], overrides)
    bom = derive_bom(compose_path, plan)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "bake-plan.json").write_text(canonical_json(plan))
    (out_dir / "bom.json").write_text(canonical_json(bom))
    print(f"bom sha256: {bom_sha256(bom)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
