"""Unit tests for the v0.6 fail-closed convention lint (lint_caller.py).

One test per rule id (AC-1..15, test names = rule ids), ship-set
repository+chart-tag matching (AC-16), and the built-unscheduled warn
path (AC-17). Rule functions are pure where possible; compose inputs are
authored inline per test, chart inputs are parsed rendered documents.
The committed ship-set-violation and n3-local-profile fixtures are
consumed here and again by the plan-job integration gate.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

from derive_bom import classify_services  # noqa: E402
from lint_caller import (  # noqa: E402
    bake_resolve,
    build_context_excludes,
    build_input_explicit,
    chart_missing,
    chart_readiness,
    chart_resolve,
    chart_undeclared,
    compose_healthcheck,
    compose_image_tag,
    compose_missing,
    compose_no_builds,
    compose_platform,
    convention_verdicts,
    dependency_shape,
    hardened_args,
    lint_caller_workflow,
    matrix_cap,
    render_chart,
    ship_set,
    smoke_resource_unknown,
    smoke_target,
    built_unscheduled,
)

FIXTURES = REPO_ROOT / "tests" / "fixtures" / "bake"


def classify(compose: dict) -> dict:
    return classify_services(compose)


def build_service(image: str = "app:1.0.0", **extra) -> dict:
    svc = {
        "build": {"context": "."},
        "image": image,
        "healthcheck": {"test": ["CMD", "true"]},
    }
    svc.update(extra)
    return svc


def only_rule(verdicts: list[dict], rule_id: str) -> dict:
    """The single verdict, asserted to name exactly the expected rule."""
    assert len(verdicts) == 1, verdicts
    v = verdicts[0]
    assert v["rule_id"] == rule_id, v
    assert v["level"] == "block", v
    assert v["message"]
    assert v["remediation_ref"].endswith(f"#rule-{rule_id}")
    return v


# --- compose presence / shape ------------------------------------------------


def test_compose_missing(tmp_path):
    absent = tmp_path / "docker-compose.yml"
    v = only_rule(compose_missing(absent), "compose-missing")
    assert str(absent) in v["message"]


def test_compose_missing_unparseable_fails_closed(tmp_path):
    broken = tmp_path / "docker-compose.yml"
    broken.write_text("services: [unclosed\n")
    only_rule(compose_missing(broken), "compose-missing")


def test_compose_missing_passes_on_readable_compose(tmp_path):
    ok = tmp_path / "docker-compose.yml"
    ok.write_text("services:\n  app:\n    build: {context: .}\n    image: a:1\n")
    assert compose_missing(ok) == []


def test_compose_no_builds():
    classified = classify(
        {
            "services": {
                "dep": {"image": "registry.example/db:16"},
                "tool": {
                    "profiles": ["local"],
                    "build": {"context": "."},
                    "image": "tool:1",
                },
            }
        }
    )
    only_rule(compose_no_builds(classified), "compose-no-builds")


def test_compose_no_builds_passes_with_one_target():
    classified = classify({"services": {"app": build_service()}})
    assert compose_no_builds(classified) == []


def test_matrix_cap():
    services = {f"svc-{i:02d}": build_service(f"svc-{i:02d}:1") for i in range(11)}
    v = only_rule(matrix_cap(classify({"services": services})), "matrix-cap")
    assert "11" in v["message"]


def test_matrix_cap_passes_at_ten():
    services = {f"svc-{i:02d}": build_service(f"svc-{i:02d}:1") for i in range(10)}
    assert matrix_cap(classify({"services": services})) == []


# --- per-service compose rules -------------------------------------------------


def test_compose_image_tag():
    compose = {
        "services": {
            "no-image": {"build": {"context": "."}},
            "untagged": build_service("registry.example/app"),
            "latest": build_service("registry.example/app:latest"),
        }
    }
    verdicts = compose_image_tag(compose, classify(compose))
    assert [v["rule_id"] for v in verdicts] == ["compose-image-tag"] * 3
    named = " ".join(v["message"] for v in verdicts)
    assert "no-image" in named and "untagged" in named and "latest" in named
    assert all(v["level"] == "block" for v in verdicts)


def test_compose_image_tag_passes_on_explicit_tag():
    compose = {"services": {"app": build_service("registry.example/app:1.2.3")}}
    assert compose_image_tag(compose, classify(compose)) == []


def test_compose_image_tag_blocks_interpolated_reference():
    """`image: app:${TAG}` resolves empty under the gate's
    scrubbed environment — block at the front door, naming interpolation."""
    compose = {"services": {"app": build_service("app:${TAG}")}}
    v = only_rule(compose_image_tag(compose, classify(compose)), "compose-image-tag")
    assert "interpolat" in v["message"]
    assert "app:${TAG}" in v["message"]


def test_compose_image_tag_allows_escaped_literal_dollar():
    """`$$` is Compose's literal-dollar escape, not interpolation."""
    compose = {"services": {"app": build_service("registry.example/app:v1$$rc")}}
    assert compose_image_tag(compose, classify(compose)) == []


