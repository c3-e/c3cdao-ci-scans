"""Unit tests for the extras-values-mismatch rule (extras tag pinning)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

from lint_caller import check_extras_values


def _image(name: str, **extra) -> dict:
    return {
        "name": name,
        "dockerfile": f"containers/{name}/Dockerfile",
        "context": ".",
        **extra,
    }


def _manifest(images: list[dict]) -> dict:
    return {
        "images": images,
        "chart": {
            "path": "helm/app",
            "values": "helm/app/values.yaml",
            "values_local": "values-local.yaml",
            "release": "app-ci",
            "namespace": "app-ci",
        },
        "health": {"path": "/health", "port": "8000", "workload_match": "backend"},
    }


def _run(tmp_path: Path, values_text: str, images: list[dict]) -> list[str]:
    (tmp_path / "values-local.yaml").write_text(values_text)
    return check_extras_values({}, {}, tmp_path, _manifest(images))


def test_extra_default_tag_pinned(tmp_path):
    values = "backend:\n  image: app:local\nworker:\n  image: worker:local\n"
    assert _run(tmp_path, values, [_image("backend"), _image("worker")]) == []


def test_extra_default_tag_missing(tmp_path):
    values = "backend:\n  image: app:local\n"
    violations = _run(tmp_path, values, [_image("backend"), _image("worker")])
    assert len(violations) == 1
    assert "extra 'worker' tag 'worker:local'" in violations[0]
    assert "extras-values-mismatch" in violations[0]


def test_extra_image_key_honored(tmp_path):
    values = "frontend:\n  image: gateway-frontend:local\n"
    images = [_image("backend"), _image("frontend", image="gateway-frontend:local")]
    assert _run(tmp_path, values, images) == []


def test_extra_image_key_mismatch(tmp_path):
    values = "frontend:\n  image: frontend:local\n"
    images = [_image("backend"), _image("frontend", image="gateway-frontend:local")]
    violations = _run(tmp_path, values, images)
    assert len(violations) == 1
    assert "'gateway-frontend:local'" in violations[0]


def test_no_extras_is_noop(tmp_path):
    assert _run(tmp_path, "backend:\n  image: app:local\n", [_image("backend")]) == []


def test_manifest_unavailable_skips(tmp_path):
    assert check_extras_values({}, {}, tmp_path, None) == []


if __name__ == "__main__":
    raise SystemExit(pytest.main(["-q", __file__]))
