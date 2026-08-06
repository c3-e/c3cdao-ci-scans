# Inputs

Every field the caller passes via `with:` to the reusable security gate,
hand-authored against `workflow_call.inputs` in
`.github/workflows/reusable-security-gate.yml` (the source of truth; the
doc tests cross-check every input and secret name against it).

Since v0.6 the gate derives build facts (images, Dockerfiles, contexts,
build args, smoke target) from your Compose file and Helm chart; see
[CI-CONTRACT.md](CI-CONTRACT.md). The seven inputs that remain are paths
and orchestration knobs, all defaulted: a conforming repository with
default paths passes nothing but secrets.

## Field reference

| Input | Type | Default | Where the value comes from |
| --- | --- | --- | --- |
| `compose_file` | string | `docker-compose.yml` | Path (relative to your repo root) of the canonical Compose file the gate derives build facts from. `docker buildx bake --print` on this file is the published build plan; the plan job annotates it into the BOM and emits the build matrix. |
| `chart_path` | string | `chart` | Path of the deployable Helm chart helm-check lints/templates and cluster-smoke installs. Irrelevant when `image_only` is true. |
| `values_local` | string | `chart/values-local.yaml` | Chart values file for local/CI installs (locally-built image tags, `pullPolicy: Never`). Rendered on top of the chart's defaults by helm-check and cluster-smoke. |
| `release` | string | `app` | Helm release name helm-check templates under and cluster-smoke installs as. |
| `namespace` | string | `app-ci` | Kubernetes namespace cluster-smoke creates and installs the release into. |
| `smoke_resources` | string | `""` | CSV of gate-owned smoke catalog module ids (`postgres-pgvector`, `gateway-crds`) provisioned before helm install. Unknown ids block (`smoke-resource-unknown`). Default provisions none. |
| `image_only` | boolean | `false` | When true, skip helm-check and cluster-smoke (and drop them from the blocking set), for repos that build and scan images without a deployable chart. |

## Secrets

The four registry secrets are the whole secret surface. Pass them
explicitly; `secrets: inherit` only works within one org/enterprise
(across owners it silently passes nothing) and is rejected by the
`no-secrets-inherit` rule.

| Secret | Used by |
| --- | --- |
| `CGR_PULL_TOKEN`, `CGR_PULL_USERNAME` | plan + every build leg: Chainguard (`cgr.dev`) login |
| `IRONBANK_TOKEN`, `IRONBANK_USERNAME` | SonarQube ephemeral + plan/build Iron Bank (`registry1.dso.mil`) login; runs alongside Chainguard when both are set |

Base images, the Iron Bank registry host, and the hardened-base posture
are gate-owned configuration (workflow `env`), not inputs: the gate is
fail-closed: no credential pair means no build.

## Worked example

```yaml
jobs:
  security-scan:  # job id is half of the required check context
    uses: c3-e/c3cdao-ci-scans/.github/workflows/reusable-security-gate.yml@<40-hex sha>  # v0.6.0
    with:
      compose_file: docker-compose.yml
      chart_path: chart
      values_local: chart/values-local.yaml
      release: app
      namespace: app-ci
      smoke_resources: postgres-pgvector,gateway-crds
    secrets:
      CGR_PULL_TOKEN: ${{ secrets.CGR_PULL_TOKEN }}
      CGR_PULL_USERNAME: ${{ secrets.CGR_PULL_USERNAME }}
      IRONBANK_TOKEN: ${{ secrets.IRONBANK_TOKEN }}
      IRONBANK_USERNAME: ${{ secrets.IRONBANK_USERNAME }}
```

Multi-image repositories declare nothing extra here: every non-local
Compose `build:` service becomes its own build + scan matrix leg, so
frontend, backend, and sidecar images enter the scan set by being declared
where local development already declares them.

## Removed inputs (v0.5 → v0.6 migration)

The unknown-input lint rule rejects each of these by name; delete them
from your caller. Their jobs moved into the derivation or into gate-owned
configuration.

| Removed input | Replaced by |
| --- | --- |
| `contract_file` | removed: no contract makefile exists; build facts are derived from Compose + Dockerfiles + chart |
| `scan_image` | removed: no primary image; every non-local Compose build service is scanned as its own matrix leg |
| `require_hardened_bases` | removed: hardened bases are always required (fail-closed gate posture) |
| `builder_image`, `runtime_image` | removed: the gate neither supplies nor overrides base-image args; base images are the consumer Dockerfile's own choice |
| `ironbank_registry`, `ironbank_builder_image`, `ironbank_runtime_image` | removed: gate-owned registry/failover configuration |
| `cluster_name` | removed: gate-owned kind cluster name |
| `smoke_secrets` | removed: smoke prerequisites come from the gate-owned `smoke_resources` catalog (fixture Secrets included, e.g. `app-database-url`) |
