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
    uses: c3-e/c3cdao-ci-scans/.github/workflows/reusable-security-gate.yml@v0.5.0
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
    uses: c3-e/c3cdao-ci-scans/.github/workflows/reusable-security-gate.yml@v0.5.0
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
| `scan_image` | string | `app:local` | Local-daemon tag the primary image is built and scanned under; caller-lint requires it to equal a parsed image string or repository:tag join in the manifest's values_local file (comments ignored). Cluster-smoke kind-loads this tag with pullPolicy: Never. Passed to `make ci-build` as CI_IMAGE_TAG for the primary. |
| `contract_file` | string | `Makefile.ci` | Path (relative to the consumer repo root) of the consumer build-contract Makefile providing the ci-manifest / ci-build / ci-secctx / ci-smoke-env targets. `make ci-manifest` output is the single source of truth for the containers list and chart/health metadata. Start from templates/consumer/Makefile.ci. |
| `builder_image` | string | `cgr.dev/chainguard/python:latest-dev` | Build-stage base image, exported to `make ci-build` as CI_BUILDER_BASE (after hardened-registry failover resolution); consume it as your builder base-image build arg. |
| `runtime_image` | string | `cgr.dev/chainguard/python:latest` | Runtime-stage base image, exported to `make ci-build` as CI_RUNTIME_BASE (after hardened-registry failover resolution); consume it as your runtime base-image build arg. |
| `require_hardened_bases` | boolean | `true` | Hardened-base policy — operator posture decision, not read from a consumer file. true (default): fail the build when neither Chainguard nor Iron Bank credentials are configured. false: warn and build with the consumer-specified bases (pilot escape hatch — the consumer explicitly owns that posture). When false, Vulnerability Scan labels the run as a public-base / consumer-specified-base proxy scan — a green result is not proof the approved production image is clean. |
| `ironbank_registry` | string | `registry1.dso.mil` | Iron Bank registry host used for docker login whenever IRONBANK_* secrets are set (alongside Chainguard when both are configured). Also used when primary-base failover swaps to ironbank_* images (CGR absent, Iron Bank present). Operator decision; defaults to the DoD registry. |
| `ironbank_builder_image` | string | `""` | Optional Iron Bank replacement for builder_image — applied only on primary-base failover (CGR credentials absent AND Iron Bank present). Left empty, the consumer's builder_image passes through. Does not affect whether Iron Bank login runs; login is independent when IRONBANK_* is set. |
| `ironbank_runtime_image` | string | `""` | Optional Iron Bank replacement for runtime_image — applied only on primary-base failover (CGR credentials absent AND Iron Bank present). Left empty, the consumer's runtime_image passes through. Does not affect whether Iron Bank login runs; login is independent when IRONBANK_* is set. |
| `cluster_name` | string | `app-ci` | kind cluster name cluster-smoke creates and loads the image into; operator choice, no consumer-file counterpart. |
| `smoke_secrets` | string | `""` | JSON array (as a string) of Kubernetes Secrets to create in the smoke namespace before helm install — one object per entry: name (DNS-1123 secret name), literals (newline-joined KEY=VALUE string). Use for chart envFrom/secretKeyRef pre-reqs beyond what your `make ci-smoke-env` target provisions. Values are CI fixtures only — never commit real credentials. Default "" creates none. Prefer a multiline YAML '\|' block. |
| `image_only` | boolean | `false` | When true, skip helm-check and cluster-smoke (and omit them from the Security Gate blocking set) — for infra/image-only repos that build and vuln-scan images without a deployable app chart. Default false keeps app callers unchanged (helm + smoke still blocking). |
<!-- END GENERATED: security-gate-inputs -->
