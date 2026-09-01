# Publish Staging Chart — Inputs

`publish-staging-chart.yml` is a separate reusable workflow from the
[Reusable Security Gate](INPUTS.md) — different trigger model (merge-only,
side-effecting) and different side-effect profile (registry writes vs.
read-only scans). See [CI-CONTRACT.md](CI-CONTRACT.md) for why the two are
not folded together.

For the umbrella (`c3-e/c3cdao-apps`) consumer-side chart-shape contract and
the full pilot onboarding sequence (including wiring this workflow into a
new pilot's own fork repo), see `PILOT-ONBOARDING-RUNBOOK.md` in that repo.

This workflow's output feeds [`composed-smoke.yml`](COMPOSED-SMOKE.md): a
reusable workflow that installs every pilot's published `charts-staging`/
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
| `publish_images` | boolean | `false` | When `true` (and the merge's base branch is `ci-scans` or `main`, narrower than the chart trigger since image publishes are a heavier, more security-sensitive write), the `derive-publish-targets` job derives the publish target list from `compose_file` and `publish-images-deferred` retags each target's **already-built, already-scanned** quarantine image into `images-staging` by digest. It does **not** build anything; see [Single source of truth for publish targets](#single-source-of-truth-for-publish-targets) and [Digest-verified quarantine publish](#digest-verified-quarantine-publish) below. Default `false` keeps this input inert. |
| `compose_file` | string | `docker-compose.yml` | Path (relative to the calling repo root) of the canonical Compose file `publish_images` derives the publish target list from — the same file (and the same derivation) `reusable-security-gate.yml`'s own `plan` job uses. Only read when `publish_images` is `true`. Keep in sync with the gate caller's own `compose_file` when a repo's Compose file lives at a non-default path. |
| `publish_targets` | string (CSV) | `""` | Optional allow-list of compose build target names to publish, e.g. `"backend,frontend"`. Default `""` publishes every non-local build target `compose_file` declares — the common case. Set this only to exclude a built target from `images-staging` (e.g. a build-only/test target the chart never ships). Naming a target `compose_file` doesn't declare fails the job closed, listing the real target set. |
| `require_hardened_bases` | boolean | `false` | Set `true` if any declared image's Dockerfile `FROM`s a hardened base (Chainguard's `cgr.dev` and/or Iron Bank's `registry1.dso.mil`) and needs the corresponding credential secret pair to pull it during build. Passed straight through to this repo's [`hardened-registry-login`](../.github/actions/hardened-registry-login/action.yml) composite action's `require-hardened-bases` input, the same mechanism `reusable-security-gate.yml`'s `plan`/`build` jobs already use, reused here instead of a second, narrower login step. Fails closed (job errors) when `true` and neither credential pair is configured; when `false` (default), builds proceed on the Dockerfile's declared bases with no hardened-registry login attempt. (Renamed from this input's earlier, Chainguard-only `cgr_pull_required` name once the per-repo survey found several pilots (`geoint`, `pipeassist`, `dtic`'s fallback path) needing Iron Bank instead of or in addition to Chainguard.) |

**Retired:** the earlier `images` input (a hand-typed JSON array of
`{"name","target","dockerfile","context","build_args"?}` tuples) is gone.
See [Single source of truth for publish targets](#single-source-of-truth-for-publish-targets)
below for why, and update any existing caller still declaring `images:` to
the `compose_file`/`publish_targets` shape above.

**Cross-repo gotcha (worth checking before onboarding any pilot):** some
pilots maintain multiple wrapper-chart copies (e.g. `c3cdao-cra` has both
an older `helm/aca` and the actually-consumed `helm/contract-automation`).
Always point `chart_path` at the chart the umbrella's `Chart.yaml` actually
depends on, not the one that merely looks canonical by directory name — a
wrong guess here silently publishes a chart (and, when `publish_images` is
set, images) nobody consumes.

## Secrets

None required for the base case. Authentication for the chart-publish job
uses the calling job's `GITHUB_TOKEN` with `permissions: packages: write`,
Actions-native, not a personal PAT (a personal PAT lacks `write:packages` and
requires an interactive scope grant, which isn't viable for CI). The
image-publish job (`publish-images-deferred`) uses the same `GITHUB_TOKEN`
for its GHCR login and additionally accepts four **optional**
`workflow_call` secrets, needed only when `require_hardened_bases: true`:
one credential pair per hardened registry, mirroring exactly what
`reusable-security-gate.yml`'s own callers already configure for the same
underlying `hardened-registry-login` composite action, so a repo that has
already configured these for the security gate needs no new secret to also
use them here:

| Secret | Required | Purpose |
| --- | --- | --- |
| `CGR_PULL_TOKEN` | Only if `require_hardened_bases: true` and the image(s) need Chainguard | Chainguard (`cgr.dev`) registry pull token. |
| `CGR_PULL_USERNAME` | Only if `require_hardened_bases: true` and the image(s) need Chainguard | Chainguard (`cgr.dev`) registry pull username. |
| `IRONBANK_TOKEN` | Only if `require_hardened_bases: true` and the image(s) need Iron Bank | Iron Bank (`registry1.dso.mil`) pull token, e.g. `geoint`'s backend/frontend, `pipeassist`'s backend, `dtic`'s fallback path. |
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

Image artifacts (one per derived publish target, only when `publish_images: true`):

```
ghcr.io/c3-e/images-staging/<pilot>/<image-name>:0.0.0-mech.<pr-number>.<short-sha>
```

Unlike `helm push` (which always appends the chart's name as an extra
path component; see the comment above), `docker buildx imagetools create
--tag` does **not** infer or append any path segment: the destination tag
the job constructs is the full, exact path, including both `<pilot>` and
`<image-name>`.

This tag/path shape is intentionally **not** a legal ascending SemVer
release: `0.0.0-mech.*` cannot be mistaken for, or collide with, a real
release tag, and `charts-staging/`/`images-staging/` are distinct registry
namespaces from any future real publish target. These are pre-merge test
artifacts, not releases.

## Single source of truth for publish targets

Before this, `images[]` had to be hand-declared in the caller, matched by
its `target` field to whichever compose-target name `reusable-security-gate.yml`'s
own build matrix (derived from the SAME repo's compose file) used — the
same image list declared twice, once implicitly via the compose file and
once explicitly in the caller's JSON, with no check that the two agreed.
A typo or a forgotten update to either side either 404s the quarantine
lookup at merge time or silently omits an image, discovered late.

`publish_images: true` now runs a `derive-publish-targets` job first: it
checks out the merge commit, then runs the exact same derivation
`reusable-security-gate.yml`'s own `plan` job runs (`derive_bom.py` over
`compose_file`, i.e. `docker buildx bake --print` plus the non-local
`build:` service classification) to get the authoritative list of build
target names. `publish-images-deferred`'s matrix is populated directly
from that list (optionally narrowed by `publish_targets`) — never
hand-typed, so it cannot drift from the gate's own build matrix by
construction (a real config file drift, e.g. a compose service added on
one side but not reflected on the other, is a separate, already-tracked
concern — see Issue H, chart/build-identity verification — not something
this reintroduces).

This is a **local re-derivation from the checked-out compose file**, not
a fetch of `reusable-security-gate.yml`'s own `plan-bom` artifact:
that artifact is produced in a *different* GitHub Actions workflow run
(the gate fires on `pull_request`; this workflow fires on
`pull_request`/`closed`), so consuming it here would need
`actions/download-artifact`'s cross-run mode (`github-token` + `run-id`,
and a new `actions: read` grant on every caller — the same "missing
grant" bug class the caller lint hardens against elsewhere) plus a
run lookup by head SHA that has no unambiguous answer when a PR's gate
ran more than once. Re-deriving locally needs neither: `derive_bom.py`
is a pure function of the checked-out compose file, so there's nothing
to look up.

The `name` used for the `images-staging/<pilot>/<image-name>` path
segment (see [Output](#output) above) is now always the target name
itself — every documented and live caller already set them identically
before this change, so this is not an observed behavior change for any
onboarded pilot, only a removed opportunity for the two to diverge.

## Digest-verified quarantine publish

`publish_images: true` never rebuilds an image. Instead it retags, by
digest, an image the same pull request's `reusable-security-gate.yml` run
already built and scanned. This is the sole publish mechanism: no
rebuild fallback exists.

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
   HEAD commit SHA. This happens before image-scan runs, so the
   quarantine tag is not itself a scan attestation: it's a candidate
   retrieved later, only once the whole gate run (including image-scan)
   has gone green.
2. On merge, this workflow's `publish-images-deferred` job reconstructs
   the identical quarantine ref from the same three fields
   (`github.repository`, the PR number, and
   `github.event.pull_request.head.sha`, deliberately the PR's head SHA
   rather than the merge commit SHA, since the quarantine push happened
   before any merge existed) plus one target name from
   `derive-publish-targets`' compose-derived list (see
   [Single source of truth for publish targets](#single-source-of-truth-for-publish-targets)
   above).
3. It runs `docker buildx imagetools inspect` against that ref. If the
   image is missing or has expired out of the quarantine namespace's own
   GHCR retention, the job fails closed:
   ```
   ::error::quarantine image missing or expired for target <target>; PR must be re-scanned via a fresh gate run before merge
   ```
   No rebuild fallback exists: a missing quarantine image means the PR
   needs a fresh `reusable-security-gate.yml` run (with
   `publish_images: true`) before it can merge and publish.
4. On success, the job extracts the quarantine manifest's digest and runs
   `docker buildx imagetools create --tag <dest> <quarantine-ref>@<digest>`,
   a registry-side manifest/blob copy, not a rebuild or a client-side
   pull. For a single-platform source (every build in this fleet today;
   see [CI-CONTRACT.md](CI-CONTRACT.md), `linux/amd64` only), `imagetools
   create` wraps the quarantined manifest in a new single-entry image
   index (manifest list) and tags that as `<dest>`, confirmed live via
   `selftest-publish-images.yml`'s run history. The wrapped child
   manifest is copied unmodified, keeping its original digest (nothing is
   rebuilt or re-derived); only the outer index is new bytes. So
   `<dest>`'s top-level digest differs from the quarantine digest, but
   `docker buildx imagetools inspect <dest> --raw | jq '.manifests[].digest'`
   still shows the untouched quarantine digest, and `docker pull <dest>`
   resolves to that same, unmodified image
   `reusable-security-gate.yml`'s image-scan job scanned.

**Fork-PR caveat:** this mechanism assumes same-repo PRs. `GITHUB_TOKEN` is
force-read-only for `pull_request` events triggered from a fork repo (a
GitHub platform restriction, not something this workflow can override), so
a fork PR's `reusable-security-gate.yml` run cannot push to the quarantine
namespace in the first place, and this job's retag step would fail closed
on the missing-image path for the same reason. Callers publishing images
from fork PRs are not supported by this mechanism today.

## Worked example: chart only

```yaml
jobs:
  publish-staging-chart:
    if: github.event.pull_request.merged == true
    uses: c3-e/c3cdao-ci-scans/.github/workflows/publish-staging-chart.yml@<40-hex sha>  # v0.1.0
    with:
      chart_path: helm/rms-copilot
```

## Worked example: chart + images

```yaml
jobs:
  publish-staging-chart:
    if: github.event.pull_request.merged == true
    uses: c3-e/c3cdao-ci-scans/.github/workflows/publish-staging-chart.yml@<40-hex sha>
    with:
      chart_path: helm/rms-copilot
      publish_images: true
      compose_file: docker-compose.yml  # same file reusable-security-gate.yml's own compose_file input points at
```

No `images:` array to hand-maintain: `derive-publish-targets` derives the
target list (here, `frontend` and `backend`) directly from `compose_file`'s
own non-local `build:` services — the same names
`reusable-security-gate.yml`'s `build` job matrixed over for this PR, by
construction (see [Single source of truth for publish targets](#single-source-of-truth-for-publish-targets)).

Produces, from one merge (PR `#94`, merge commit `c6a53e6...`):

```
oci://ghcr.io/c3-e/charts-staging/rms-copilot:0.0.0-mech.94.c6a53e6
ghcr.io/c3-e/images-staging/rms-copilot/frontend:0.0.0-mech.94.c6a53e6
ghcr.io/c3-e/images-staging/rms-copilot/backend:0.0.0-mech.94.c6a53e6
```

## Worked example: publishing only a subset of built targets

For a repository whose Compose file builds a target the chart never
ships (e.g. a build-only/test image — see the `built-unscheduled` lint
warning on `reusable-security-gate.yml`), narrow `publish_targets` to
just the targets that should actually land in `images-staging`:

```yaml
      publish_images: true
      compose_file: docker-compose.yml
      publish_targets: "backend,frontend"  # excludes e.g. a "test-runner" build target
```

Naming a target `compose_file` doesn't declare (a typo, or one that's
excluded via `profiles: [local]`) fails `derive-publish-targets` closed,
citing the real available target list — never a silent no-op.

Build args, Dockerfile paths, and build contexts are never declared here:
`publish-images-deferred` only retags an already-built quarantine image
by digest (see [Digest-verified quarantine publish](#digest-verified-quarantine-publish)),
so it has no need to know them. The same PR's `reusable-security-gate.yml`
Compose file / bake target definition is the one and only place that
actually builds the image, and the one and only place any of that detail
needs to live.

## Worked example: `require_hardened_bases` (Chainguard and/or Iron Bank)

`require_hardened_bases` on this workflow governs only the login side
effect this job's `publish-images-deferred` step performs before its
`imagetools inspect`/`imagetools create` calls (both operate registry-side
against `ghcr.io`, but the same shared `hardened-registry-login` action
is reused here for consistency with `reusable-security-gate.yml`'s own
plan/build jobs). The actual base-image pull happened earlier, in the
gate's own `build` job. Set `require_hardened_bases` on both workflows
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
      compose_file: docker-compose.yml
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

## Caller lint

`scripts/lib/lint_caller_publish.py` is the caller-lint equivalent of
`reusable-security-gate.yml`'s `lint_caller.py`, scoped to this workflow's
own actual shape (no Compose file, no build matrix, no `image_only` mode —
so none of `lint_caller.py`'s convention pipeline applies). Every real bug
found onboarding Phase 2 pilots — a missing `target` field on an
`images[]` tuple, a missing caller-side `packages: write` permission, a
missing `routes:` key in the chart's `values.yaml` — was previously
discovered ad hoc, per pilot, at merge time; this catches the first two
mechanically at lint time and the third as an early warning. Run it via:

```sh
uv run scripts/lib/lint_caller_publish.py <caller.yml> [--consumer-root <path>]
```

`--consumer-root` is required only to enable the `publish-chart-routes-missing`
warn rule (it needs the caller's `chart_path` resolved against the actual
consumer checkout to find `values.yaml`); the rest of the rules run against
the caller file alone. See `templates/callers/publish-staging-chart.yml`
for a starting caller you can copy into your own repo.

### Rule table

Every lint finding carries a `remediation_ref` pointing at one of the rule
headings below. `publish-chart-routes-missing` is **warn**: it reports
without blocking. Everything else blocks the run.

| Rule id | Level | Check |
|---|---|---|
| [`publish-ref-pin`](#rule-publish-ref-pin) | block | `uses:` is not pinned by a full 40-hex commit SHA |
| [`publish-decoy-job`](#rule-publish-decoy-job) | block | more than one job in the caller calls `publish-staging-chart.yml` |
| [`publish-packages-write-missing`](#rule-publish-packages-write-missing) | block | `publish_images: true` is set but no `permissions:` block grants `packages: write` |
| [`publish-permissions-both-levels`](#rule-publish-permissions-both-levels) | block | `permissions:` is declared at both the workflow level and the calling job level |
| [`publish-chart-routes-missing`](#rule-publish-chart-routes-missing) | warn | the chart's `values.yaml` declares no non-empty `routes:` key |
| [`unreadable-caller`](#rule-unreadable-caller) | block | the caller workflow cannot be parsed, or no job's `uses:` matches `publish-staging-chart.yml` |

### Rule: publish-ref-pin

The `publish-staging-chart.yml` ref in `uses:` must be pinned by a full
40-hex commit SHA; record the release tag as a trailing comment. Mirrors
`lint_caller.py`'s `gate-ref-pin` rule for the security gate. Tags and
branches (including `@main`) block.

### Rule: publish-decoy-job

Exactly one job may call `publish-staging-chart.yml`, run or not. This
workflow's own "Resolve callee (ci-scans) ref" step takes the FIRST
`uses:` match in the caller file (same first-match parse
`reusable-security-gate.yml`'s resolver uses) — a second, differently
pinned job calling this workflow is a decoy vector against that resolver,
exactly the reasoning behind `lint_caller.py`'s `decoy-gate-job` rule.

### Rule: publish-packages-write-missing

When `publish_images: true` is set, some `permissions:` block on the caller
(workflow-level or job-level) must grant `packages: write`. This is the
exact bug that caused a real, hard-to-diagnose failure in production
onboarding: a **missing grant**, not a missing declaration — GitHub Actions
caps a reusable workflow's granted permissions at whatever the caller
itself grants, independent of the callee's own `permissions:` block.
Without it, `publish-images-deferred`'s `imagetools create` push fails at
merge time with a registry-permission error, not a clean, named lint
finding.

### Rule: publish-permissions-both-levels

`permissions:` must not be declared at both the workflow level and the
calling job level on the same caller. Confirmed live (see the "Caller
gotcha" worked example above) to silently produce
`conclusion: startup_failure` with zero jobs allocated and no error
message anywhere in the API or the Actions UI.

### Rule: publish-chart-routes-missing

**Warn only.** The declared `chart_path`'s `values.yaml` should declare a
non-empty `routes:` key, either top-level or nested one level under
`fullstack-template.routes:` — the same two shapes the "Chart-shape
validation" runtime check above enforces at merge time. Reported as a
warning rather than a block because a brand-new pilot's chart may not
exist yet at lint time; the real, blocking enforcement of this contract
remains the runtime `check-jsonschema` step. Fixing it before merge avoids
discovering the gap only when the merge-time step fails.

### Rule: unreadable-caller

The caller workflow must parse as YAML with a non-empty `jobs:` mapping,
and at least one job's `uses:` must match `publish-staging-chart.yml`.
Fails closed rather than silently reporting a clean run for an
unparseable or unrelated caller file.
