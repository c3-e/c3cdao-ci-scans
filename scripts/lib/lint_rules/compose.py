"""Compose-file convention rules: presence/shape, per-service conventions,
explicit build inputs, and bake plan resolution.

Rule ids here: compose-missing, compose-no-builds, matrix-cap,
compose-image-tag, compose-healthcheck, compose-platform, dependency-shape,
build-input-explicit, build-context-excludes, bake-resolve.
"""

from __future__ import annotations

import contextlib
import io
from pathlib import Path
from typing import Any

from compose_facts import PLATFORM_PIN, load_compose, run_bake_print
from lint_rules import Verdict, verdict

MATRIX_CAP = 10
_SECRET_LIKE_FRAGMENTS = ("TOKEN", "SECRET", "PASSW", "CREDENTIAL")
REQUIRED_DOCKERIGNORE = (".env", "*.pem", "*.key", "*credentials*")


# --- presence / shape -----------------------------------------------------------


def compose_missing(compose_path: Path) -> list[Verdict]:
    """The canonical compose file must exist and parse to a services mapping."""
    try:
        load_compose(compose_path)
    except SystemExit as e:
        return [verdict("compose-missing", str(e.code))]
    return []


def compose_no_builds(classified: dict[str, Any]) -> list[Verdict]:
    """At least one non-local `build:` service must exist (image_only too)."""
    if classified["targets"]:
        return []
    return [
        verdict(
            "compose-no-builds",
            "compose file declares zero non-local 'build:' services; "
            "the fork must build at least one image",
        )
    ]


def matrix_cap(classified: dict[str, Any]) -> list[Verdict]:
    """More than ten non-local build services exceeds the supported matrix."""
    count = len(classified["targets"])
    if count <= MATRIX_CAP:
        return []
    return [
        verdict(
            "matrix-cap",
            f"{count} non-local 'build:' services exceed the supported "
            f"maximum of {MATRIX_CAP}",
        )
    ]


# --- per-service conventions ------------------------------------------------------


def _target_services(
    compose: dict[str, Any], classified: dict[str, Any]
) -> list[tuple[str, dict[str, Any]]]:
    return [(name, compose["services"][name]) for name in classified["targets"]]


def compose_image_tag(
    compose: dict[str, Any], classified: dict[str, Any]
) -> list[Verdict]:
    """Every non-local build service declares an explicit `image:` tag.

    `:latest` and untagged are indistinguishable after bake's normalization.
    An interpolated tag (`image: app:${TAG}`) blocks first: the gate runs
    bake with a scrubbed environment, so `${TAG}` would resolve empty.
    """
    verdicts = []
    for name, svc in _target_services(compose, classified):
        image = svc.get("image")
        if _interpolated(image):
            verdicts.append(
                verdict(
                    "compose-image-tag",
                    f"build service '{name}' interpolates its image reference "
                    f"(image: {image!r}); the gate builds with a scrubbed "
                    "environment, so the variable resolves empty; pin a "
                    "committed literal tag",
                )
            )
            continue
        tag = ""
        if isinstance(image, str):
            tag = image.rpartition("@")[0] or image
            tag = tag.rpartition("/")[2].partition(":")[2]
        if not tag or tag == "latest":
            verdicts.append(
                verdict(
                    "compose-image-tag",
                    f"build service '{name}' lacks an explicit image tag "
                    f"(image: {image!r}); ':latest' and untagged references "
                    "are not explicit",
                )
            )
    return verdicts


def compose_healthcheck(
    compose: dict[str, Any], classified: dict[str, Any]
) -> list[Verdict]:
    """Every non-local build service declares a `healthcheck:` (HTTP/TCP/exec)."""
    verdicts = []
    for name, svc in _target_services(compose, classified):
        healthcheck = svc.get("healthcheck")
        if not isinstance(healthcheck, dict) or not healthcheck.get("test"):
            verdicts.append(
                verdict(
                    "compose-healthcheck",
                    f"build service '{name}' lacks a healthcheck with a "
                    "'test' command (HTTP, TCP, or exec)",
                )
            )
    return verdicts


def compose_platform(compose: dict[str, Any]) -> list[Verdict]:
    """No service or build may declare a platform other than linux/amd64.

    Platform selection is gate-owned (pinned via --set on every build); a
    committed non-amd64 platform is rejected rather than silently overridden.
    """
    verdicts = []
    for name, svc in sorted(compose["services"].items()):
        if not isinstance(svc, dict):
            continue
        declared: list[Any] = []
        if "platform" in svc:
            declared.append(svc["platform"])
        build = svc.get("build")
        if isinstance(build, dict):
            declared.extend(build.get("platforms") or [])
        for platform in declared:
            if str(platform) != PLATFORM_PIN:
                verdicts.append(
                    verdict(
                        "compose-platform",
                        f"service '{name}' declares platform '{platform}'; "
                        f"v0.6 builds {PLATFORM_PIN} only",
                    )
                )
    return verdicts


