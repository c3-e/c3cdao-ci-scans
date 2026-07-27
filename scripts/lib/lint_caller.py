# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
"""Lint a consumer caller workflow against the published gate contract.

Usage:
    lint_caller.py <caller.yml> --contract <schema.json> [--consumer-root <path>]
    lint_caller.py --emit-manifest

``--emit-manifest`` prints a single-line JSON object built from the consumer's
``make ci-manifest`` output (passed via the GATE_CI_MANIFEST env var) and the
gate's resolved scan_image input (GATE_SCAN_IMAGE):

    {"containers": [{name, role, image}, ...], "chart": {...}, "health": {...}}

containers[0] is always the primary (tagged scan_image); the rest are extras
(manifest images[1:], tagged by their optional ``image`` key or <name>:local).
The gate's caller-lint job pipes the three sections into GITHUB_OUTPUT; the
build and image-scan jobs matrix over ``containers`` and helm-check /
cluster-smoke fromJSON() ``chart`` / ``health``.

Exit 0 when clean; exit 1 with one line per violation on stdout:
    <rule-id>: <offending key/detail>

Rules skipped for a stated reason print to stderr as
``notice: skip: <rule-id>: <reason>``; file-touching rules announce an active
run as ``notice: active: <rule-id>: checked <path>``.

Rule ids: gate-job-id, no-secrets-inherit, no-caller-concurrency, uses-ref,
unknown-input,
type-mismatch, missing-secret-map, unreadable-caller, smoke-secrets-json,
smoke-secrets-name, smoke-secrets-duplicate, smoke-secrets-literals,
ci-contract-file, ci-contract-target, ci-contract-manifest,
image-values-mismatch, extras-values-mismatch.

The consumer build contract is the only build path, so contract validation is
BLOCKING: a missing contract file, a missing required make target
(ci-manifest / ci-build / ci-smoke-env), or a ci-manifest that fails to run,
parse, or match the required shape is a lint violation. ci-secctx is the one
optional target (the gate's bundled restricted-PSS assertion is the floor) —
its absence is a stderr notice. The image-values rule reads the values-local
path from the manifest's chart.values_local and requires scan_image to be
pinned there (skipped when image_only or when the manifest is unavailable).
The extras-values rule applies the same pin check to every manifest extra
(images[1:]), tagged by its optional ``image`` key or <name>:local — a
mismatched extra is ErrImageNeverPull at smoke time.
An unreadable caller (missing/unparseable file, or no job whose ``uses:``
matches the reusable gate workflow) fails closed.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from extract_contract import load_gha_workflow

GATE_WORKFLOW_BASENAME = "reusable-security-gate.yml"
REQUIRED_SECRETS = (
    "CGR_PULL_TOKEN",
    "CGR_PULL_USERNAME",
    "IRONBANK_TOKEN",
    "IRONBANK_USERNAME",
)


def notice(kind: str, rule: str, detail: str) -> None:
    print(f"notice: {kind}: {rule}: {detail}", file=sys.stderr)


def is_expression(value: Any) -> bool:
    """A GitHub Actions expression value — its literal type is unknowable."""
    return isinstance(value, str) and "${{" in value


def yaml_json_type(value: Any) -> str:
    """JSON Schema type name of a parsed YAML scalar (bool before int!)."""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if value is None:
        return "null"
    return type(value).__name__


def load_contract(path: Path) -> dict[str, Any]:
    """Return the contract schema's properties mapping, or exit naming why."""
    try:
        schema = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise SystemExit(f"error: {path}: {e}") from e
    props = schema.get("properties") if isinstance(schema, dict) else None
    if not isinstance(props, dict) or not props:
        raise SystemExit(f"error: {path}: contract has no properties mapping")
    return props


