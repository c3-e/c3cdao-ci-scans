"""Fixture tests for the routes contract in publish-staging-chart.yml's
"Validate chart shape" step.

The step enforces "every pilot must declare a non-empty `routes:` key,
either at the top level or nested one level under the shared
`fullstack-template` engine-dependency key" as a JSON Schema, checked by
`check-jsonschema` (github.com/python-jsonschema/check-jsonschema) — not a
bespoke jq recursion. The schema is built in the workflow via single-quoted
shell-string concatenation (a heredoc's closing delimiter can't satisfy both
YAML's block-scalar indentation rules and bash's "delimiter alone on its
own line" rule at once, so the workflow avoids heredocs for this).

Same drift-guard shape as test_callee_ref_resolver.py: the schema text is
extracted from the workflow file itself (not hand-copied), reassembled
exactly as bash would concatenate it, and then handed to the real
check-jsonschema CLI — so a future edit to the schema is caught by
construction, and the test exercises the actual tool the workflow runs, not
a reimplementation of its logic. Case values.yaml content is inlined below
rather than kept as separate fixture files: each is a single-purpose,
one-line synthetic snippet with no reuse outside this module.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "publish-staging-chart.yml"

STEP_NAME = "Validate chart shape (lint + routes contract)"
FRAGMENT_RE = re.compile(r"^\s*SCHEMA_JSON(?:=|\+=)'(.*)'\s*$")

CASES = {
    "no routes key anywhere": (
        {"image": {"repository": "example/app", "tag": "1.0.0"}},
        False,
    ),
    "top-level routes: [] (present but empty)": (
        {"image": {"repository": "example/app", "tag": "1.0.0"}, "routes": []},
        False,
    ),
    "top-level routes: [...] (non-empty)": (
        {"image": {"repository": "example/app", "tag": "1.0.0"}, "routes": [{"path": "/", "service": "web"}]},
        True,
    ),
    "nested fullstack-template.routes: [...]": (
        {"fullstack-template": {"routes": [{"path": "/", "service": "web"}]}},
        True,
    ),
}

requires_uvx = pytest.mark.skipif(shutil.which("uvx") is None, reason="uvx not on PATH")


def _extract_schema_json() -> str:
    """Reassemble the SCHEMA_JSON literal exactly as bash would: each
    `SCHEMA_JSON=` / `SCHEMA_JSON+=` line's single-quoted fragment,
    concatenated in file order."""
    jobs = yaml.safe_load(WORKFLOW.read_text())["jobs"]
    steps = jobs["publish-staging-chart"]["steps"]
    matches = [s for s in steps if s.get("name") == STEP_NAME]
    assert len(matches) == 1, f"expected exactly one step named {STEP_NAME!r}"
    run = matches[0]["run"]
    fragments = [m.group(1) for line in run.splitlines() if (m := FRAGMENT_RE.match(line))]
    assert fragments, "could not locate any SCHEMA_JSON fragment in the workflow step"
    return "".join(fragments)


def test_schema_is_extracted_and_well_formed():
    """Sanity check on the extraction itself, independent of the case runs
    below: the reassembled text must be the real schema, not noise."""
    schema = json.loads(_extract_schema_json())
    assert schema["title"] == "Pilot chart values.yaml routes contract"
    assert len(schema["anyOf"]) == 2


@pytest.fixture(scope="module")
def schema_file(tmp_path_factory):
    path = tmp_path_factory.mktemp("chart-shape") / "chart-shape.schema.json"
    path.write_text(_extract_schema_json())
    return path


@requires_uvx
@pytest.mark.parametrize("case_name", CASES)
def test_routes_contract(schema_file, tmp_path, case_name):
    values, should_pass = CASES[case_name]
    values_file = tmp_path / "values.yaml"
    values_file.write_text(yaml.safe_dump(values))

    result = subprocess.run(
        ["uvx", "check-jsonschema", "--schemafile", str(schema_file), str(values_file)],
        capture_output=True,
        text=True,
    )

    if should_pass:
        assert result.returncode == 0, result.stdout + result.stderr
    else:
        assert result.returncode != 0