def dependency_shape(classified: dict[str, Any]) -> list[Verdict]:
    """Image-only services must be conforming downloaded-dependency declarations.

    The derivation routes nonconforming entries to `unmarked[]` (missing
    x-downloaded-dependency, digest pin, or chart-tag); each is a block.
    """
    return [
        verdict(
            "dependency-shape",
            f"service '{entry['service']}' (image: {entry['image']}): "
            f"{entry['reason']}",
        )
        for entry in classified["unmarked"]
    ]


# --- explicit build inputs --------------------------------------------------------


def _secret_like(arg_name: str) -> bool:
    upper = arg_name.upper()
    return (
        any(fragment in upper for fragment in _SECRET_LIKE_FRAGMENTS)
        or upper.endswith("_KEY")
        or upper == "KEY"
    )


def _interpolated(value: Any) -> bool:
    """Compose-file environment interpolation (`$VAR` / `${VAR}`).

    A literal dollar is escaped as `$$` in Compose, so any single `$`
    marks an environment-dependent field.
    """
    return isinstance(value, str) and "$" in value.replace("$$", "")


def build_input_explicit(
    compose: dict[str, Any], classified: dict[str, Any]
) -> list[Verdict]:
    """Build inputs are committed literals; nothing flows in from the host.

    The gate supplies no arg values of its own; the only execution-time
    override is the platform pin.
    """

    def block(name: str, detail: str) -> Verdict:
        return verdict("build-input-explicit", f"build service '{name}': {detail}")

    verdicts = []
    for name, svc in _target_services(compose, classified):
        build = svc.get("build")
        if not isinstance(build, dict):
            if _interpolated(build):
                verdicts.append(block(name, f"build '{build}' is interpolated"))
            continue
        for key in ("secrets", "ssh"):
            if key in build:
                verdicts.append(
                    block(name, f"'build.{key}' is not permitted in CI builds")
                )
        for field, value in build.items():
            if field != "args" and _interpolated(value):
                verdicts.append(
                    block(
                        name,
                        f"build field '{field}' interpolates the environment "
                        f"({value!r})",
                    )
                )
        args = build.get("args")
        if args is None:
            continue
        if not isinstance(args, dict):
            verdicts.append(
                block(
                    name,
                    "'build.args' must be a mapping of committed literal "
                    "values (list syntax forwards host values)",
                )
            )
            continue
        for arg, value in args.items():
            if value is None:
                verdicts.append(block(name, f"arg '{arg}' is a null pass-through"))
            elif _interpolated(value):
                verdicts.append(
                    block(
                        name,
                        f"arg '{arg}' interpolates the environment ({value!r})",
                    )
                )
            if _secret_like(str(arg)):
                verdicts.append(block(name, f"arg '{arg}' has a secret-like name"))
    return verdicts


def _build_contexts(
    compose_path: Path, compose: dict[str, Any], classified: dict[str, Any]
) -> dict[Path, list[str]]:
    """Build-context directories (resolved against the compose file's dir)."""
    contexts: dict[Path, list[str]] = {}
    for name, svc in _target_services(compose, classified):
        build = svc.get("build")
        context = build.get("context", ".") if isinstance(build, dict) else "."
        resolved = (compose_path.parent / str(context)).resolve()
        contexts.setdefault(resolved, []).append(name)
    return contexts


def build_context_excludes(
    compose_path: Path, compose: dict[str, Any], classified: dict[str, Any]
) -> list[Verdict]:
    """Every build context excludes env/credential/private-key material.

    Each context directory needs a `.dockerignore` carrying every entry in
    REQUIRED_DOCKERIGNORE, so `.env` files and key material can never enter
    an image build.
    """
    verdicts = []
    for context, services in sorted(
        _build_contexts(compose_path, compose, classified).items()
    ):
        dockerignore = context / ".dockerignore"
        try:
            lines = {
                line.strip()
                for line in dockerignore.read_text().splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            }
        except OSError:
            verdicts.append(
                verdict(
                    "build-context-excludes",
                    f"build context '{context}' (services {services}) has no "
                    ".dockerignore; required exclusions: "
                    + ", ".join(REQUIRED_DOCKERIGNORE),
                )
            )
            continue
        missing = [e for e in REQUIRED_DOCKERIGNORE if e not in lines]
        if missing:
            verdicts.append(
                verdict(
                    "build-context-excludes",
                    f"{dockerignore} (services {services}) is missing required "
                    "exclusions: " + ", ".join(missing),
                )
            )
    return verdicts


# --- bake resolve -----------------------------------------------------------------


def bake_resolve(
    compose_path: Path, targets: list[str]
) -> tuple[dict[str, Any] | None, list[Verdict]]:
    """Resolve the bake plan, converting a resolve failure into a verdict.

    Reuses the derivation's `run_bake_print` unchanged (same command, cwd,
    scrubbed environment); its fail-closed stderr (which already names
    this rule and attaches bake's stderr) becomes the verdict message.
    """
    stderr = io.StringIO()
    try:
        with contextlib.redirect_stderr(stderr):
            plan = run_bake_print(compose_path, targets)
    except SystemExit as e:
        message = stderr.getvalue().strip() or str(e.code)
        return None, [verdict("bake-resolve", message)]
    return plan, []