def find_gate_job(jobs: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    for job_id, job in jobs.items():
        if isinstance(job, dict) and GATE_WORKFLOW_BASENAME in str(
            job.get("uses") or ""
        ):
            return job_id, job
    return None


_USES_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
_RELEASE_TAG_RE = re.compile(r"^v\d")


def check_uses_ref(gate_id: str, uses: str) -> list[str]:
    """The gate job's ``uses:`` must carry a pinned @ref (BLOCKING when not).

    Simple heuristic: the ref must be non-empty, match _USES_REF_RE, and look
    like a real ref, not a placeholder (``vX.Y.Z`` / ``EDIT-ME`` / ``<...>``
    — flagged via the placeholder chars ``<``, ``>``, ``X`` and the literal
    ``EDIT-ME``). Any non-release ref (``main`` or a branch) is
    pilot-window-only: a stderr notice, never a violation.
    """
    rule = "uses-ref"
    _, sep, ref = uses.rpartition("@")
    if not sep or not ref:
        return [
            (
                f"{rule}: gate job '{gate_id}' uses: has no @ref — "
                "pin a release tag (vX.Y.Z)"
            )
        ]
    if (
        not _USES_REF_RE.match(ref)
        or any(c in ref for c in "<>X")
        or "EDIT-ME" in ref.upper()
    ):
        return [
            (
                f"{rule}: gate job '{gate_id}' uses: ref '{ref}' looks like a "
                "placeholder — pin a real release tag (vX.Y.Z)"
            )
        ]
    if not _RELEASE_TAG_RE.match(ref):
        notice(
            "warn",
            rule,
            f"@{ref} is not a release tag — branch refs are pilot-window "
            "only; pin a release tag (vX.Y.Z) before promoting to trunk",
        )
    return []


def contract_value(with_map: dict[str, Any], props: dict[str, Any], key: str) -> Any:
    """Caller-provided value for ``key``, falling back to the contract default."""
    if key in with_map:
        return with_map[key]
    return (props.get(key) or {}).get("default")


def _image_mapping_pins(mapping: dict[str, Any], scan_image: str) -> bool:
    """True when a Helm-style image map joins to ``scan_image``."""
    repo = mapping.get("repository")
    tag = mapping.get("tag")
    if not isinstance(repo, str) or tag is None or isinstance(tag, (dict, list)):
        return False
    return f"{repo}:{tag}" == scan_image


def values_pin_scan_image(node: Any, scan_image: str) -> bool:
    """True if parsed values pin ``scan_image`` via ``image`` string or map.

    Accepts ``image: repo:tag`` strings and ``image: {repository, tag}`` maps
    (including nested ``*.image``). Comments are invisible to the YAML parse.
    """
    if isinstance(node, dict):
        image = node.get("image")
        if isinstance(image, str) and image == scan_image:
            return True
        if isinstance(image, dict) and _image_mapping_pins(image, scan_image):
            return True
        return any(values_pin_scan_image(v, scan_image) for v in node.values())
    if isinstance(node, list):
        return any(values_pin_scan_image(v, scan_image) for v in node)
    return False


def check_image_values(
    with_map: dict[str, Any],
    props: dict[str, Any],
    consumer_root: Path | None,
    manifest: dict[str, Any] | None,
) -> list[str]:
    """scan_image must be pinned in the manifest's chart.values_local YAML."""
    rule = "image-values-mismatch"
    image_only = contract_value(with_map, props, "image_only")
    if image_only is True:
        notice("skip", rule, "image_only is true")
        return []
    if consumer_root is None:
        notice("skip", rule, "--consumer-root not given")
        return []
    if manifest is None:
        notice("skip", rule, "manifest unavailable (see ci-contract violations)")
        return []
    scan_image = contract_value(with_map, props, "scan_image")
    if is_expression(scan_image):
        notice("skip", rule, "scan_image is an expression")
        return []
    values_file = (manifest.get("chart") or {}).get("values_local")
    values_path = consumer_root / str(values_file)
    try:
        text = values_path.read_text()
    except OSError as e:
        return [
            f"{rule}: manifest chart.values_local '{values_file}' unreadable "
            f"under consumer root '{consumer_root}': {e}"
        ]
    notice("active", rule, f"checked {values_path}")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        return [f"{rule}: values file '{values_path}' is not valid YAML: {e}"]
    if values_pin_scan_image(data, str(scan_image)):
        return []
    return [f"{rule}: scan_image '{scan_image}' not found in {values_path}"]


def check_extras_values(
    with_map: dict[str, Any],
    props: dict[str, Any],
    consumer_root: Path | None,
    manifest: dict[str, Any] | None,
) -> list[str]:
    """Each manifest extra's tag must be pinned in chart.values_local YAML.

    Extras (images[1:]) are tagged exactly as manifest_containers() tags them:
    the entry's optional ``image`` key or <name>:local. An unpinned extra is
    ErrImageNeverPull at smoke time.
    """
    rule = "extras-values-mismatch"
    image_only = contract_value(with_map, props, "image_only")
    if image_only is True:
        notice("skip", rule, "image_only is true")
        return []
    if consumer_root is None:
        notice("skip", rule, "--consumer-root not given")
        return []
    if manifest is None:
        notice("skip", rule, "manifest unavailable (see ci-contract violations)")
        return []
    extras = manifest["images"][1:]
    if not extras:
        return []
    values_file = (manifest.get("chart") or {}).get("values_local")
    values_path = consumer_root / str(values_file)
    try:
        data = yaml.safe_load(values_path.read_text())
    except (OSError, yaml.YAMLError):
        # image-values-mismatch already reports the unreadable/invalid file.
        return []
    notice("active", rule, f"checked {values_path}")
    violations: list[str] = []
    for entry in extras:
        name = entry["name"]
        tag = str(entry.get("image") or f"{name}:local")
        if not values_pin_scan_image(data, tag):
            violations.append(
                f"{rule}: extra '{name}' tag '{tag}' not found in {values_path}"
            )
    return violations


_SMOKE_SECRET_ALLOWED_KEYS = {"name", "literals"}
_SMOKE_SECRET_NAME_RE = re.compile(r"^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$")
_SMOKE_LITERAL_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def check_smoke_secrets(with_map: dict[str, Any]) -> list[str]:
    """Validate the caller's smoke_secrets value (a JSON-array string).

    cluster-smoke creates each entry as a Kubernetes Secret before helm install.
    literals is a newline-joined KEY=VALUE string. Absent / empty / [] = no rules.
    """
    if "smoke_secrets" not in with_map:
        return []
    raw = with_map["smoke_secrets"]
    if is_expression(raw):
        return [
            "smoke-secrets-json: smoke_secrets must be a literal JSON-array "
            "string (expressions are not lintable; expand to a static JSON array "
            "or use a multiline '|' block)"
        ]
    if not isinstance(raw, str):
        return [
            "smoke-secrets-json: smoke_secrets must be a JSON-array string, "
            f"got {yaml_json_type(raw)}"
        ]
    text_val = raw.strip()
    if text_val in ("", "[]"):
        return []
    try:
        entries = json.loads(text_val)
    except json.JSONDecodeError as e:
        return [f"smoke-secrets-json: smoke_secrets is not valid JSON: {e}"]
    if not isinstance(entries, list):
        return [
            "smoke-secrets-json: smoke_secrets must be a JSON array, "
            f"got {yaml_json_type(entries)}"
        ]
    # Style only (stderr notice, not a violation): a single-line quoted JSON
    # array is valid but hard to review once there is more than one entry.
    if entries and "\n" not in text_val:
        notice(
            "style",
            "smoke-secrets-format",
            "prefer a multiline YAML '|' block (one object per entry); "
            "single-line quoted JSON does not scale — see docs/INPUTS.md",
        )

    violations: list[str] = []
    seen: set[str] = set()
    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            violations.append(f"smoke-secrets-json: entry {idx} is not an object")
            continue
        name = entry.get("name")
        where = f"'{name}'" if isinstance(name, str) and name else f"entry {idx}"

        unknown = set(entry) - _SMOKE_SECRET_ALLOWED_KEYS
        if unknown:
            violations.append(
                f"smoke-secrets-json: {where}: unknown key(s) {sorted(unknown)}"
            )

        if not isinstance(name, str) or not _SMOKE_SECRET_NAME_RE.match(name):
            violations.append(
                f"smoke-secrets-name: {where}: name must be a DNS-1123 label "
                "(lowercase alphanumeric and '-', max 63 chars)"
            )
        elif name in seen:
            violations.append(f"smoke-secrets-duplicate: duplicate name '{name}'")
        else:
            seen.add(name)

        literals = entry.get("literals")
        if not isinstance(literals, str) or not literals.strip():
            violations.append(
                f"smoke-secrets-literals: {where}: literals must be a non-empty "
                "newline-joined KEY=VALUE string"
            )
        else:
            for line in literals.splitlines():
                if line.strip() and not _SMOKE_LITERAL_RE.match(line):
                    violations.append(
                        f"smoke-secrets-literals: {where}: literals line "
                        f"'{line}' must match ^[A-Za-z_][A-Za-z0-9_]*="
                    )
    return violations


# --- consumer build contract (BLOCKING) --------------------------------------
# The contract is the only build path: a broken contract file is a lint
# violation (exit 1), not a warning. Rule ids: ci-contract-file
# (missing/unreadable contract file), ci-contract-target (a required make
# target is absent), ci-contract-manifest (ci-manifest fails to run, parse,
# or match the required shape). ci-secctx is the one optional target — the
# gate's bundled restricted-PSS assertion is the in-gate floor — so its
# absence is a stderr notice, never a violation.

_CI_CONTRACT_REQUIRED_TARGETS = ("ci-manifest", "ci-build", "ci-smoke-env")
_CI_CONTRACT_OPTIONAL_TARGETS = ("ci-secctx",)
_CI_MANIFEST_REQUIRED: dict[str, tuple[str, ...]] = {
    "chart": ("path", "values", "values_local", "release", "namespace"),
    "health": ("path", "port", "workload_match"),
}
_CI_MANIFEST_IMAGE_REQUIRED = ("name", "dockerfile", "context")


def _make_target_missing(contract_path: Path, target: str, cwd: Path) -> str | None:
    """Return a detail string when ``make -n`` can't resolve ``target``."""
    try:
        proc = subprocess.run(
            ["make", "-n", "-f", str(contract_path), target],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"make -n {target}: {e}"
    if proc.returncode == 0:
        return None
    return f"make -n {target} failed (rc={proc.returncode}): {proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else 'no stderr'}"


def check_ci_manifest_shape(manifest: Any) -> list[str]:
    """Return problem details for a ci-manifest document off the required shape.

    Required: images[] non-empty, each entry an object with non-empty string
    name/dockerfile/context; chart{} with path/values/values_local/release/
    namespace; health{} with path/port/workload_match.
    """
    problems: list[str] = []
    if not isinstance(manifest, dict):
        return [f"manifest must be a JSON object, got {yaml_json_type(manifest)}"]
    images = manifest.get("images")
    if not isinstance(images, list) or not images:
        problems.append("'images' must be a non-empty array")
    else:
        for idx, entry in enumerate(images):
            if not isinstance(entry, dict):
                problems.append(f"images[{idx}] is not an object")
                continue
            for key in _CI_MANIFEST_IMAGE_REQUIRED:
                if not isinstance(entry.get(key), str) or not entry[key]:
                    problems.append(f"images[{idx}] missing '{key}'")
    for section, keys in _CI_MANIFEST_REQUIRED.items():
        node = manifest.get(section)
        if not isinstance(node, dict):
            problems.append(f"'{section}' must be an object")
            continue
        missing = [k for k in keys if k not in node]
        if missing:
            problems.append(f"'{section}' missing key(s) {missing}")
    return problems


def check_ci_contract(
    with_map: dict[str, Any],
    props: dict[str, Any],
    consumer_root: Path | None,
) -> tuple[list[str], dict[str, Any] | None]:
    """Blocking contract-file validation.

    Returns (violations, manifest) — manifest is the parsed ci-manifest dict
    when it ran, parsed, and matched the required shape; None otherwise.
    """
    contract_file = contract_value(with_map, props, "contract_file")
    if is_expression(contract_file):
        notice("skip", "ci-contract-file", "contract_file is an expression")
        return [], None
    if consumer_root is None:
        notice("skip", "ci-contract-file", "--consumer-root not given")
        return [], None
    contract_path = (consumer_root / str(contract_file)).resolve()
    if not contract_path.is_file():
        return [
            f"ci-contract-file: contract file '{contract_file}' not found under "
            f"consumer root '{consumer_root}' — the consumer build contract is "
            "required (start from templates/consumer/Makefile.ci)"
        ], None
    notice("active", "ci-contract-file", f"checked {contract_path}")
    violations: list[str] = []
    for target in _CI_CONTRACT_REQUIRED_TARGETS:
        detail = _make_target_missing(contract_path, target, consumer_root)
        if detail is not None:
            violations.append(f"ci-contract-target: {contract_file}: {detail}")
    for target in _CI_CONTRACT_OPTIONAL_TARGETS:
        detail = _make_target_missing(contract_path, target, consumer_root)
        if detail is not None:
            notice(
                "skip",
                "ci-contract-target",
                f"{contract_file}: optional target '{target}' absent — the "
                "gate's bundled restricted-PSS assertion is the coverage",
            )
    try:
        proc = subprocess.run(
            ["make", "-s", "-f", str(contract_path), "ci-manifest"],
            cwd=consumer_root,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        violations.append(f"ci-contract-manifest: {contract_file}: ci-manifest: {e}")
        return violations, None
    if proc.returncode != 0:
        violations.append(
            f"ci-contract-manifest: {contract_file}: ci-manifest exited "
            f"{proc.returncode}"
        )
        return violations, None
    try:
        manifest = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        violations.append(
            f"ci-contract-manifest: {contract_file}: ci-manifest output is not "
            f"valid JSON: {e}"
        )
        return violations, None
    shape_problems = check_ci_manifest_shape(manifest)
    for problem in shape_problems:
        violations.append(f"ci-contract-manifest: {contract_file}: {problem}")
    if shape_problems:
        return violations, None
    return violations, manifest


# --- normalized manifest (--emit-manifest) -----------------------------------
# Consumed by the gate workflow: caller-lint emits {containers, chart, health};
# the matrixed build and image-scan jobs fromJSON() containers, helm-check and
# cluster-smoke fromJSON() chart/health. Container entry schema:
#   {name, role: "primary"|"extra", image}
# The list always has >=1 entry (images[0] = the primary, tagged with the
# gate's scan_image input), so the jobs' matrices can never be empty.


def manifest_containers(
    manifest: dict[str, Any], scan_image: str
) -> list[dict[str, str]]:
    """Normalized containers list from a validated ci-manifest document.

    images[0] is the primary (always tagged with the gate's scan_image input;
    a manifest ``image`` key on the primary is ignored), images[1:] are the
    extras, tagged by their optional ``image`` key or <name>:local when absent.
    """
    containers: list[dict[str, str]] = []
    for idx, entry in enumerate(manifest["images"]):
        name = entry["name"]
        primary = idx == 0
        containers.append(
            {
                "name": name,
                "role": "primary" if primary else "extra",
                "image": (
                    scan_image
                    if primary
                    else str(entry.get("image") or f"{name}:local")
                ),
            }
        )
    return containers


def emit_manifest() -> int:
    """Print the normalized manifest (single-line JSON object) from env.

    Fails closed (SystemExit) on an unusable manifest — the blocking lint has
    already validated the caller-side shape by the time the gate calls this,
    so a failure here means the contract output changed between steps.
    """
    raw = os.environ.get("GATE_CI_MANIFEST", "")
    scan_image = os.environ.get("GATE_SCAN_IMAGE", "")
    try:
        manifest = json.loads(raw)
    except json.JSONDecodeError as e:
        raise SystemExit(f"error: ci-manifest output is not valid JSON: {e}") from e
    problems = check_ci_manifest_shape(manifest)
    if problems:
        for problem in problems:
            print(f"error: ci-manifest: {problem}", file=sys.stderr)
        raise SystemExit("error: ci-manifest output is off the required shape")
    doc = {
        "containers": manifest_containers(manifest, scan_image),
        "chart": manifest["chart"],
        "health": manifest["health"],
    }
    print(json.dumps(doc, separators=(",", ":")))
    return 0


def lint(
    caller_path: Path, props: dict[str, Any], consumer_root: Path | None
) -> list[str]:
    try:
        wf = load_gha_workflow(caller_path)
    except SystemExit as e:
        return [f"unreadable-caller: {e.code}"]

    jobs = wf.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        return [f"unreadable-caller: {caller_path}: no jobs mapping"]
    gate = find_gate_job(jobs)
    if gate is None:
        return [
            f"unreadable-caller: {caller_path}: no job whose 'uses:' matches "
            f"{GATE_WORKFLOW_BASENAME}"
        ]
    gate_id, gate_job = gate

    violations: list[str] = []

    if gate_id != "security-scan":
        violations.append(
            f"gate-job-id: gate job id is '{gate_id}', must be 'security-scan' — "
            "the job id is half of the required check context "
            "'security-scan / Security Gate'; a different id reports under a "
            "different context and the ruleset no longer matches"
        )

    violations.extend(check_uses_ref(gate_id, str(gate_job.get("uses") or "")))

    for job_id, job in jobs.items():
        if isinstance(job, dict) and job.get("secrets") == "inherit":
            violations.append(
                f"no-secrets-inherit: job '{job_id}' uses 'secrets: inherit' — "
                "map the four gate secrets explicitly"
            )

    if "concurrency" in wf:
        violations.append(
            "no-caller-concurrency: caller has a top-level 'concurrency:' key — "
            "the reusable workflow owns concurrency"
        )

    with_map = gate_job.get("with")
    if not isinstance(with_map, dict):
        with_map = {}
    for key, value in with_map.items():
        if key not in props:
            violations.append(
                f"unknown-input: with: key '{key}' not in contract properties"
            )
            continue
        if is_expression(value):
            notice("skip", "type-mismatch", f"{key} is an expression")
            continue
        expected = (props[key] or {}).get("type", "string")
        actual = yaml_json_type(value)
        if actual != expected:
            violations.append(
                f"type-mismatch: with: key '{key}' expects {expected}, "
                f"got {actual} ({value!r})"
            )

    if gate_job.get("secrets") != "inherit":
        secrets = gate_job.get("secrets")
        mapped = secrets if isinstance(secrets, dict) else {}
        for name in REQUIRED_SECRETS:
            if name not in mapped:
                violations.append(
                    f"missing-secret-map: secret '{name}' not mapped on job '{gate_id}'"
                )

    violations.extend(check_smoke_secrets(with_map))
    contract_violations, manifest = check_ci_contract(with_map, props, consumer_root)
    violations.extend(contract_violations)
    violations.extend(check_image_values(with_map, props, consumer_root, manifest))
    violations.extend(check_extras_values(with_map, props, consumer_root, manifest))
    return violations


def main(argv: list[str]) -> int:
    if argv == ["--emit-manifest"]:
        return emit_manifest()
    parser = argparse.ArgumentParser(
        description="Lint a caller workflow against the gate contract."
    )
    parser.add_argument("caller", type=Path, help="caller workflow YAML to lint")
    parser.add_argument(
        "--contract", required=True, type=Path, help="contract JSON Schema path"
    )
    parser.add_argument(
        "--consumer-root",
        type=Path,
        default=None,
        help="consumer repo root; enables the contract-file and values-local rules",
    )
    args = parser.parse_args(argv)
    props = load_contract(args.contract)
    violations = lint(args.caller, props, args.consumer_root)
    for violation in violations:
        print(violation)
    if violations:
        return 1
    print(f"OK: {args.caller}: caller lint clean")
    return 0


if __name__ == "__main__":
    rc = 1
    try:
        rc = main(sys.argv[1:])
        sys.stdout.flush()
    except BrokenPipeError:
        # A downstream reader (e.g. `... | grep -q`) closed the pipe after
        # matching; the verdict in rc is already computed, so keep it.
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
    sys.exit(rc)