def test_compose_healthcheck():
    svc = build_service("app:1")
    del svc["healthcheck"]
    compose = {"services": {"app": svc}}
    v = only_rule(compose_healthcheck(compose, classify(compose)), "compose-healthcheck")
    assert "app" in v["message"]


def test_compose_healthcheck_local_profile_exempt():
    svc = build_service("tool:1", profiles=["local"])
    del svc["healthcheck"]
    compose = {"services": {"tool": svc, "app": build_service("app:1")}}
    assert compose_healthcheck(compose, classify(compose)) == []


def test_compose_platform():
    compose = {
        "services": {
            "app": build_service("app:1", platform="linux/arm64"),
            "ok": build_service("ok:1", platform="linux/amd64"),
        }
    }
    v = only_rule(compose_platform(compose), "compose-platform")
    assert "linux/arm64" in v["message"] and "app" in v["message"]


def test_compose_platform_checks_build_level_platforms():
    compose = {
        "services": {
            "app": {
                "build": {"context": ".", "platforms": ["linux/arm64"]},
                "image": "app:1",
                "healthcheck": {"test": ["CMD", "true"]},
            }
        }
    }
    only_rule(compose_platform(compose), "compose-platform")


def test_dependency_shape():
    compose = {
        "services": {
            "app": build_service("app:1"),
            "dep-tag-only": {"image": "registry.example/db:16"},
        }
    }
    v = only_rule(dependency_shape(classify(compose)), "dependency-shape")
    assert "dep-tag-only" in v["message"]


def test_dependency_shape_passes_on_declared_digest_pinned_dependency():
    """The n3 fixture's dep-db shape is the conforming exemplar (IG-1 prep)."""
    import yaml

    compose = yaml.safe_load(
        (FIXTURES / "n3-local-profile" / "docker-compose.yml").read_text()
    )
    assert dependency_shape(classify(compose)) == []


# --- explicit build inputs ------------------------------------------------------


def test_build_input_explicit():
    compose = {
        "services": {
            "list-args": {
                "build": {"context": ".", "args": ["HOST_ARG"]},
                "image": "a:1",
            },
            "null-arg": {
                "build": {"context": ".", "args": {"PASSTHRU": None}},
                "image": "b:1",
            },
            "interpolated": {
                "build": {"context": "${BUILD_DIR}", "args": {"X": "1"}},
                "image": "c:1",
            },
            "secret-like": {
                "build": {"context": ".", "args": {"NPM_TOKEN": "abc"}},
                "image": "d:1",
            },
            "build-secrets": {
                "build": {"context": ".", "secrets": ["npmrc"]},
                "image": "e:1",
            },
            "build-ssh": {
                "build": {"context": ".", "ssh": ["default"]},
                "image": "f:1",
            },
        }
    }
    for svc in compose["services"].values():
        svc["healthcheck"] = {"test": ["CMD", "true"]}
    verdicts = build_input_explicit(compose, classify(compose))
    assert {v["rule_id"] for v in verdicts} == {"build-input-explicit"}
    assert all(v["level"] == "block" for v in verdicts)
    named = " ".join(v["message"] for v in verdicts)
    for offender in compose["services"]:
        assert offender in named, offender


