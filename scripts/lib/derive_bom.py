# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
"""Derive the annotated Image BOM from a Compose file plus bake's plan.

The plan document is `docker buildx bake --print` JSON, untouched — we
define no schema of our own (ADR-02). This module adds the sibling
annotation document: build targets, `excluded[]` (compose services
filtered by `profiles: [local]`, with reasons), `dependencies[]`
(image-only services declaring `x-downloaded-dependency`, each with
digest pin and chart-facing tag), `unmarked[]` (image-only services
lacking the declaration — routed to lint, never scanned), a derived
smoke-target placeholder, and provenance comments. The annotated
document is canonically serialized and hashed for publication.

Pure function of (compose file, target list, override set): bake runs
with a scrubbed environment from the compose file's directory (compose
`context:` resolves against the process cwd — spike Finding A).
"""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

LOCAL_PROFILE = "local"
DEPENDENCY_KEY = "x-downloaded-dependency"
PLATFORM_PIN = "linux/amd64"


def load_compose(path: Path) -> dict[str, Any]:
    """Parse the canonical compose file, failing closed on absence/shape."""
    try:
        doc = yaml.safe_load(path.read_text())
    except OSError as e:
        raise SystemExit(f"error: {path}: {e}") from e
    except yaml.YAMLError as e:
        raise SystemExit(f"error: {path}: unparseable compose file: {e}") from e
    if not isinstance(doc, dict) or not isinstance(doc.get("services"), dict):
        raise SystemExit(f"error: {path}: compose file must map 'services'")
    return doc


def classify_services(compose: dict[str, Any]) -> dict[str, Any]:
    """Split compose services into targets / excluded / dependencies / unmarked.

    Explicit target selection is load-bearing (SPIKE-01): bake ignores
    `profiles:` when given no targets, so the returned target list must be
    passed to every `--print` and execution call.
    """
    targets: list[str] = []
    excluded: list[dict[str, str]] = []
    dependencies: list[dict[str, str]] = []
    unmarked: list[dict[str, str]] = []
    for name, svc in sorted(compose["services"].items()):
        if not isinstance(svc, dict):
            raise SystemExit(f"error: service {name!r}: not a mapping")
        profiles = svc.get("profiles") or []
        if "build" in svc:
            if LOCAL_PROFILE in profiles:
                excluded.append(
                    {"service": name, "reason": f"profiles: [{LOCAL_PROFILE}]"}
                )
            else:
                targets.append(name)
        elif "image" in svc:
            image = str(svc["image"])
            marker = svc.get(DEPENDENCY_KEY)
            digest = image.rpartition("@")[2] if "@" in image else ""
            chart_tag = (
                str(marker.get("chart-tag", "")) if isinstance(marker, dict) else ""
            )
            if marker is not None and digest.startswith("sha256:") and chart_tag:
                dependencies.append(
                    {
                        "service": name,
                        "image": image,
                        "digest": digest,
                        "chart_tag": chart_tag,
                    }
                )
            else:
                unmarked.append(
                    {
                        "service": name,
                        "image": image,
                        "reason": (
                            f"image without build must declare {DEPENDENCY_KEY} "
                            "with a sha256 digest pin and chart-tag"
                        ),
                    }
                )
    return {
        "targets": targets,
        "excluded": excluded,
        "dependencies": dependencies,
        "unmarked": unmarked,
    }


def bake_print_command(
    compose_path: Path, targets: list[str], overrides: list[str] | None = None
) -> list[str]:
    """The exact bake --print invocation, mirroring execution's overrides.

    `overrides` are extra --set values (e.g. the gate's resolved
    `*.args.BUILDER_IMAGE`/`*.args.RUNTIME_IMAGE`); plan/execution parity
    requires the published plan to resolve with the same override set the
    build legs execute with.
    """
    set_args: list[str] = []
    for override in overrides or []:
        set_args += ["--set", override]
    return [
        "docker",
        "buildx",
        "bake",
        "-f",
        compose_path.name,
        "--print",
        "--set",
        f"*.platform={PLATFORM_PIN}",
        *set_args,
        *targets,
    ]


def run_bake_print(
    compose_path: Path, targets: list[str], overrides: list[str] | None = None
) -> dict[str, Any]:
    """Resolve the plan via `bake --print` with a scrubbed environment.

    Runs from the compose file's directory (compose `context:` resolves
    against the process cwd — spike Finding A) with only PATH/HOME kept
    (SPIKE-03 determinism). Resolve failure exits non-zero naming the
    `bake-resolve` rule with bake's stderr attached.
    """
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME")}
    proc = subprocess.run(
        bake_print_command(compose_path, targets, overrides),
        cwd=compose_path.parent,
        env=env,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        print(
            f"error: bake-resolve: bake --print failed on {compose_path} "
            f"(exit {proc.returncode}); bake stderr follows\n{proc.stderr}",
            file=sys.stderr,
        )
        raise SystemExit(1)
    try:
        plan = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        print(
            f"error: bake-resolve: bake --print emitted unparseable JSON "
            f"for {compose_path}: {e}",
            file=sys.stderr,
        )
        raise SystemExit(1) from e
    if not isinstance(plan, dict) or not isinstance(plan.get("target"), dict):
        raise SystemExit(
            f"error: bake-resolve: plan for {compose_path} has no 'target' mapping"
        )
    return plan


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
        # Filled by the smoke-target derivation (T-7) from the rendered
        # chart; a placeholder here so the published shape is stable.
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
                "the rendered chart (T-7); placeholder in this document"
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
