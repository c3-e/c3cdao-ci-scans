# Inputs

Every field the caller passes via `with:` to the reusable security gate. The
table below is generated from `workflow_call.inputs` by
`scripts/lib/extract_contract.py` and is the published contract — never
hand-edit between the markers; CI rejects drift. Edit the preamble and worked
examples above the markers freely; the generator preserves them.

Since v0.5.0 the consumer build contract is the **only** build path: build
knowledge (Dockerfiles, contexts, build args, chart location, health probe)
lives in your contract makefile (`contract_file`, default `Makefile.ci`), not
in `with:` inputs — see [CI-CONTRACT.md](CI-CONTRACT.md). The inputs that
remain are orchestration and policy knobs.

## Worked examples

The examples pass the four gate secrets explicitly because `secrets: inherit`
only works within the same org/enterprise (it silently passes nothing across
owners) and caller-lint rejects it (`no-secrets-inherit`).

### Single-image default

The common case: one backend image, one chart, everything declared by
`make ci-manifest`. Omit anything you keep at its default.

```yaml
jobs:
  security-scan:
    uses: c3-e/c3cdao-ci-scans/.github/workflows/reusable-security-gate.yml@v0.5.1
    with:
      scan_image: app:local
      contract_file: Makefile.ci
    secrets:
      CGR_PULL_TOKEN: ${{ secrets.CGR_PULL_TOKEN }}
      CGR_PULL_USERNAME: ${{ secrets.CGR_PULL_USERNAME }}
      IRONBANK_TOKEN: ${{ secrets.IRONBANK_TOKEN }}
      IRONBANK_USERNAME: ${{ secrets.IRONBANK_USERNAME }}
```

### Multi-container

Extras (workers, frontends, sidecars) are declared in the manifest, not the
caller: add entries to `ci-manifest`'s `images[]` (images[0] stays the
primary) and teach `ci-build IMAGE=<name>` to build each one. Cluster-smoke
kind-loads every built extras tag before `helm install`, so charts that
schedule them with `pullPolicy: Never` do not hit `ErrImageNeverPull` — set
each entry's `image` key to match the chart's values-local tag.

Declare **self-authored, gate-reachable** images only (bases pulled from
`cgr.dev` and/or `registry1.dso.mil`). Do not use extras to "scan" third-party
DB/base images or private-mirror artifacts the runner cannot pull — those
produce low-signal proxy scans, not approved-image attestation.

### Smoke Secrets (`smoke_secrets`)

Charts that reference Kubernetes Secrets via `envFrom` / `secretKeyRef` need
those objects present before `helm install`. Your `make ci-smoke-env` target
is the first place for these; `smoke_secrets` covers caller-side extras. Pass
CI fixture literals (never real credentials) as a JSON array in a multiline
`|` block. Each object has `name` (Secret metadata.name) and `literals`
(newline-joined `KEY=VALUE`).

```yaml
jobs:
  security-scan:
    uses: c3-e/c3cdao-ci-scans/.github/workflows/reusable-security-gate.yml@v0.5.1
    with:
      scan_image: app:local
      smoke_secrets: |
        [
          {
            "name": "aca-database-url",
            "literals": "DATABASE_URL=postgresql://postgres:postgres@app-postgres:5432/appdb"
          }
        ]
    secrets:
      CGR_PULL_TOKEN: ${{ secrets.CGR_PULL_TOKEN }}
      CGR_PULL_USERNAME: ${{ secrets.CGR_PULL_USERNAME }}
      IRONBANK_TOKEN: ${{ secrets.IRONBANK_TOKEN }}
      IRONBANK_USERNAME: ${{ secrets.IRONBANK_USERNAME }}
```

### Non-default ports and health routes

Ports and health probes are manifest data, not inputs: set `health.port` /
`health.path` / `health.workload_match` in your `ci-manifest` output (the
reference `Makefile.ci` exposes them as `APP_PORT` / `HEALTH_PATH` /
`WORKLOAD_MATCH` variables).

## Scan boundary

The gate builds and vulnerability-scans the image **as built with bases the
runner can pull** (`cgr.dev` and/or `registry1.dso.mil`). Approved-image /
OS-layer scanning for private-mirror or entitlement-unreachable bases is **out
of scope** here — that stays with the consumer pipeline (IL5 / Game Warden /
etc.).

When `require_hardened_bases` is `false` (or bases are overridden to public
substitutes), a green Vulnerability Scan is **not** proof the approved
production image is clean; the job labels that run as a **proxy scan**.

## Field reference

<!-- BEGIN GENERATED: security-gate-inputs -->
| Input | Type | Default | Where the value comes from |
| --- | --- | --- | --- |
| `compose_file` | string | `docker-compose.yml` | Path (relative to the consumer repo root) of the canonical Compose file the gate derives build facts from (v0.6). `docker buildx bake --print` on this file is the published build plan; the plan job annotates it into the BOM and emits the build matrix from it. |
| `chart_path` | string | `chart` | Path (relative to the consumer repo root) of the deployable Helm chart helm-check lints/templates and cluster-smoke installs. Required for chart consumers; irrelevant when image_only is true. |
| `values_local` | string | `chart/values-local.yaml` | Path (relative to the consumer repo root) of the chart values file for local/CI installs (locally-built image tags, pullPolicy: Never). Rendered by helm-check and cluster-smoke on top of the chart's default values. |
| `release` | string | `app` | Helm release name helm-check templates under and cluster-smoke installs as. |
| `namespace` | string | `app-ci` | Kubernetes namespace cluster-smoke creates and installs the release into. |
| `smoke_resources` | string | `""` | CSV of gate-owned smoke catalog module ids (e.g. postgres-pgvector,gateway-crds) cluster-smoke provisions before helm install. Unknown ids are blocked by the smoke-resource-unknown lint rule. Default "" provisions none. (Wired by T-7.) |
| `image_only` | boolean | `false` | When true, skip helm-check and cluster-smoke (and omit them from the Security Gate blocking set) — for infra/image-only repos that build and vuln-scan images without a deployable app chart. Default false keeps app callers unchanged (helm + smoke still blocking). |
<!-- END GENERATED: security-gate-inputs -->