def test_build_input_explicit_passes_on_literal_mapping():
    compose = {
        "services": {
            "app": {
                "build": {"context": ".", "args": {"SVC_NAME": "app"}},
                "image": "app:1",
                "healthcheck": {"test": ["CMD", "true"]},
            }
        }
    }
    assert build_input_explicit(compose, classify(compose)) == []


def test_build_context_excludes(tmp_path):
    compose_path = tmp_path / "docker-compose.yml"
    compose = {"services": {"app": build_service("app:1")}}
    # No .dockerignore at all -> block
    v = only_rule(
        build_context_excludes(compose_path, compose, classify(compose)),
        "build-context-excludes",
    )
    assert ".dockerignore" in v["message"]
    # Present but missing required exclusions -> block naming what's absent
    (tmp_path / ".dockerignore").write_text(".env\n")
    v = only_rule(
        build_context_excludes(compose_path, compose, classify(compose)),
        "build-context-excludes",
    )
    assert "*.pem" in v["message"]


def test_build_context_excludes_passes_with_required_entries(tmp_path):
    compose_path = tmp_path / "docker-compose.yml"
    (tmp_path / ".dockerignore").write_text(
        ".env\n*.pem\n*.key\n*credentials*\n"
    )
    compose = {"services": {"app": build_service("app:1")}}
    assert (
        build_context_excludes(compose_path, compose, classify(compose)) == []
    )


def test_hardened_args(tmp_path):
    compose_path = tmp_path / "docker-compose.yml"
    (tmp_path / "Dockerfile").write_text(
        "ARG BUILDER_IMAGE=alpine:3.20\nFROM ${BUILDER_IMAGE}\n"
    )
    compose = {"services": {"app": build_service("app:1")}}
    v = only_rule(
        hardened_args(compose_path, compose, classify(compose)), "hardened-args"
    )
    assert "RUNTIME_IMAGE" in v["message"] and "Dockerfile" in v["message"]


def test_hardened_args_missing_dockerfile_fails_closed(tmp_path):
    compose_path = tmp_path / "docker-compose.yml"
    compose = {"services": {"app": build_service("app:1")}}
    only_rule(
        hardened_args(compose_path, compose, classify(compose)), "hardened-args"
    )


def test_hardened_args_passes_on_blessed_pair():
    import yaml

    fixture = FIXTURES / "n3-local-profile"
    compose = yaml.safe_load((fixture / "docker-compose.yml").read_text())
    assert (
        hardened_args(fixture / "docker-compose.yml", compose, classify(compose))
        == []
    )


# --- chart-declaration consistency (BL-1, T-12) ---------------------------------


def test_chart_missing(tmp_path):
    v = only_rule(chart_missing(tmp_path / "chart"), "chart-missing")
    assert "chart" in v["message"]


def test_chart_missing_passes_when_chart_yaml_present(tmp_path):
    chart = tmp_path / "chart"
    chart.mkdir()
    (chart / "Chart.yaml").write_text("apiVersion: v2\nname: x\nversion: 0.1.0\n")
    assert chart_missing(chart) == []


def test_chart_undeclared(tmp_path):
    """image_only: true with a chart anywhere in the repo tree blocks —
    the repo-wide glob, not chart_path-only (rescreen's pre-rollout shape:
    image_only: true while owning helm/resume-screener)."""
    nested = tmp_path / "helm" / "resume-screener"
    nested.mkdir(parents=True)
    (nested / "Chart.yaml").write_text("apiVersion: v2\nname: x\nversion: 0.1.0\n")
    v = only_rule(chart_undeclared(tmp_path), "chart-undeclared")
    assert "helm/resume-screener" in v["message"]


def test_chart_undeclared_passes_with_no_chart_anywhere(tmp_path):
    (tmp_path / "docker-compose.yml").write_text("services: {}\n")
    assert chart_undeclared(tmp_path) == []


