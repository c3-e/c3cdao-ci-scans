# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
"""Derive the published gate request contract from `workflow_call.inputs`.

Writes contract/security-gate.schema.json (JSON Schema draft 2020-12, one
property per input) and rewrites the generated inputs table in docs/INPUTS.md
between the BEGIN/END markers. Never hand-edit the outputs — this script is
the only writer. Content outside the markers (the hand-written preamble and
worked examples) is preserved untouched.

Modes:
    (no args)              extract schema + docs/INPUTS.md table
    --check-descriptions   exit non-zero listing inputs with missing/blank
                           descriptions; writes nothing
    --emit-confluence      print the API reference (inputs + secrets) as
                           Confluence storage-format XHTML on stdout;
                           writes nothing

Also importable by sibling scripts:
    load_gha_workflow(path) -> dict (triggers normalized under "on")
"""

import json
import os
import sys
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "reusable-security-gate.yml"
SCHEMA_PATH = REPO_ROOT / "contract" / "security-gate.schema.json"
INPUTS_DOC_PATH = REPO_ROOT / "docs" / "INPUTS.md"
SCHEMA_ID = "https://github.com/c3-e/c3cdao-ci-scans/contract/security-gate.schema.json"
BEGIN_MARKER = "<!-- BEGIN GENERATED: security-gate-inputs -->"
END_MARKER = "<!-- END GENERATED: security-gate-inputs -->"

# GHA input types -> JSON Schema types (everything else GHA validates as string)
_JSON_TYPES = {"boolean": "boolean", "number": "number"}


def load_gha_workflow(path: Path) -> dict[str, Any]:
    """Parse a GitHub Actions workflow YAML with the trigger key normalized.

    PyYAML (YAML 1.1) parses a bare ``on:`` key as boolean ``True``, so a
    workflow's triggers land under the key ``True`` instead of ``"on"``.
    This helper resolves that quirk in exactly one place: the returned dict
    always carries the triggers under ``"on"``. Side-effect-free, PyYAML
    only — safe to import from sibling scripts.
    """
    try:
        wf = yaml.safe_load(path.read_text())
    except OSError as e:
        raise SystemExit(f"error: {path}: {e}") from e
    except yaml.YAMLError as e:
        raise SystemExit(f"error: {path}: unparseable workflow: {e}") from e
    if not isinstance(wf, dict):
        raise SystemExit(f"error: {path}: workflow must be a YAML mapping")
    wf["on"] = wf.get("on") or wf.pop(True, None)
    return wf


def workflow_inputs(path: Path) -> dict[str, Any]:
    """Return the workflow_call.inputs mapping, or exit naming what's missing."""
    wf = load_gha_workflow(path)
    on = wf["on"] if isinstance(wf["on"], dict) else {}
    inputs = (on.get("workflow_call") or {}).get("inputs")
    if not isinstance(inputs, dict) or not inputs:
        raise SystemExit(f"error: {path}: no workflow_call.inputs found")
    return inputs


def build_schema(inputs: dict[str, Any]) -> dict[str, Any]:
    properties: dict[str, dict[str, Any]] = {}
    for name, spec in inputs.items():
        if not isinstance(spec, dict):
            raise SystemExit(f"error: input {name!r}: not a mapping")
        missing = [f for f in ("type", "default", "description") if f not in spec]
        if missing:
            raise SystemExit(
                f"error: input {name!r}: missing field(s): {', '.join(missing)}"
            )
        properties[name] = {
            "type": _JSON_TYPES.get(spec["type"], "string"),
            "default": spec["default"],
            "description": spec["description"],
        }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": SCHEMA_ID,
        "title": "Security gate request contract (workflow_call inputs)",
        "type": "object",
        "additionalProperties": False,
        # no "required": every input is defaulted
        "properties": properties,
    }


def check_descriptions(inputs: dict[str, Any]) -> None:
    bad = [
        name
        for name, spec in inputs.items()
        if not isinstance(spec, dict) or not str(spec.get("description") or "").strip()
    ]
    if bad:
        for name in bad:
            print(
                f"error: input {name!r}: missing or blank description", file=sys.stderr
            )
        raise SystemExit(1)


def render_inputs_table(inputs: dict[str, Any]) -> str:
    lines = [
        "| Input | Type | Default | Where the value comes from |",
        "| --- | --- | --- | --- |",
    ]
    for name, spec in inputs.items():
        default = spec["default"]
        if isinstance(default, bool):
            shown = "true" if default else "false"
        else:
            shown = str(default) or '""'
        description = str(spec["description"]).replace("|", "\\|")
        lines.append(f"| `{name}` | {spec['type']} | `{shown}` | {description} |")
    return "\n".join(lines)


def write_inputs_table(inputs: dict[str, Any]) -> None:
    """Rewrite only the marked block in docs/INPUTS.md; preserve the rest.

    The hand-written preamble and worked examples live outside the BEGIN/END
    markers and are never touched — this replaces solely the content between
    them, so repeated runs on a clean tree are byte-idempotent.
    """
    try:
        text = INPUTS_DOC_PATH.read_text()
    except OSError as e:
        raise SystemExit(f"error: {INPUTS_DOC_PATH}: {e}") from e
    has_begin = BEGIN_MARKER in text
    has_end = END_MARKER in text
    if not has_begin and not has_end:
        print(
            f"notice: {INPUTS_DOC_PATH.name} markers not found; inputs table not written",
            file=sys.stderr,
        )
        return
    if not (has_begin and has_end):
        missing = END_MARKER if has_begin else BEGIN_MARKER
        raise SystemExit(
            f"error: {INPUTS_DOC_PATH}: malformed generated block: missing marker {missing!r}"
        )
    head, rest = text.split(BEGIN_MARKER, 1)
    _, tail = rest.split(END_MARKER, 1)
    new = f"{head}{BEGIN_MARKER}\n{render_inputs_table(inputs)}\n{END_MARKER}{tail}"
    if new != text:
        try:
            INPUTS_DOC_PATH.write_text(new)
        except OSError as e:
            raise SystemExit(f"error: {INPUTS_DOC_PATH}: {e}") from e


