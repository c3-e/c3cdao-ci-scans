# Publish Staging Chart — Inputs

`publish-staging-chart.yml` is a separate reusable workflow from the
[Reusable Security Gate](INPUTS.md) — different trigger model (merge-only,
side-effecting) and different side-effect profile (registry writes vs.
read-only scans). See [CI-CONTRACT.md](CI-CONTRACT.md) for why the two are
not folded together.

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

## Secrets

None declared as `workflow_call` secrets. Authentication is the calling
job's own `GITHUB_TOKEN` with `permissions: packages: write` — Actions-native,
not a personal PAT (a personal PAT lacks `write:packages` and requires an
interactive scope grant, which isn't viable for CI).

## Output

```
oci://ghcr.io/c3-e/charts-staging/<pilot>:0.0.0-mech.<pr-number>.<short-sha>
```

This tag/path shape is intentionally **not** a legal ascending SemVer
release: `0.0.0-mech.*` cannot be mistaken for, or collide with, a real
release tag, and `charts-staging/` is a distinct registry namespace from
any future real chart-publish target. This is a pre-merge test artifact,
not a release.

## Worked example

```yaml
jobs:
  publish-staging-chart:
    if: github.event.pull_request.merged == true
    uses: c3-e/c3cdao-ci-scans/.github/workflows/publish-staging-chart.yml@<40-hex sha>  # v0.1.0
    with:
      chart_path: helm/rms-copilot
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

## Failure behavior

A chart-package failure (e.g. a broken chart dependency) or a registry-push
failure fails the calling job closed — visible as a red step on the PR's
Checks tab, never a green run with a missing artifact. This is not
(currently) a required check; it reports independently of the repo's own
existing gate.