def test_chart_undeclared_excludes_vendored_charts_dir(tmp_path):
    """A vendored dependency copy under any `charts/` directory never
    false-positives (cra's vendored fullstack-template-adjacent trees)."""
    vendored = tmp_path / "helm" / "app" / "charts" / "fullstack-template"
    vendored.mkdir(parents=True)
    (vendored / "Chart.yaml").write_text("apiVersion: v2\nname: dep\nversion: 0.1.0\n")
    assert chart_undeclared(tmp_path) == []


def test_chart_resolve_wraps_helm_failure_as_named_verdict():
    """A chart whose dependency cannot be resolved fails closed with a
    named, remediation-linked verdict — not an uncaught SystemExit (T-13
    AC-2, F-C1)."""
    chart_path = FIXTURES / "chart-broken-dependency" / "chart"
    rendered, verdicts = chart_resolve(chart_path)
    assert rendered is None
    v = only_rule(verdicts, "chart-resolve")
    assert "missing-sub" in v["message"] or "charts/" in v["message"]


def test_chart_resolve_passes_after_dependency_build():
    """Once `helm dependency build` vendors the file:// dependency (the
    plan job's new step, T-13 AC-1), the chart renders with no committed
    charts/*.tgz required."""
    import shutil
    import subprocess

    chart_path = FIXTURES / "chart-file-dependency" / "chart"
    vendored = chart_path / "charts"
    assert not vendored.exists(), "fixture must not commit a vendored charts/ dir"
    try:
        subprocess.run(
            ["helm", "dependency", "build", str(chart_path)],
            capture_output=True,
            text=True,
            check=True,
        )
        rendered, verdicts = chart_resolve(chart_path)
        assert verdicts == []
        assert rendered
    finally:
        shutil.rmtree(vendored, ignore_errors=True)


# --- bake resolve ---------------------------------------------------------------


def test_bake_resolve(monkeypatch):
    """A failing `bake --print` blocks with the rule id and bake's stderr.

    The canned stderr is captured output of a real failing bake run
    against the resolve-error fixture (live path at the plan-job gate run).
    """
    import subprocess

    bake_stderr = (FIXTURES / "resolve-error" / "bake-stderr.txt").read_text()

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 1, stdout="", stderr=bake_stderr)

    monkeypatch.setattr(subprocess, "run", fake_run)
    plan, verdicts = bake_resolve(
        FIXTURES / "resolve-error" / "docker-compose.yml", ["app"]
    )
    assert plan is None
    v = only_rule(verdicts, "bake-resolve")
    assert "services.app.image must be a string" in v["message"]


def test_bake_resolve_passes_returning_plan(monkeypatch):
    import subprocess

    stdout = (FIXTURES / "n3-local-profile" / "bake-print.json").read_text()

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, stdout=stdout, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    plan, verdicts = bake_resolve(
        FIXTURES / "n3-local-profile" / "docker-compose.yml",
        ["svc-a", "svc-b", "svc-c"],
    )
    assert verdicts == []
    assert sorted(plan["target"]) == ["svc-a", "svc-b", "svc-c"]


# --- rendered-chart rules -------------------------------------------------------


def deployment(name: str, containers: list[dict], labels: dict | None = None) -> dict:
    labels = labels or {"app": name}
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": name},
        "spec": {
            "selector": {"matchLabels": labels},
            "template": {
                "metadata": {"labels": labels},
                "spec": {"containers": containers},
            },
        },
    }


def service(name: str, selector: dict, port: int, target_port: int | str) -> dict:
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": name},
        "spec": {
            "selector": selector,
            "ports": [{"port": port, "targetPort": target_port}],
        },
    }


def http_container(name: str, image: str = "app:1", port: int = 8080) -> dict:
    return {
        "name": name,
        "image": image,
        "ports": [{"containerPort": port}],
        "readinessProbe": {"httpGet": {"path": "/healthz", "port": port}},
    }


def exec_container(name: str, image: str = "app:1") -> dict:
    return {
        "name": name,
        "image": image,
        "readinessProbe": {"exec": {"command": ["true"]}},
    }


