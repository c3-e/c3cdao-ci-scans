"""Unit tests for the chart-derived smoke target (scripts/lib/derive_smoke_target.py).

T-7 AC-2 (zero/two-candidate failure paths name the candidates) plus the
ticket's test-file spec: happy path, non-HTTP probe, no Service backing,
image_only skip. Rendered-chart inputs are authored inline as parsed
documents (same convention as tests/lib/test_lint_rules.py).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

from derive_smoke_target import derive_smoke_target  # noqa: E402


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


# --- happy path: exactly one Service-backed HTTP target ------------------------


def test_one_target_derives_service_port_and_path():
    rendered = [
        deployment("web", [http_container("web"), exec_container("worker")]),
        service("web", {"app": "web"}, 80, 8080),
    ]
    assert derive_smoke_target(rendered) == {
        "workload": "Deployment/web",
        "container": "web",
        "service": "web",
        "port": 80,
        "path": "/healthz",
    }


def test_one_target_via_cli_prints_json(tmp_path, capsys):
    import json

    import yaml

    from derive_smoke_target import main

    rendered = tmp_path / "rendered-chart.yaml"
    rendered.write_text(
        yaml.safe_dump_all(
            [
                deployment("web", [http_container("web")]),
                service("web", {"app": "web"}, 80, 8080),
            ]
        )
    )
    assert main([str(rendered)]) == 0
    target = json.loads(capsys.readouterr().out)
    assert target["service"] == "web"
    assert target["port"] == 80
    assert target["path"] == "/healthz"


# --- non-HTTP probe / no Service backing (zero-candidate variants) --------------


def test_non_http_probe_only_errors_as_zero_candidates():
    rendered = [
        deployment("worker", [exec_container("worker")]),
    ]
    with pytest.raises(SystemExit) as exc:
        derive_smoke_target(rendered)
    assert "no container declares an httpGet readinessProbe" in str(exc.value)


def test_http_probe_without_service_backing_names_the_unbacked_candidate():
    rendered = [deployment("web", [http_container("web")])]
    with pytest.raises(SystemExit) as exc:
        derive_smoke_target(rendered)
    message = str(exc.value)
    assert "no Service routes" in message
    assert "Deployment/web container 'web'" in message


# --- image_only skip -------------------------------------------------------------


def test_image_only_skips_derivation_via_cli(tmp_path, capsys):
    import json

    from derive_smoke_target import main

    # No rendered chart needs to exist: image_only makes no chart claim.
    assert main([str(tmp_path / "absent.yaml"), "--image-only"]) == 0
    assert json.loads(capsys.readouterr().out) == {"skipped": "image_only"}



def test_zero_targets_errors_without_any_http_probe():
    rendered = [
        deployment("web", [exec_container("web")]),
        service("web", {"app": "web"}, 80, 8080),
    ]
    with pytest.raises(SystemExit) as exc:
        derive_smoke_target(rendered)
    message = str(exc.value)
    assert "smoke-target" in message
    assert "no " in message.lower()


def test_two_targets_errors_naming_both_candidates():
    rendered = [
        deployment("web", [http_container("web")]),
        deployment("api", [http_container("api")], labels={"app": "api"}),
        service("web", {"app": "web"}, 80, 8080),
        service("api", {"app": "api"}, 80, 8080),
    ]
    with pytest.raises(SystemExit) as exc:
        derive_smoke_target(rendered)
    message = str(exc.value)
    assert "smoke-target" in message
    assert "web" in message and "api" in message