# --- Confluence API-reference emitter (--emit-confluence) -------------------

# Section order for the Confluence reference. Inputs not named here fall
# through to a trailing "Other inputs" section, so new workflow inputs are
# never silently dropped from the page.
_CONFLUENCE_SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Core build inputs",
        (
            "scan_image",
            "contract_file",
            "builder_image",
            "runtime_image",
        ),
    ),
    (
        "Cluster-smoke inputs",
        (
            "cluster_name",
            "smoke_secrets",
            "image_only",
        ),
    ),
    (
        "Hardened-base and failover inputs",
        (
            "require_hardened_bases",
            "ironbank_registry",
            "ironbank_builder_image",
            "ironbank_runtime_image",
        ),
    ),
)

# The workflow declares secrets with `required` only; purpose text mirrors
# the "Required secrets" table in docs/RUNBOOK.md.
_SECRET_PURPOSE = {
    "CGR_PULL_TOKEN": ("Phase 1 build - Chainguard (cgr.dev) registry login token."),
    "CGR_PULL_USERNAME": (
        "Phase 1 build - Chainguard (cgr.dev) registry login username."
    ),
    "IRONBANK_TOKEN": (
        "SonarQube ephemeral + build Iron Bank (registry1.dso.mil) login "
        "token - runs alongside Chainguard when both are set."
    ),
    "IRONBANK_USERNAME": (
        "Iron Bank (registry1.dso.mil) login username, paired with IRONBANK_TOKEN."
    ),
}

_TABLE_HEADER = (
    "<tr><th>Input</th><th>Type</th><th>Default</th>"
    "<th>Required</th><th>Description</th></tr>"
)


def workflow_secrets(path: Path) -> dict[str, Any]:
    """Return the workflow_call.secrets mapping (empty dict when absent)."""
    wf = load_gha_workflow(path)
    on = wf["on"] if isinstance(wf["on"], dict) else {}
    secrets = (on.get("workflow_call") or {}).get("secrets")
    return secrets if isinstance(secrets, dict) else {}


def _xml(value: Any) -> str:
    return escape(str(value))


def _shown_default(default: Any) -> str:
    if isinstance(default, bool):
        return "true" if default else "false"
    return str(default) or '""'


def _input_row(name: str, spec: dict[str, Any]) -> str:
    required = "yes" if spec.get("required") else "no"
    return (
        "<tr>"
        f"<td><code>{_xml(name)}</code></td>"
        f"<td>{_xml(spec['type'])}</td>"
        f"<td><code>{_xml(_shown_default(spec['default']))}</code></td>"
        f"<td>{required}</td>"
        f"<td>{_xml(spec['description'])}</td>"
        "</tr>"
    )


def render_confluence(inputs: dict[str, Any], secrets: dict[str, Any]) -> str:
    """Render the full inputs + secrets reference as storage-format XHTML."""
    grouped = {name for _, members in _CONFLUENCE_SECTIONS for name in members}
    leftovers = tuple(name for name in inputs if name not in grouped)
    sections = _CONFLUENCE_SECTIONS + (("Other inputs", leftovers),)
    parts: list[str] = []
    for title, members in sections:
        rows = [_input_row(n, inputs[n]) for n in members if n in inputs]
        if not rows:
            continue
        parts.append(f"<h2>{_xml(title)}</h2>")
        parts.append(
            "<table><tbody>" + _TABLE_HEADER + "".join(rows) + "</tbody></table>"
        )
    if secrets:
        parts.append("<h2>Secrets</h2>")
        srows = [
            "<tr>"
            f"<td><code>{_xml(name)}</code></td>"
            f"<td>{'yes' if (spec or {}).get('required') else 'no'}</td>"
            f"<td>{_xml(_SECRET_PURPOSE.get(name, ''))}</td>"
            "</tr>"
            for name, spec in secrets.items()
        ]
        parts.append(
            "<table><tbody>"
            "<tr><th>Secret</th><th>Required</th><th>Purpose</th></tr>"
            + "".join(srows)
            + "</tbody></table>"
        )
    return "\n".join(parts)


def main(argv: list[str]) -> int:
    inputs = workflow_inputs(WORKFLOW_PATH)
    if "--check-descriptions" in argv:
        check_descriptions(inputs)
        print(f"OK: {len(inputs)} inputs, all described")
        return 0
    if "--emit-confluence" in argv:
        print(render_confluence(inputs, workflow_secrets(WORKFLOW_PATH)))
        return 0
    schema_text = json.dumps(build_schema(inputs), indent=2, sort_keys=True) + "\n"
    try:
        SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
        SCHEMA_PATH.write_text(schema_text)
    except OSError as e:
        raise SystemExit(f"error: {SCHEMA_PATH}: {e}") from e
    write_inputs_table(inputs)
    print(f"wrote {SCHEMA_PATH.relative_to(REPO_ROOT)} ({len(inputs)} inputs)")
    return 0


if __name__ == "__main__":
    try:
        rc = main(sys.argv[1:])
        sys.stdout.flush()
    except BrokenPipeError:
        # A downstream reader (e.g. `... | grep -q`) closed the pipe after
        # matching; all file writes are already done, so this is a success.
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        rc = 0
    sys.exit(rc)
