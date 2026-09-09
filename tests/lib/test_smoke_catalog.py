"""Contract tests for the gate-owned smoke catalog modules.

scripts/lib/smoke_catalog/*.yaml are idempotent k8s manifests applied
into the smoke namespace before helm install: fixture credentials only,
digest-pinned images, a readiness gate, restricted-PSS posture (the
gate's own helm-check bar applies to gate-owned pods too), and the
secret-naming convention (`app-database-url` -> `DATABASE_URL`).
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

import assert_restricted_pss  # noqa: E402

CATALOG = REPO_ROOT / "scripts" / "lib" / "smoke_catalog"
POSTGRES = CATALOG / "postgres_pgvector.yaml"
GATEWAY = CATALOG / "gateway_crds.yaml"


def docs(path: Path) -> list[dict]:
    return [d for d in yaml.safe_load_all(path.read_text()) if isinstance(d, dict)]


def by_kind(path: Path, kind: str) -> list[dict]:
    return [d for d in docs(path) if d.get("kind") == kind]


# --- catalog <-> lint whitelist invariant ----------------------------------------


def test_smoke_catalog_whitelist_maps_one_to_one_onto_module_files():
    """Every SMOKE_CATALOG id has a manifest and every manifest is
    whitelisted; drift in either direction ships an unusable module."""
    from lint_rules.chart import SMOKE_CATALOG

    files = {p.stem for p in CATALOG.glob("*.yaml")}
    assert {m.replace("-", "_") for m in SMOKE_CATALOG} == files


# --- module shape: idempotent kubectl apply -------------------------------------


def test_every_doc_is_named_and_kinded_for_idempotent_apply():
    for module in (POSTGRES, GATEWAY):
        parsed = docs(module)
        assert parsed, f"{module.name}: no documents"
        for doc in parsed:
            assert doc.get("kind"), f"{module.name}: document without kind"
            assert (doc.get("metadata") or {}).get("name"), (
                f"{module.name}: {doc.get('kind')} without metadata.name "
                "(generateName would break idempotent re-apply)"
            )


def test_module_resources_carry_the_readiness_wait_label():
    """The workflow's Ready gate selects pods by app.kubernetes.io/name
    == the module id (dashes, not the filename's underscores)."""
    sts = by_kind(POSTGRES, "StatefulSet")
    assert len(sts) == 1
    template = sts[0]["spec"]["template"]
    labels = template["metadata"]["labels"]
    assert labels["app.kubernetes.io/name"] == "postgres-pgvector"
    assert sts[0]["spec"]["selector"]["matchLabels"][
        "app.kubernetes.io/name"
    ] == "postgres-pgvector"


# --- postgres-pgvector: digest pin, fixture creds, readiness, PSS ---------------


def test_pgvector_image_is_digest_pinned():
    (sts,) = by_kind(POSTGRES, "StatefulSet")
    containers = sts["spec"]["template"]["spec"]["containers"]
    assert len(containers) == 1
    image = containers[0]["image"]
    assert image.startswith("pgvector/pgvector:pg16@sha256:"), image


def test_pgvector_secret_follows_app_database_url_convention():
    secrets = by_kind(POSTGRES, "Secret")
    assert len(secrets) == 1
    secret = secrets[0]
    assert secret["metadata"]["name"] == "app-database-url"
    url = secret["stringData"]["url"]
    assert url.startswith("postgresql://")
    # Fixture credentials only — greppable marker, never a real secret.
    assert "fixture-only" in url


def test_pgvector_statefulset_has_readiness_gate():
    (sts,) = by_kind(POSTGRES, "StatefulSet")
    (container,) = sts["spec"]["template"]["spec"]["containers"]
    probe = container.get("readinessProbe") or {}
    assert probe.get("exec"), "pg_isready exec probe expected"
    assert "pg_isready" in " ".join(probe["exec"]["command"])


def test_pgvector_service_routes_to_postgres():
    (svc,) = by_kind(POSTGRES, "Service")
    assert svc["spec"]["selector"]["app.kubernetes.io/name"] == "postgres-pgvector"
    ports = svc["spec"]["ports"]
    assert any(p.get("port") == 5432 for p in ports)


def test_pgvector_pod_passes_restricted_pss(capsys):
    """The gate's own bundled restricted-PSS assertion, applied to the
    gate's own module — same bar consumers' rendered charts must meet."""
    assert assert_restricted_pss.check(str(POSTGRES)) == 0, capsys.readouterr().out


def test_pgvector_root_filesystem_read_only_with_writable_volumes():
    (sts,) = by_kind(POSTGRES, "StatefulSet")
    pod = sts["spec"]["template"]["spec"]
    (container,) = pod["containers"]
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    mounts = {m["mountPath"] for m in container.get("volumeMounts") or []}
    # postgres must be able to write PGDATA, its socket dir, and /tmp.
    assert {"/var/lib/postgresql/data", "/var/run/postgresql", "/tmp"} <= mounts


# --- gateway-crds: CRD-only apply module -----------------------------------------


def test_gateway_module_contains_only_crds():
    parsed = docs(GATEWAY)
    assert parsed
    assert all(d["kind"] == "CustomResourceDefinition" for d in parsed)
    assert all(d["apiVersion"] == "apiextensions.k8s.io/v1" for d in parsed)


def test_gateway_crds_carry_protected_group_approval_annotation():
    """gateway.networking.k8s.io is protected: the API server rejects CRDs
    without api-approved.kubernetes.io (KEP-1111); these copies declare
    themselves unapproved rather than borrowing the upstream approval URL."""
    for doc in docs(GATEWAY):
        annotation = doc["metadata"]["annotations"]["api-approved.kubernetes.io"]
        assert annotation.startswith("unapproved"), doc["metadata"]["name"]


def test_gateway_crds_cover_the_gateway_api_core_kinds():
    names = {d["metadata"]["name"] for d in docs(GATEWAY)}
    assert {
        "gatewayclasses.gateway.networking.k8s.io",
        "gateways.gateway.networking.k8s.io",
        "httproutes.gateway.networking.k8s.io",
    } <= names
