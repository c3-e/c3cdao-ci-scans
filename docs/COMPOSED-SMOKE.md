# Composed Multi-Pilot Smoke Test: Inputs

`composed-smoke.yml` is a separate reusable workflow from
[`publish-staging-chart.yml`](PUBLISH-STAGING-CHART.md) and the
[Reusable Security Gate](INPUTS.md). It differs in trigger model (manual
dry-run or a caller-owned PR/merge trigger, never a same-run build) and
in consumption shape: it installs N pilot subcharts together against
artifacts a prior run published, rather than one chart against images
built this run. It exists as its own workflow rather than a
`reusable-security-gate.yml` extension because it composes multiple
pilots' previously-published artifacts together, not a single pilot's
from-source build.

For an umbrella repo's consumer-side wiring, including the
`composed-smoke-caller.yml` caller file, how the `pilots:` JSON input
derives from `Chart.yaml`, and the full onboarding sequence, see that
umbrella's own onboarding runbook.

## Trigger

`workflow_call` only. This workflow takes no position on when it runs: a
caller wires it to a `workflow_dispatch` manual dry-run, a
`pull_request: branches: [ci-scans]` trigger, or both (the umbrella's
`composed-smoke-caller.yml` uses both during this feature's development
window: manual dry-run first, wired to a real PR trigger only once the
dry-run proves the mechanics end-to-end for every composed pilot).

## Field reference