def test_chart_readiness():
    rendered = [
        deployment(
            "web",
            [http_container("web"), {"name": "sidecar", "image": "side:1"}],
        )
    ]
    v = only_rule(chart_readiness(rendered), "chart-readiness")
    assert "web" in v["message"] and "sidecar" in v["message"]


def test_chart_readiness_passes_and_ignores_non_workloads():
    rendered = [
        {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "cm"}},
        deployment("web", [http_container("web"), exec_container("worker")]),
    ]
    assert chart_readiness(rendered) == []


def test_smoke_target():
    # Zero HTTP readiness targets: exec probe only -> block
    zero = [
        deployment("web", [exec_container("web")]),
        service("web", {"app": "web"}, 80, 8080),
    ]
    v = only_rule(smoke_target(zero), "smoke-target")
    assert "no " in v["message"].lower()

    # Multiple Service-backed HTTP targets -> block naming candidates
    multiple = [
        deployment("web", [http_container("web")]),
        deployment("api", [http_container("api")], labels={"app": "api"}),
        service("web", {"app": "web"}, 80, 8080),
        service("api", {"app": "api"}, 80, 8080),
    ]
    v = only_rule(smoke_target(multiple), "smoke-target")
    assert "web" in v["message"] and "api" in v["message"]


def test_smoke_target_http_probe_without_service_is_not_backed():
    rendered = [deployment("web", [http_container("web")])]
    v = only_rule(smoke_target(rendered), "smoke-target")
    assert "web" in v["message"]


def test_smoke_target_passes_on_exactly_one_service_backed_http_target():
    rendered = [
        deployment("web", [http_container("web"), exec_container("worker")]),
        service("web", {"app": "web"}, 80, 8080),
    ]
    assert smoke_target(rendered) == []


# --- ship-set invariant (S \ D must be a subset of B) ---------------------------


def load_fixture_chart(fixture: str) -> tuple[dict, list[dict]]:
    """Compose doc + rendered chart docs for a bake fixture (real helm)."""
    import yaml

    root = FIXTURES / fixture
    compose = yaml.safe_load((root / "docker-compose.yml").read_text())
    return compose, render_chart(root / "chart")


def test_ship_set():
    """The committed violation fixture blocks naming the offending image."""
    compose, rendered = load_fixture_chart("ship-set-violation")
    v = only_rule(ship_set(compose, classify(compose), rendered), "ship-set")
    assert "registry.example/ghost:9.9.9" in v["message"]


def test_ship_set_match_passes():
    """Chart image matching a declared dependency by repository AND
    chart-tag passes; built tags pass (AC-16 pass path)."""
    compose, rendered = load_fixture_chart("n3-local-profile")
    assert ship_set(compose, classify(compose), rendered) == []


def test_ship_set_chart_tag_mismatch_blocks_naming_both_tags():
    """Same repository, bumped chart-side tag: block names both tags (AC-16)."""
    compose, rendered = load_fixture_chart("n3-local-profile")
    rendered.append(
        deployment("bumped", [exec_container("db", "pgvector/pgvector:pg17")])
    )
    v = only_rule(ship_set(compose, classify(compose), rendered), "ship-set")
    assert "pgvector/pgvector:pg17" in v["message"]
    assert "pgvector/pgvector:pg16" in v["message"]


def test_ship_set_checks_init_containers():
    compose, rendered = load_fixture_chart("n3-local-profile")
    workload = next(d for d in rendered if d["kind"] == "Deployment")
    workload["spec"]["template"]["spec"]["initContainers"] = [
        {"name": "init", "image": "registry.example/init:1.0.0"}
    ]
    v = only_rule(ship_set(compose, classify(compose), rendered), "ship-set")
    assert "registry.example/init:1.0.0" in v["message"]


# --- built-unscheduled (warn only) ----------------------------------------------


def test_built_unscheduled():
    """A built-but-unscheduled target warns and never blocks (AC-17)."""
    import yaml

    compose, rendered = load_fixture_chart("n3-local-profile")
    compose["services"]["svc-extra"] = yaml.safe_load(
        "{build: {context: .}, image: 'bake-spike/svc-extra:0.1.0',\n"
        " healthcheck: {test: [CMD, 'true']}}"
    )
    verdicts = built_unscheduled(compose, classify(compose), rendered)
    assert len(verdicts) == 1
    v = verdicts[0]
    assert v["rule_id"] == "built-unscheduled"
    assert v["level"] == "warn"
    assert "bake-spike/svc-extra:0.1.0" in v["message"]


