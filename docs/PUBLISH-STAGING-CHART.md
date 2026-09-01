# Publish Staging Chart — Inputs

`publish-staging-chart.yml` is a separate reusable workflow from the
[Reusable Security Gate](INPUTS.md) — different trigger model (merge-only,
side-effecting) and different side-effect profile (registry writes vs.
read-only scans). See [CI-CONTRACT.md](CI-CONTRACT.md) for why the two are
not folded together.

For the umbrella (`c3-e/c3cdao-apps`) consumer-side chart-shape contract and
the full pilot onboarding sequence (including wiring this workflow into a
new pilot's own fork repo), see `PILOT-ONBOARDING-RUNBOOK.md` in that repo.

A downstream consumer of this workflow's own output is
[`composed-smoke.yml`](COMPOSED-SMOKE.md) — the umbrella's own reusable
workflow that installs every pilot's published `charts-staging`/
`images-staging` artifacts together in one `kind` cluster. See
[COMPOSED-SMOKE.md](COMPOSED-SMOKE.md) for its contract.

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
| `publish_images` | boolean | `false` | When `true` (and the merge's base branch is `ci-scans` or `main` — narrower than the chart trigger, since image publishes are a heavier, more security-sensitive write), the `publish-images-deferred` job retags each declared `images[]` tuple's **already-built, already-scanned** quarantine image into `images-staging` by digest. It does **not** build anything itself — see [Digest-verified quarantine publish](#digest-verified-quarantine-publish) below for the full mechanism and its same-repo-PR requirement. Default `false` keeps this input inert. |
| `images` | string (JSON) | `"[]"` | JSON array of image build tuples to publish when `publish_images` is `true`: `{"name","target","dockerfile","context","build_args"?}`. `name` becomes the `<image-name>` path segment (see [Output](#output) below). `target` is **required**: the exact bake target name the SAME PR's `reusable-security-gate.yml` `build` job used for this image (the name its matrix fans out over) — used to reconstruct the quarantine ref this job retags from; a mismatch here 404s the quarantine lookup and fails the job closed. `dockerfile`/`context`/`build_args` are retained in the tuple shape for documentation/audit purposes only — this job no longer builds, so it does not read them (a future cleanup may drop them once the migration is complete; see [Digest-verified quarantine publish](#digest-verified-quarantine-publish)). Ignored when `publish_images` is `false`. |
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
path component — see the comment above), `docker buildx imagetools create
--tag` does **not** infer or append any path segment: the destination tag
the job constructs is the full, exact path, including both `<pilot>` and
`<image-name>`.

This tag/path shape is intentionally **not** a legal ascending SemVer
release: `0.0.0-mech.*` cannot be mistaken for, or collide with, a real
release tag, and `charts-staging/`/`images-staging/` are distinct registry
namespaces from any future real publish target. These are pre-merge test
artifacts, not releases.

## Digest-verified quarantine publish

`publish_images: true` never rebuilds an image. Instead it retags, by
digest, an image the SAME pull request's `reusable-security-gate.yml` run
already built and scanned. This is the sole publish mechanism — there is
no rebuild fallback.

**How it works, end to end:**

1. On the PR, the caller's `reusable-security-gate.yml` run sets its own
   `publish_images: true` input (a separate input on that workflow, not
   this one). Its `build` job, after producing and tag-verifying each
   bake target's image (the same image the rest of the gate scans), tags
   and pushes it to a quarantine namespace:
   ```
   ghcr.io/c3-e/images-quarantine/<repo>/<target>:pr-<pr-number>-<short-head-sha>
   ```
   `<repo>` is `github.repository` (lowercased), `<target>` is the bake
   target name, `<short-head-sha>` is the first 7 characters of the PR's
   HEAD commit SHA. This happens BEFORE image-scan runs — the quarantine
   tag is not itself a scan attestation, it is a candidate later retrieved
   only once the whole gate run (including image-scan) has gone green.
2. On merge, this workflow's `publish-images-deferred` job reconstructs
   the identical quarantine ref from the same three fields
   (`github.repository`, the PR number, and
   `github.event.pull_request.head.sha` — deliberately the PR's head SHA,
   not the merge commit SHA, since the quarantine push happened before any
   merge existed) plus the `images[]` tuple's own `target` field.
3. It runs `docker buildx imagetools inspect` against that ref. If the
   image is missing or has expired out of the quarantine namespace's own
   GHCR retention, the job fails closed:
   ```
   ::error::quarantine image missing or expired for target <target>; PR must be re-scanned via a fresh gate run before merge
   ```
   There is no rebuild fallback — a missing quarantine image means the PR
   must go through a fresh `reusable-security-gate.yml` run (with
   `publish_images: true`) before it can be merged and published.
4. On success, the job extracts the quarantine manifest's digest and runs
   `docker buildx imagetools create --tag <dest> <quarantine-ref>@<digest>`
   — a registry-side manifest/blob copy, not a rebuild or a client-side
   pull. For a single-platform source (every build in this fleet today —
   see [CI-CONTRACT.md](CI-CONTRACT.md), `linux/amd64` only), `imagetools
   create` wraps the quarantined manifest in a new single-entry image
   index (manifest list) and tags THAT as `<dest>` — confirmed live via
   `selftest-publish-images.yml`'s own run history. The wrapped child
   manifest is copied unmodified, keeping its original digest (nothing is
   rebuilt or re-derived); only the outer index is new bytes. So
   `<dest>`'s own top-level digest differs from the quarantine digest, but
   `docker buildx imagetools inspect <dest> --raw | jq '.manifests[].digest'`
   still shows the untouched quarantine digest, and `docker pull <dest>`
   transparently resolves to that same, unmodified image
   `reusable-security-gate.yml`'s image-scan job scanned.

**Fork-PR caveat:** this mechanism assumes same-repo PRs. `GITHUB_TOKEN` is
force-read-only for `pull_request` events triggered from a fork repo (a
GitHub platform restriction, not something this workflow can override), so
a fork PR's `reusable-security-gate.yml` run cannot push to the quarantine
namespace in the first place, and this job's retag step would fail closed
on the missing-image path for the same reason. Callers publishing images
from fork PRs are not supported by this mechanism today.

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
          {"name": "frontend", "target": "frontend", "dockerfile": "Dockerfile.frontend", "context": "."},
          {"name": "backend", "target": "backend", "dockerfile": "Dockerfile.backend", "context": "."}
        ]
```

`target` must equal the bake target name the SAME PR's
`reusable-security-gate.yml` `build` job matrixed over for this image (see
[Digest-verified quarantine publish](#digest-verified-quarantine-publish));
it usually — but not necessarily — matches `name`.

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
            "target": "aca-backend",
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
            "target": "aca-frontend",
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

**`build_args`/`dockerfile`/`context` no longer drive a build in THIS
workflow** (see [Digest-verified quarantine publish](#digest-verified-quarantine-publish)
— `publish-images-deferred` only retags an already-built quarantine image
by digest). They remain useful as documentation of how the image was
actually built, and matter to the ONE place that still builds it: the
SAME PR's `reusable-security-gate.yml` Compose file / bake target
definition, which is the real source of truth for build args, base image,
and Dockerfile path. Note on `VITE_API_URL` (and any other
frontend-runtime-config build arg) for that build: it only proves the
image **builds and publishes**, not that its baked-in runtime config is
correct for any particular consumer — a staging-only placeholder value
(e.g. `http://localhost`) is sufficient there, and a downstream
composed-smoke consumer that needs the real API URL at runtime overrides
it via its own mechanism (e.g. an env var or config map at `helm install`
time) rather than rebuilding the image with a different value.

## Worked example — `require_hardened_bases` (Chainguard and/or Iron Bank)

`require_hardened_bases` on THIS workflow governs only the login side
effect this job's `publish-images-deferred` step performs before its
`imagetools inspect`/`imagetools create` calls (both operate registry-side
against `ghcr.io`, but the same shared `hardened-registry-login` action
is reused here for consistency with `reusable-security-gate.yml`'s own
plan/build jobs). The actual base-image pull happened earlier, in the
gate's own `build` job — set `require_hardened_bases` on both workflows
consistently, since each governs its own registry-credential-login step
independently and neither reads the other's:

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
          {"name": "backend", "target": "backend", "dockerfile": "apps/psp7-gateway/backend/Dockerfile", "context": "apps/psp7-gateway/backend"},
          {"name": "psp7-gateway-frontend", "target": "psp7-gateway-frontend", "dockerfile": "apps/psp7-gateway/frontend/Dockerfile", "context": "."}
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
