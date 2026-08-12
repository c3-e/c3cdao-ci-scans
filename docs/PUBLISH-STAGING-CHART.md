# Publish Staging Chart — Inputs

`publish-staging-chart.yml` is a separate reusable workflow from the
[Reusable Security Gate](INPUTS.md) — different trigger model (merge-only,
side-effecting) and different side-effect profile (registry writes vs.
read-only scans). See [CI-CONTRACT.md](CI-CONTRACT.md) for why the two are
not folded together.

For the umbrella (`c3-e/c3cdao-apps`) consumer-side chart-shape contract and
the full pilot onboarding sequence (including wiring this workflow into a
new pilot's own fork repo), see `PILOT-ONBOARDING-RUNBOOK.md` in that repo.

## Trigger

`pull_request`, `types: [closed]`, gated on
`github.event.pull_request.merged == true`. An ordinary push to an open PR,
or a close without merge, produces no artifact. The base branch is
intentionally **unrestricted** (any branch, not just `main`) — fork PRs in
this org's stacked-PR pattern merge into intermediate branches (e.g.
`ci-scans`) before `main`, and restricting the trigger to `main` would
reproduce the exact pre-merge composability gap this workflow exists to
close.

## Field reference

| Input | Type | Default | Where the value comes from |
| --- | --- | --- | --- |
| `chart_path` | string | *(required)* | Path (relative to the calling repo root) of the Helm chart to package and push on merge. The pilot name (used in the staging path and pin naming convention) is derived as this path's basename. |
| `publish_images` | boolean | `false` | Deferred slot for a future image-publish job. Default `false` keeps this input inert — no image-publish logic executes yet. When a future caller sets this `true`, the image-publish job additionally requires the merge's base branch to be `ci-scans` or `main` (narrower than the chart trigger, since image publishes are a heavier, more security-sensitive write). |
| `images` | string (JSON) | `"[]"` | JSON array of image build tuples to publish when `publish_images` is `true`: `{"name","dockerfile","context","build_args"?}`. `name` becomes the `<image-name>` path segment (see [Output](#output) below); `dockerfile`/`context` are passed straight through to `docker/build-push-action`'s `file:`/`context:` inputs. `build_args` is **optional** — a flat JSON object of `{"KEY":"value"}` string pairs, for pilots whose Dockerfile is a shared/generic template parameterized per-app (e.g. `cra`'s `aca-backend`/`aca-frontend`, built from the shared `containers/fullstack-backend`/`containers/fullstack-frontend` engine Dockerfiles via `APP_PATH`/`APP_PACKAGE`/`APP_MODULE`/etc.). Tuples that need no build args can omit the field entirely — it is not required to pass `{}` explicitly. Ignored when `publish_images` is `false`. |
| `require_hardened_bases` | boolean | `false` | Set `true` if any declared image's Dockerfile `FROM`s a hardened base — Chainguard (`cgr.dev`) and/or Iron Bank (`registry1.dso.mil`) — and needs the corresponding credential secret pair to pull it during build. Passed straight through to this repo's own [`hardened-registry-login`](../.github/actions/hardened-registry-login/action.yml) composite action's `require-hardened-bases` input — the SAME shared mechanism `reusable-security-gate.yml`'s `plan`/`build` jobs already use, reused here rather than a second, narrower login step. Fails closed (job errors) when `true` and neither credential pair is configured; when `false` (default), builds proceed on the Dockerfile's own declared bases with no hardened-registry login attempt. (Renamed from this input's earlier, Chainguard-only `cgr_pull_required` name once the per-repo survey found several pilots — `geoint`, `pipeassist`, `dtic`'s fallback path — need Iron Bank instead of or in addition to Chainguard.) |

**Cross-repo gotcha (worth checking before filling in `images:` for any pilot):**
some pilots maintain multiple wrapper-chart copies (e.g. `c3cdao-cra` has both
an older `helm/aca` and the actually-consumed `helm/contract-automation`).
Always source image build coordinates (Dockerfile paths, build contexts,
build args) from the chart the umbrella's own `Chart.yaml` actually depends
on — confirm which one that is via that pilot repo's own
`publish-staging-chart-caller.yml`'s `chart_path` input, not by guessing from
directory names. A wrong guess here silently builds/publishes images for a
chart nobody consumes.

## Secrets

None required for the base case. Authentication for the chart-publish job is
the calling job's own `GITHUB_TOKEN` with `permissions: packages: write` —
Actions-native, not a personal PAT (a personal PAT lacks `write:packages` and
requires an interactive scope grant, which isn't viable for CI). The
image-publish job (`publish-images-deferred`) uses the same `GITHUB_TOKEN`
for its GHCR login and additionally accepts four **optional**
`workflow_call` secrets, only needed when `require_hardened_bases: true` —
one credential pair per hardened registry, mirroring exactly what
`reusable-security-gate.yml`'s own callers already configure for the same
underlying `hardened-registry-login` composite action, so a repo that has
already configured these for the security gate needs no new secret to also
use them here:

| Secret | Required | Purpose |
| --- | --- | --- |
| `CGR_PULL_TOKEN` | Only if `require_hardened_bases: true` and the image(s) need Chainguard | Chainguard (`cgr.dev`) registry pull token. |
| `CGR_PULL_USERNAME` | Only if `require_hardened_bases: true` and the image(s) need Chainguard | Chainguard (`cgr.dev`) registry pull username. |
| `IRONBANK_TOKEN` | Only if `require_hardened_bases: true` and the image(s) need Iron Bank | Iron Bank (`registry1.dso.mil`) pull token — e.g. `geoint`'s backend/frontend, `pipeassist`'s backend, `dtic`'s fallback path. |
| `IRONBANK_USERNAME` | Only if `require_hardened_bases: true` and the image(s) need Iron Bank | Iron Bank (`registry1.dso.mil`) pull username. |

Both pairs may be configured at once (a repo whose images span both
registries builds in a single run); with neither configured,
`require_hardened_bases: true` fails the job closed rather than silently
building on unauthenticated pulls.

## Output

Chart artifact:

```
oci://ghcr.io/c3-e/charts-staging/<pilot>:0.0.0-mech.<pr-number>.<short-sha>
```

Image artifacts (one per `images[]` tuple, only when `publish_images: true`):

```
ghcr.io/c3-e/images-staging/<pilot>/<image-name>:0.0.0-mech.<pr-number>.<short-sha>
```

Unlike `helm push` (which always appends the chart's own name as an extra
path component — see the comment above), `docker buildx build --push` does
**not** infer or append any path segment: the destination tag the job
constructs is the full, exact path, including both `<pilot>` and
`<image-name>`.

This tag/path shape is intentionally **not** a legal ascending SemVer
release: `0.0.0-mech.*` cannot be mistaken for, or collide with, a real
release tag, and `charts-staging/`/`images-staging/` are distinct registry
namespaces from any future real publish target. These are pre-merge test
artifacts, not releases.

## Worked example — chart only

```yaml
jobs:
  publish-staging-chart:
    if: github.event.pull_request.merged == true
    uses: c3-e/c3cdao-ci-scans/.github/workflows/publish-staging-chart.yml@<40-hex sha>  # v0.1.0
    with:
      chart_path: helm/rms-copilot
```

## Worked example — chart + images

```yaml
jobs:
  publish-staging-chart:
    if: github.event.pull_request.merged == true
    uses: c3-e/c3cdao-ci-scans/.github/workflows/publish-staging-chart.yml@<40-hex sha>
    with:
      chart_path: helm/rms-copilot
      publish_images: true
      images: |
        [
          {"name": "frontend", "dockerfile": "Dockerfile.frontend", "context": "."},
          {"name": "backend", "dockerfile": "Dockerfile.backend", "context": "."}
        ]
```

Produces, from one merge (PR `#94`, merge commit `c6a53e6...`):

```
oci://ghcr.io/c3-e/charts-staging/rms-copilot:0.0.0-mech.94.c6a53e6
ghcr.io/c3-e/images-staging/rms-copilot/frontend:0.0.0-mech.94.c6a53e6
ghcr.io/c3-e/images-staging/rms-copilot/backend:0.0.0-mech.94.c6a53e6
```

## Worked example — images with `build_args` (shared/generic Dockerfile)

For a pilot whose Dockerfile is a shared, generic per-app template (not
baked with the app's own identity) — e.g. `cra`'s `aca-backend`/
`aca-frontend`, built from the shared `containers/fullstack-backend`/
`containers/fullstack-frontend` engine Dockerfiles — supply the per-app
values as `build_args`. Any tuple that needs no build args (like
`backend` below) can simply omit the field:

```yaml
      images: |
        [
          {
            "name": "aca-backend",
            "dockerfile": "containers/fullstack-backend/Dockerfile",
            "context": ".",
            "build_args": {
              "APP_PATH": "apps/aca/backend",
              "APP_PACKAGE": "aca-backend",
              "APP_MODULE": "app.main:app",
              "APP_PORT": "8000"
            }
          },
          {
            "name": "aca-frontend",
            "dockerfile": "containers/fullstack-frontend/Dockerfile",
            "context": ".",
            "build_args": {
              "APP_PATH": "apps/aca/frontend",
              "APP_FILTER": "aca",
              "VITE_API_URL": "http://localhost",
              "VITE_MOCK_AUTH": "true",
              "VITE_GIT_SHA": "0.0.0-mech.94.c6a53e6"
            }
          }
        ]
```

Note on `VITE_API_URL` (and any other frontend-runtime-config build arg):
this job only proves the image **builds and publishes**, not that its
baked-in runtime config is correct for any particular consumer. A
staging-only placeholder value (e.g. `http://localhost`) is sufficient
here — a downstream composed-smoke consumer that needs the real API URL
at runtime is expected to override it via its own mechanism (e.g. an
env var or config map at `helm install` time), not by rebuilding this
image with a different `build_args` value.

## Worked example — `require_hardened_bases` (Chainguard and/or Iron Bank)

`cra`'s images above need Chainguard; a repo like `geoint` needs Iron Bank
instead (both of its images are Iron-Bank-only, hard-fail without
`IRONBANK_USERNAME`/`IRONBANK_TOKEN`). Both cases set the same
`require_hardened_bases: true` — which credential pair(s) are actually
present as secrets is what determines which registry the job logs into
(see [Secrets](#secrets) above); the input itself does not name a specific
registry:

```yaml
jobs:
  publish-staging-chart:
    if: github.event.pull_request.merged == true
    uses: c3-e/c3cdao-ci-scans/.github/workflows/publish-staging-chart.yml@<40-hex sha>
    with:
      chart_path: helm/rms-copilot
      publish_images: true
      require_hardened_bases: true
      images: |
        [
          {"name": "backend", "dockerfile": "apps/psp7-gateway/backend/Dockerfile", "context": "apps/psp7-gateway/backend"},
          {"name": "psp7-gateway-frontend", "dockerfile": "apps/psp7-gateway/frontend/Dockerfile", "context": "."}
        ]
    secrets:
      IRONBANK_USERNAME: ${{ secrets.IRONBANK_USERNAME }}
      IRONBANK_TOKEN: ${{ secrets.IRONBANK_TOKEN }}
```

**Caller gotcha (confirmed live, not theoretical):** declare `permissions:`
at the **workflow level only** on the calling file. A job that `uses:` a
reusable workflow must not carry its *own* `permissions:` block in addition
to a workflow-level one — that combination silently produces
`conclusion: startup_failure` with **zero jobs allocated** and no error
message anywhere in the API or the Actions UI (confirmed via isolation
testing against `c3cdao-geoint`: the identical reusable-workflow reference
resolved fine with either workflow-level-only or job-level-only
permissions, but failed every time both were present together on the same
job). If the calling job needs a permission the workflow-level block
doesn't grant, add it to the workflow-level block instead of overriding at
the job level.

```yaml
# WRONG — startup_failure, zero jobs, no error message
permissions:
  contents: read
  packages: write
jobs:
  publish-staging-chart:
    permissions:      # <-- do not also set permissions here
      packages: write
    uses: c3-e/c3cdao-ci-scans/.github/workflows/publish-staging-chart.yml@<sha>
    with:
      chart_path: helm/rms-copilot
```

```yaml
# RIGHT — workflow-level only
permissions:
  contents: read
  packages: write
jobs:
  publish-staging-chart:
    uses: c3-e/c3cdao-ci-scans/.github/workflows/publish-staging-chart.yml@<sha>
    with:
      chart_path: helm/rms-copilot
```

## Chart-shape validation

Before packaging, the workflow runs a fail-closed "Validate chart shape"
step (no `continue-on-error`, no `|| true` — same style as every other step
in this workflow) that checks two things:

1. **`helm lint <chart_path>`** must pass. Any lint error fails the job.
2. **Non-empty `routes:` contract.** Every pilot chart must declare
   its own routes somewhere in `values.yaml` — either top-level (`routes:`)
   or nested one level under the shared `fullstack-template`
   engine-dependency key (`fullstack-template.routes:`). Enforced as a
   JSON Schema (built inline in the step, `anyOf` the two shapes above),
   validated by [`check-jsonschema`](https://github.com/python-jsonschema/check-jsonschema)
   via `uvx` — not a hand-rolled recursive search. Confirmed against every
   one of the 6 already-published engine pilots' actual chart source
   (`rms-copilot`, `contract-automation`, `data-science`, `copa`,
   `osc-pipeline`, `dtic-rag`): all 6 use one of these exact two shapes,
   so the schema is exactly as permissive as real usage requires — not
   narrower, and not a generic "any key named `routes` at any depth"
   search either.

Grounded against all 6 already-published engine pilots before landing:
all 6 pass both checks unchanged, so this does not change behavior for any
chart that was already publishing successfully.

On failure, the step prints an `::error::` annotation naming which check
failed, why, and what to fix, e.g.:

```
::error::chart-shape validation failed: 'helm/<pilot>/values.yaml' does not declare a non-empty 'routes:' key (either top-level or nested under 'fullstack-template.routes:'). See the check-jsonschema output above for the exact violation. Fix: add a non-empty 'routes:' list to the chart's values.yaml before merging.
```

## Failure behavior

A chart-shape validation failure, a chart-package failure (e.g. a broken
chart dependency), or a registry-push failure fails the calling job closed —
visible as a red step on the PR's Checks tab, never a green run with a
missing or malformed artifact. This is not (currently) a required check; it
reports independently of the repo's own existing gate.
