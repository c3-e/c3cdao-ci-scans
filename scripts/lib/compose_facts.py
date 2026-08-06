"""Compose-file facts shared by the BOM derivation and the lint rules.

Header-less library module (no PEP 723 block): entry-point scripts import
from here, never the other way around, so uv script-header dependencies
cannot drift apart from importers. Owns the canonical compose parse, the
service classification (targets / excluded / dependencies / unmarked),
and the `docker buildx bake --print` resolution.
"""

from __future__ import annotations

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

    Explicit target selection is load-bearing: bake ignores `profiles:`
    when given no targets, so the returned target list must be passed to
    every `--print` and execution call.
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

    `overrides` are extra --set values (e.g. the gate's
    `*.platform=linux/amd64` pin); plan/execution parity
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
    against the process cwd) with only PATH/HOME kept, so interpolation
    from ambient environment variables cannot make two plans differ.
    Resolve failure exits non-zero naming the `bake-resolve` rule with
    bake's stderr attached.
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
