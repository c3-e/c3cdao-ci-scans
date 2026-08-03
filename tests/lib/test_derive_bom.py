"""Unit tests for the annotated BOM derivation (derive_bom.py).

Plan fixtures are `--print` JSON captured from real `docker buildx bake`
runs against tests/fixtures/bake/ (buildx v0.29.1, 2026-07-31) — never
hand-authored. The resolve-error stderr fixture is likewise real bake
output. The live-bake path is re-exercised at IG-1.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

from derive_bom import bom_sha256, canonical_json, derive_bom, run_bake_print  # noqa: E402

FIXTURES = REPO_ROOT / "tests" / "fixtures" / "bake"
N3 = FIXTURES / "n3-local-profile"
N1 = FIXTURES / "n1"
RESOLVE_ERROR = FIXTURES / "resolve-error"


def _load_plan(fixture_dir: Path) -> dict:
    return json.loads((fixture_dir / "bake-print.json").read_text())


def test_n3_annotation_targets_excluded_dependencies():
    bom = derive_bom(N3 / "docker-compose.yml", _load_plan(N3))
    assert bom["targets"] == ["svc-a", "svc-b", "svc-c"]
    assert bom["excluded"] == [
        {"service": "svc-local", "reason": "profiles: [local]"}
    ]
    assert bom["dependencies"] == [
        {
            "service": "dep-db",
            "image": (
                "pgvector/pgvector:pg16@sha256:a36250871de0833b8757561c72f2477e"
                "f1ddd1101afa4e617fb552e0de514c6b"
            ),
            "digest": (
                "sha256:a36250871de0833b8757561c72f2477ef1ddd1101afa4e617fb552e"
                "0de514c6b"
            ),
            "chart_tag": "pgvector/pgvector:pg16",
        }
    ]


def test_resolve_error_exits_nonzero_naming_rule_with_bake_stderr(monkeypatch, capsys):
    """A failing bake resolve surfaces rule id + real bake stderr (AC-3).

    The canned stderr is the captured output of a real failing
    `docker buildx bake --print` run against the resolve-error fixture.
    """
    import subprocess

    bake_stderr = (RESOLVE_ERROR / "bake-stderr.txt").read_text()

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 1, stdout="", stderr=bake_stderr)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(SystemExit) as exc:
        run_bake_print(RESOLVE_ERROR / "docker-compose.yml", ["app"])
    assert exc.value.code != 0
    err = capsys.readouterr().err
    assert "bake-resolve" in err
    assert "services.app.image must be a string" in err


def test_hash_identical_for_identical_inputs():
    """Canonical serialization is deterministic (AC-2)."""
    first = derive_bom(N3 / "docker-compose.yml", _load_plan(N3))
    second = derive_bom(N3 / "docker-compose.yml", _load_plan(N3))
    assert canonical_json(first) == canonical_json(second)
    assert bom_sha256(first) == bom_sha256(second)


def test_hash_changes_when_input_changes():
    n3 = derive_bom(N3 / "docker-compose.yml", _load_plan(N3))
    n1 = derive_bom(N1 / "docker-compose.yml", _load_plan(N1))
    assert bom_sha256(n3) != bom_sha256(n1)


def test_unmarked_external_image_neither_target_nor_dependency(tmp_path):
    """image: without build: and without x-downloaded-dependency (AC-4)."""
    compose = tmp_path / "docker-compose.yml"
    compose.write_text(
        (N3 / "docker-compose.yml").read_text()
        + "\n  ext-app:\n    image: registry.example/ext-app:1.0.0\n"
    )
    bom = derive_bom(compose, _load_plan(N3))
    assert bom["targets"] == ["svc-a", "svc-b", "svc-c"]
    assert "ext-app" not in [d["service"] for d in bom["dependencies"]]
    assert [u["service"] for u in bom["unmarked"]] == ["ext-app"]
    assert "x-downloaded-dependency" in bom["unmarked"][0]["reason"]


def test_unmarked_when_digest_or_chart_tag_missing(tmp_path):
    """Tag-only pin or missing chart-tag degrades to unmarked, not dependency."""
    compose = tmp_path / "docker-compose.yml"
    compose.write_text(
        "services:\n"
        "  app:\n"
        "    build: {context: .}\n"
        "    image: app:1\n"
        "  dep-tag-only:\n"
        "    image: registry.example/db:16\n"
        "    x-downloaded-dependency:\n"
        "      chart-tag: registry.example/db:16\n"
        "  dep-no-chart-tag:\n"
        "    image: registry.example/db:16@sha256:"
        + "0" * 64
        + "\n"
        "    x-downloaded-dependency: {}\n"
    )
    bom = derive_bom(compose, {"target": {"app": {}}})
    assert bom["dependencies"] == []
    assert [u["service"] for u in bom["unmarked"]] == [
        "dep-no-chart-tag",
        "dep-tag-only",
    ]


def test_target_list_sorted_nonlocal_build_services_only(tmp_path):
    """Explicit target selection is load-bearing (SPIKE-01): the list is
    exactly the sorted non-local build services; local-profile and
    image-only services never appear."""
    compose = tmp_path / "docker-compose.yml"
    compose.write_text(
        "services:\n"
        "  zeta:\n"
        "    build: {context: .}\n"
        "    image: zeta:1\n"
        "  alpha:\n"
        "    build: {context: .}\n"
        "    image: alpha:1\n"
        "  tool:\n"
        "    profiles: [local]\n"
        "    build: {context: .}\n"
        "    image: tool:1\n"
    )
    bom = derive_bom(compose, {"target": {"alpha": {}, "zeta": {}}})
    assert bom["targets"] == ["alpha", "zeta"]


def test_n1_single_target_empty_annotations_plan_untouched():
    """N=1 derivation: one target, empty annotation lists, placeholder +
    provenance present, and the bake plan document is never mutated."""
    plan = _load_plan(N1)
    before = json.dumps(plan, sort_keys=True)
    bom = derive_bom(N1 / "docker-compose.yml", plan)
    assert bom["targets"] == ["app"]
    assert bom["excluded"] == []
    assert bom["dependencies"] == []
    assert bom["unmarked"] == []
    assert bom["smoke_target"] is None
    assert bom["plan_sha256"] == hashlib.sha256(
        json.dumps(plan, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    ).hexdigest()
    assert isinstance(bom["provenance"], dict)
    assert all(isinstance(v, str) and v for v in bom["provenance"].values())
    assert json.dumps(plan, sort_keys=True) == before


def test_missing_compose_fails_closed_naming_path(tmp_path):
    missing = tmp_path / "docker-compose.yml"
    with pytest.raises(SystemExit) as exc:
        derive_bom(missing, {"target": {}})
    assert str(missing) in str(exc.value)


def test_compose_without_services_mapping_fails_closed(tmp_path):
    compose = tmp_path / "docker-compose.yml"
    compose.write_text("just a string\n")
    with pytest.raises(SystemExit) as exc:
        derive_bom(compose, {"target": {}})
    assert "services" in str(exc.value)


def test_plan_target_mismatch_fails_closed():
    """Plan/derivation parity: the resolved plan must carry exactly the
    compose-derived non-local targets."""
    plan = _load_plan(N3)
    del plan["target"]["svc-c"]
    with pytest.raises(SystemExit) as exc:
        derive_bom(N3 / "docker-compose.yml", plan)
    assert "svc-c" in str(exc.value)


def test_bake_print_command_carries_execution_overrides():
    """The published plan must resolve with the SAME --set overrides the
    build legs execute with (plan/execution parity, T-5 AC-3): gate
    overrides append after the platform pin, before the targets."""
    from derive_bom import bake_print_command

    overrides = ["*.args.BUILDER_IMAGE=cgr.dev/b:1", "*.args.RUNTIME_IMAGE=cgr.dev/r:1"]
    cmd = bake_print_command(N3 / "docker-compose.yml", ["svc-a"], overrides)
    platform_i = cmd.index("*.platform=linux/amd64")
    assert cmd[platform_i - 1] == "--set"
    assert cmd[platform_i + 1 : platform_i + 5] == [
        "--set",
        overrides[0],
        "--set",
        overrides[1],
    ]
    assert cmd[-1] == "svc-a"
    # No overrides: command unchanged from the pre-T-5 shape.
    assert bake_print_command(N3 / "docker-compose.yml", ["svc-a"])[-2:] == [
        "*.platform=linux/amd64",
        "svc-a",
    ]


def test_main_threads_set_overrides_to_bake_print(tmp_path, monkeypatch):
    """CLI --set values reach the bake --print invocation."""
    import derive_bom as mod

    plan = _load_plan(N3)
    seen: dict = {}

    def fake_run(compose_path, targets, overrides=()):
        seen["overrides"] = list(overrides)
        return plan

    monkeypatch.setattr(mod, "run_bake_print", fake_run)
    rc = mod.main(
        [
            str(N3 / "docker-compose.yml"),
            "--out-dir",
            str(tmp_path / "out"),
            "--set",
            "*.args.BUILDER_IMAGE=x",
            "--set",
            "*.args.RUNTIME_IMAGE=y",
        ]
    )
    assert rc == 0
    assert seen["overrides"] == [
        "*.args.BUILDER_IMAGE=x",
        "*.args.RUNTIME_IMAGE=y",
    ]


def test_main_writes_sibling_documents(tmp_path, monkeypatch, capsys):
    """CLI runs bake --print with explicit targets and writes the plan and
    the annotation as sibling files (never merged)."""
    import derive_bom as mod

    plan = _load_plan(N3)
    seen: dict = {}

    def fake_run(compose_path, targets, overrides=()):
        seen["targets"] = targets
        return plan

    monkeypatch.setattr(mod, "run_bake_print", fake_run)
    out_dir = tmp_path / "out"
    rc = mod.main([str(N3 / "docker-compose.yml"), "--out-dir", str(out_dir)])
    assert rc == 0
    assert seen["targets"] == ["svc-a", "svc-b", "svc-c"]
    plan_doc = json.loads((out_dir / "bake-plan.json").read_text())
    assert plan_doc == plan
    bom_doc = json.loads((out_dir / "bom.json").read_text())
    assert bom_doc["targets"] == ["svc-a", "svc-b", "svc-c"]
    assert bom_sha256(bom_doc) in capsys.readouterr().out