def test_built_unscheduled_silent_when_all_scheduled():
    compose, rendered = load_fixture_chart("n3-local-profile")
    assert built_unscheduled(compose, classify(compose), rendered) == []


# --- smoke resource catalog -----------------------------------------------------


def test_smoke_resource_unknown():
    v = only_rule(
        smoke_resource_unknown("postgres-pgvector,mongo"), "smoke-resource-unknown"
    )
    assert "mongo" in v["message"]


def test_smoke_resource_unknown_passes_on_catalog_and_empty():
    assert smoke_resource_unknown("postgres-pgvector, gateway-crds") == []
    assert smoke_resource_unknown("") == []


# --- caller structure carryover (load-bearing rules only) -----------------------

PINNED_REF = "0" * 40


def caller_yaml(
    ref: str = PINNED_REF,
    secrets: str | dict | None = None,
    with_map: dict | None = None,
) -> str:
    import yaml

    if secrets is None:
        secrets = {
            name: f"${{{{ secrets.{name} }}}}"
            for name in (
                "CGR_PULL_TOKEN",
                "CGR_PULL_USERNAME",
                "IRONBANK_TOKEN",
                "IRONBANK_USERNAME",
            )
        }
    job: dict = {
        "uses": (
            "c3-e/c3cdao-ci-scans/.github/workflows/"
            f"reusable-security-gate.yml@{ref}"
        ),
        "secrets": secrets,
    }
    if with_map is not None:
        job["with"] = with_map
    return yaml.safe_dump(
        {"name": "Security Scan", "on": ["pull_request"], "jobs": {"security-scan": job}}
    )


def lint_caller_file(tmp_path, text: str) -> list[dict]:
    caller = tmp_path / "caller.yml"
    caller.write_text(text)
    return lint_caller_workflow(caller)


def test_gate_ref_pin(tmp_path):
    v = only_rule(lint_caller_file(tmp_path, caller_yaml(ref="main")), "gate-ref-pin")
    assert "@main" in v["message"]


def test_gate_ref_pin_accepts_full_sha(tmp_path):
    assert lint_caller_file(tmp_path, caller_yaml()) == []


def test_no_secrets_inherit(tmp_path):
    verdicts = lint_caller_file(tmp_path, caller_yaml(secrets="inherit"))
    assert [v["rule_id"] for v in verdicts] == ["no-secrets-inherit"]
    assert verdicts[0]["level"] == "block"


def test_missing_secret_map(tmp_path):
    secrets = {"CGR_PULL_TOKEN": "${{ secrets.CGR_PULL_TOKEN }}"}
    verdicts = lint_caller_file(tmp_path, caller_yaml(secrets=secrets))
    assert {v["rule_id"] for v in verdicts} == {"missing-secret-map"}
    named = " ".join(v["message"] for v in verdicts)
    for name in ("CGR_PULL_USERNAME", "IRONBANK_TOKEN", "IRONBANK_USERNAME"):
        assert name in named


def test_unknown_input_rejects_removed_v05_inputs(tmp_path):
    with_map = {
        "scan_image": "app:local",
        "contract_file": "Makefile.ci",
        "require_hardened_bases": True,
    }
    verdicts = lint_caller_file(tmp_path, caller_yaml(with_map=with_map))
    assert {v["rule_id"] for v in verdicts} == {"unknown-input"}
    named = " ".join(v["message"] for v in verdicts)
    assert "removed" in named
    for key in with_map:
        assert key in named


def test_unknown_input_rejects_arbitrary_keys_and_accepts_v06_surface(tmp_path):
    v06 = {
        "compose_file": "docker-compose.yml",
        "image_only": False,
        "chart_path": "chart",
        "values_local": "chart/values-local.yaml",
        "release": "app-ci",
        "namespace": "app-ci",
        "smoke_resources": "postgres-pgvector",
    }
    assert lint_caller_file(tmp_path, caller_yaml(with_map=v06)) == []
    verdicts = lint_caller_file(
        tmp_path, caller_yaml(with_map={**v06, "dockerfile": "x"})
    )
    only_rule(verdicts, "unknown-input")