| Input | Type | Default | Where the value comes from |
| --- | --- | --- | --- |
| `pilots` | string (JSON) | *(required)* | JSON array, one entry per pilot subchart to compose: `{"name","chart_ref","images":[{"name","values_path"}]}`. `chart_ref` is the exact `oci://ghcr.io/c3-e/charts-staging/<pilot>:<tag>` ref already pinned in the caller's `Chart.yaml`; this workflow does not decide pilot versions, the caller's `Chart.yaml` already did. Each `images[]` entry's `name` is the `<image-name>` path segment under `images-staging/<pilot>/<image-name>` (see [PUBLISH-STAGING-CHART.md](PUBLISH-STAGING-CHART.md)); the image ref itself is derived by this workflow as `ghcr.io/c3-e/images-staging/<pilot>/<image-name>:<tag>`, reusing the same `<tag>` already embedded in `chart_ref` (every artifact from one merge shares one salted tag, so there's no separate lookup table). `values_path` is the dotted values key (a `{repository,tag}` parent) the caller's `helm install` overrides via `--set-string`, e.g. `rms-copilot.fullstack-template.backend.image`. |
| `umbrella_values` | string | `values.yaml` | Path (repo-root-relative, in the caller's tree) to the values file layered on top of the chart's defaults before installing. |
| `namespace` | string | `umbrella-ci` | Namespace this workflow creates (if missing) and installs the composed release into. |
| `smoke_resources` | string (CSV) | `postgres-pgvector,gateway-crds` | Gate-owned smoke-catalog module ids (`scripts/lib/smoke_catalog/*.yaml`), the same catalog `reusable-security-gate.yml`'s `cluster-smoke` job already owns, reused directly rather than forked into a second copy. The default covers the umbrella's two known backing-service needs: a shared Postgres fixture (every fullstack-template pilot composes its own `DATABASE_URL` against it, ADR-08) and the Gateway API core CRDs every pilot's chart-emitted `HTTPRoute` needs present to install cleanly. |

## Secrets

None required. This workflow only reads (`packages: read`): it pulls
already-published `charts-staging/*` and `images-staging/*` staging
artifacts and never builds or publishes. GHCR authentication for the
image pulls uses the calling job's `GITHUB_TOKEN`, Actions-native, not a
personal PAT.

## Mechanics (what the one job actually does)

1. Checks out the caller's tree (the umbrella chart lives there).
2. Checks out `c3-e/c3cdao-ci-scans` itself into `.ci-scans` (same
   cross-repo pattern `reusable-security-gate.yml`'s `plan`/`build`/
   `cluster-smoke` jobs use): the smoke-catalog manifests and
   `derive_smoke_target.py` live in the gate repo, not the caller's.
3. `helm pull <chart_ref> --untar` for every `pilots[]` entry, into the
   caller's `charts/<pilot>`, the same OCI-pull mechanism
   `hack/test-pilot-pin.sh --oci-ref` already proves in the umbrella
   repo. It untars rather than leaving a bare `.tgz`, so the chart
   resolves as an ordinary vendored subchart directory.
4. `docker pull` every declared image ref, then `kind load docker-image`,
   the same technique `reusable-security-gate.yml`'s `cluster-smoke` job
   already uses for images built earlier in that run, just sourced from
   a registry pull here instead of a same-run build.
5. Creates a `kind` cluster (`helm/kind-action`, same pinned SHA
   `reusable-security-gate.yml` already uses) and provisions the
   `smoke_resources` catalog modules into it, gated on readiness, before
   any `helm install`: identical `provision_module()` logic to
   `cluster-smoke`'s own step.
6. `helm install`s the caller's own umbrella chart with one
   `--set-string {repository,tag,pullPolicy}` triple per declared image,
   derived from each `pilots[].images[].values_path`.
7. Partitions the composed pilots by whether each one's rendered
   subchart carries a `helm.sh/hook: test` resource (see [Helm test hook
   migration](#helm-test-hook-migration-temporary) below).
8. Health-checks every composed pilot, not just one:
   - Hook-bearing pilots are covered by one release-wide `helm test
     umbrella-ci -n <namespace> --logs` run. Helm runs every
     hook-annotated resource across the release in a single invocation,
     regardless of which pilot(s) declared them, so this happens once
     per run rather than once per hook-bearing pilot.
   - Hook-less pilots keep the pre-migration path: it renders that
     pilot's vendored subchart alone and reuses `smoke_candidates()`
     (the same underlying function `derive_smoke_target.py` wraps,
     called directly here since a multi-component pilot commonly yields
     more than the CLI's "exactly one" constraint) to find every
     Service-backed HTTP readiness target it exposes, then `kubectl
     port-forward` + `curl`s each one. It's the same probe mechanic
     `cluster-smoke` runs, just per pilot here instead of once per
     caller.
9. Emits a per-pilot job-summary table (pilot, chart ref, result,
   probe), matching this repo's established job-summary convention
   (`publish-staging-chart.yml`'s own summary block), not a single
   aggregate pass/fail line. Hook-bearing pilots are recorded as
   `OK (helm test)` / `FAIL (helm test)`, not re-probed.

## Helm test hook migration (temporary)

**This partition is temporary fleet-migration scaffolding.** It exists
only because not every onboarded pilot has adopted a `helm.sh/hook: test`
resource yet. `reusable-security-gate.yml`'s own `cluster-smoke` job is
going through the identical migration (see that workflow's `hook-detect`
step), and `scripts/lib/lint_rules/chart.py`'s `smoke_target` rule
carries the matching exemption (see
[CI-CONTRACT.md](CI-CONTRACT.md#rule-smoke-target)). This fallback will
be removed, along with the hook-less per-target loop and the partition
step, once every pilot chart this workflow composes adopts a `helm test`
hook.

## Worked example

```yaml
name: Composed Smoke (all pilots)

on:
  pull_request:
    branches: [ci-scans]
  workflow_dispatch:

permissions:
  contents: read
  packages: read

jobs:
  composed-smoke:
    uses: c3-e/c3cdao-ci-scans/.github/workflows/composed-smoke.yml@<40-hex sha>
    with:
      pilots: |
        [
          {
            "name": "rms-copilot",
            "chart_ref": "oci://ghcr.io/c3-e/charts-staging/rms-copilot:0.0.0-mech.102.b8544c4",
            "images": [
              {"name": "backend", "values_path": "rms-copilot.fullstack-template.backend.image"},
              {"name": "psp7-gateway-frontend", "values_path": "rms-copilot.fullstack-template.frontend.image"}
            ]
          }
        ]
```

Produces a `kind` cluster with `rms-copilot`'s frontend + backend
Deployments running the exact images `c3cdao-geoint#94`'s merge
published, health-checked through the umbrella release's rendered
Service. The run itself is the evidence: a shareable GHA run URL instead
of a laptop screenshot.

## Failure behavior

Any pulled chart/image that fails to resolve, any smoke-catalog module
that fails readiness, a failed `helm install --wait`, a failed
`helm test` run (for hook-bearing pilots), or any hook-less pilot's
health-check returning a non-200 fails the job closed, visible as a red
step on the run's Checks tab. `job summary` still renders a per-pilot
table on `if: always()`, so a partial failure (e.g. pilot 3 of 5 failing
its probe) stays legible without reading the full step log.