def test_unreadable_caller_fails_closed(tmp_path):
    only_rule(lint_caller_file(tmp_path, "jobs: [broken\n"), "unreadable-caller")
    # No job uses the gate workflow -> also fail closed.
    import yaml

    doc = {"jobs": {"other": {"uses": "some/other/workflow.yml@" + PINNED_REF}}}
    only_rule(
        lint_caller_file(tmp_path, yaml.safe_dump(doc)), "unreadable-caller"
    )


# --- full pipeline / CLI --------------------------------------------------------


def test_conforming_n3_fixture_passes_full_rule_set(monkeypatch):
    """IG-1 Fixture Conformance Prep: the N=3 fixture yields zero verdicts
    under the complete v0.6 rule set (bake plan is the captured real one)."""
    import json

    import lint_rules.compose as compose_rules

    fixture = FIXTURES / "n3-local-profile"
    plan = json.loads((fixture / "bake-print.json").read_text())
    monkeypatch.setattr(compose_rules, "run_bake_print", lambda path, targets: plan)
    verdicts = convention_verdicts(
        fixture / "docker-compose.yml",
        chart_path=fixture / "chart",
        smoke_resources="postgres-pgvector,gateway-crds",
    )
    assert verdicts == []


def test_convention_verdicts_image_only_skips_chart_render_rules(monkeypatch):
    """image_only: true skips the chart-rendering rules (chart-readiness,
    smoke-target, ship-set, built-unscheduled) — but still enforces
    chart-undeclared (T-12) when a real chart exists in the repo tree."""
    import json

    import lint_rules.compose as compose_rules

    fixture = FIXTURES / "n3-local-profile"
    plan = json.loads((fixture / "bake-print.json").read_text())
    monkeypatch.setattr(compose_rules, "run_bake_print", lambda path, targets: plan)
    verdicts = convention_verdicts(
        fixture / "docker-compose.yml",
        chart_path=fixture / "chart",
        image_only=True,
    )
    only_rule(verdicts, "chart-undeclared")


def test_convention_verdicts_image_only_passes_with_no_chart_anywhere(
    tmp_path, monkeypatch
):
    """image_only: true with no chart anywhere in the repo passes clean —
    the fixture's chart-rendering rules and its new chart-undeclared check
    both stay silent (T-12's non-violation path)."""
    import json
    import shutil

    import lint_rules.compose as compose_rules

    fixture = FIXTURES / "n3-local-profile"
    for name in ("docker-compose.yml", "Dockerfile", ".dockerignore"):
        shutil.copy(fixture / name, tmp_path / name)
    plan = json.loads((fixture / "bake-print.json").read_text())
    monkeypatch.setattr(compose_rules, "run_bake_print", lambda path, targets: plan)
    verdicts = convention_verdicts(
        tmp_path / "docker-compose.yml",
        image_only=True,
        smoke_resources="postgres-pgvector,gateway-crds",
    )
    assert verdicts == []


def test_convention_verdicts_fails_closed_on_missing_compose(tmp_path):
    verdicts = convention_verdicts(tmp_path / "docker-compose.yml")
    only_rule(verdicts, "compose-missing")


def test_main_clean_caller_exits_zero(tmp_path, capsys):
    from lint_caller import main

    caller = tmp_path / "caller.yml"
    caller.write_text(caller_yaml())
    assert main([str(caller)]) == 0
    assert "caller lint clean" in capsys.readouterr().out


def test_main_blocking_caller_exits_one_printing_verdicts(tmp_path, capsys):
    from lint_caller import main

    caller = tmp_path / "caller.yml"
    caller.write_text(caller_yaml(ref="main"))
    assert main([str(caller)]) == 1
    out = capsys.readouterr().out
    assert "gate-ref-pin" in out and "block" in out
