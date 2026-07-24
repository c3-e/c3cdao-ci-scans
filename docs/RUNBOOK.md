# Onboarding runbook

Copy-and-own onboarding for the c3cdao-ci-scans security gate, as a sequential
walkthrough: copy the caller, edit `with:`, set the four secrets, create the
ruleset, pilot on a scratch branch, then promote to trunk and enforce. Every
step is version-pinned and copy-paste-able, names who runs it (**consumer** =
the gated repo's team; **operator** = whoever holds admin on the consumer repo
and runs the one-time setup commands), and states the observable outcome.

For the requirement-by-requirement traceability, see
[REQUIREMENTS-MAP.md](REQUIREMENTS-MAP.md). For the field reference, see
[INPUTS.md](INPUTS.md) and the Inputs table in the [README](../README.md).
Reference material — the registry login matrix, the scan-boundary discussion,
the caller-lint rule ids, and maintenance notes — lives in the
[appendix](#appendix-reference); the steps link into it where needed.

## Branch conventions (decide first)

Pilot/scratch branch naming depends on the repo shape. Decide before step 7;
steps 7–10 use these names.

| Repo shape | Convention |
|---|---|
| **Single-app usecase repo** (one app per repo, e.g. `c3cdao-dsa-ecpilot`) | Scan target branch is the **bare** name **`ci-scans`**. There is only one usecase in the repo, so no token is needed. The helm-chart side mirrors this with a bare **`ci-chart`**. |
| **Shared umbrella repo** (many usecases integrated in one repo, i.e. `c3cdao-apps`) | A token is required to avoid collisions — use **`ci-chart-<usecasename>`** (e.g. `ci-chart-ecpilot`) so each usecase's chart branch coexists. |
| **Canary (trigger) branch** (all shapes) | The canonical name **`ci-scans-canary`** — a trigger-only branch cut off the scan target head (step 8). |

Keep a single hyphenated branch as the scan target; a slash form like
`ci-scans/...` is non-conforming. Why the shared umbrella repo is scanned at
all is reference material: see
[appendix E](#e-why-scan-the-shared-umbrella-repo-at-all).

## 0. Prerequisites (consumer + operator)

The gate assumes this app shape:

- the app serves the health route your manifest declares (`health.path`,
  default `GET /health` — cluster-smoke probes it after the helm install)
- a helm deploy of the primary backend image (built, scanned, kind-loaded, and
  installed). Declare self-authored, gate-reachable frontend/sidecar images as
  extra `ci-manifest` `images[]` entries — those tags are also kind-loaded for
  smoke when built. Pass `smoke_secrets` when the chart requires Secrets beyond
  what your `make ci-smoke-env` target provisions
- a consumer build contract makefile (`Makefile.ci`, from
  [`templates/consumer/Makefile.ci`](../templates/consumer/Makefile.ci))
  exposing `ci-manifest` / `ci-build` / `ci-secctx` / `ci-smoke-env` — the
  gate's only build path, see [CI-CONTRACT.md](CI-CONTRACT.md)

Tooling: `gh` (authenticated), `uv`, and **admin** on the consumer repo (secrets
and rulesets).

**You should see:** every bullet answered yes for your repo before moving on —
the operator holds admin, and `gh`/`uv` are available on the operator laptop.

## 1. Copy the caller template — commit 1 (consumer)

```bash
cd <consumer-repo>
mkdir -p .github/workflows
cp <ci-scans-clone>/templates/callers/security-gate.yml .github/workflows/security-gate.yml
cp <ci-scans-clone>/templates/consumer/Makefile.ci Makefile.ci
```

You own both files from here — no tooling ever rewrites them. `Makefile.ci` is
the consumer build contract (`ci-manifest` / `ci-build` / `ci-secctx` /
`ci-smoke-env`); edit its variable block so `ci-manifest` describes your
images, chart, and health probe, and `ci-build` builds your Dockerfile(s) —
see [CI-CONTRACT.md](CI-CONTRACT.md).

**You should see:** `.github/workflows/security-gate.yml` and `Makefile.ci` in
the consumer repo, committed as their own commit.

## 2. Edit `with:` and pin the version — commit 2 (consumer)

Every `with:` line in the template carries an inline provenance comment naming
where its value must come from in your repo (Dockerfile ARG, helm values file,
package metadata, or operator choice). Edit each to match, and set your trigger
branches under `on.pull_request.branches`.

Two invariants the caller lint enforces — do not break them:

- Keep the job id `security-scan`. It is half of the required check context
  `security-scan / Security Gate`; renaming it silently un-gates merges.
- Pass secrets **explicitly** (`CGR_PULL_TOKEN: ${{ secrets.CGR_PULL_TOKEN }}`),
  never the `inherit` form. `inherit` works only when caller and callee share an
  org/enterprise; across owners it silently passes nothing and SonarQube dies at
  setup with `Unexpected value ''`.

### Version pin

The template ships with `@main` for the pilot window. In production, pin a
release tag:

```yaml
uses: c3-e/c3cdao-ci-scans/.github/workflows/reusable-security-gate.yml@v0.5.1
```

`@main` is acceptable only during the pilot migration window.

**You should see:** every `with:` value traced to its provenance source, trigger
branches set (per the [branch conventions](#branch-conventions-decide-first) if
piloting on a scratch branch), the job id still `security-scan`, and secrets
passed explicitly.

## 3. Lint the caller locally (consumer)

Run the caller lint locally before you push:

```bash
uv run scripts/lib/lint_caller.py <caller.yml> \
  --contract contract/security-gate.schema.json \
  [--consumer-root <consumer-checkout>]
```

`caller-lint` is a fail-closed configuration pre-flight: it resolves your caller
and lints it against the published contract before anything scans. Your caller
must also grant the permissions the reusable workflow needs:

- `pull-requests: write`, `actions: write` — the caller is the ceiling; the
  reusable workflow cannot elevate.
- No `concurrency:` on the caller — the reusable workflow owns the group.
- Secrets passed **explicitly**, never the `inherit` form (see step 2).

The full rule-id list and skip/notice semantics are reference material: see
[appendix C](#c-caller-lint-rule-ids-and-notices).

**You should see:** the lint exit clean. Rules skipped for a stated reason
announce on stderr (`notice: skip: image-values-mismatch: --consumer-root not
given`); with a consumer checkout supplied, the values-file rule announces
`notice: active: image-values-mismatch: checked <path>`.

## 4. Set the four secrets — one-time (operator)

```bash
gh secret set CGR_PULL_TOKEN     --repo <owner>/<repo>
gh secret set CGR_PULL_USERNAME  --repo <owner>/<repo>
gh secret set IRONBANK_TOKEN     --repo <owner>/<repo>
gh secret set IRONBANK_USERNAME  --repo <owner>/<repo>
```

These four names are exactly what the workflow declares (not the older
`*_IDENTITY`/`*_CLI_SECRET` spellings). UI alternative: Settings → Secrets and
variables → Actions → New repository secret.

| Secret | Job |
|--------|-----|
| `CGR_PULL_TOKEN`, `CGR_PULL_USERNAME` | Phase 1 build — Chainguard (`cgr.dev`) login |
| `IRONBANK_TOKEN`, `IRONBANK_USERNAME` | SonarQube ephemeral + build Iron Bank (`registry1.dso.mil`) login — can run **alongside** Chainguard when both are set |

How the two logins interact (independent logins, primary-base image swap, the
`require_hardened_bases` fail-closed posture) is reference material: see
[appendix B](#b-hardened-base-registry-login-matrix-build).

**You should see:** all four names listed under the repo's Actions secrets
(Settings → Secrets and variables → Actions).

## 5. Create the ruleset — disabled (operator)

From the ci-scans clone. `configs/local/` is gitignored — real ops configs (org
names, local paths) live there.

```bash
cp configs/examples/example.yaml configs/local/<repo>.yaml
# edit target.* / ci_scans.* / ruleset.*

./scripts/setup-ruleset.sh --config configs/local/<repo>.yaml            # create, disabled
```

`setup-ruleset.sh` creates the `security-scan-gates` ruleset **disabled** by
default (safe rollout). Private repos need a paid org/enterprise plan to
enforce. Add `--dry-run` to preview the API payload without writing.

The ops YAML is schema-validated at load (typos fail with pathed errors; see
`config/schema.json`) and carries **operations-only** fields: `target`,
`ci_scans`, `ruleset`, plus optional `workflows`. Gate values live
in your caller's `with:`, not here — a leftover `security_gate:` block is
deprecated and ignored with a warning.

If piloting on a scratch branch, scope the ruleset now: `target.trunk_branches:
[ci-scans]` and `ruleset.target_branch: ci-scans` (the ruleset then targets
that literal ref, independent of the repo's default branch — use your name from
the [branch conventions](#branch-conventions-decide-first)).

**You should see:** the `security-scan-gates` ruleset in the consumer repo's
Settings → Rules → Rulesets, in the **disabled** state.

## 6. Enable the ruleset (operator)

```bash
./scripts/setup-ruleset.sh --config configs/local/<repo>.yaml --enable   # enforce
```

`--enable` sets the ruleset to active so `security-scan / Security Gate`
becomes a required check. The script is idempotent — re-run it to re-target.

**You should see:** the ruleset flip to **active**, and
`security-scan / Security Gate` listed as a required status check on the target
branch.

## 7. Set up the scratch-branch pilot (consumer + operator)

To pilot on a shared repo without touching its real trunk, cut a scratch branch
and scope both the trigger and the ruleset to it, using your name from the
[branch conventions](#branch-conventions-decide-first) table:

- caller: `on.pull_request.branches: [ci-scans]` (single-app repo)
- ops YAML: `target.trunk_branches: [ci-scans]` and `ruleset.target_branch:
  ci-scans` (the ruleset then targets that literal ref, independent of the
  repo's default branch) — re-run step 6 if you re-target

Full scratch-branch walkthrough:
[CI CD Workflow runbook](https://c3energy.atlassian.net/wiki/spaces/CCA/pages/10910040079/).

**You should see:** the scratch branch (e.g. `ci-scans`) pushed, the caller's
trigger scoped to it, and the ruleset targeting it.

## 8. Trigger the gate with a canary PR (consumer)

The scan target branch never receives direct pushes to trigger the gate — open
a trigger-only PR into it from the canonical canary branch **`ci-scans-canary`**:

1. Cut `ci-scans-canary` off the `ci-scans` head and add a trivial marker
   commit (e.g. a `.ci-scans-canary` file).
2. Open a PR `ci-scans-canary` → `ci-scans` titled
   `canary: security-gate @<tag>`. The `on.pull_request.branches: [ci-scans]`
   trigger fires the gate; existing rules on the repo's real trunk are never
   touched.
3. The canary PR is **never merged** — it exists only to trigger. Re-trigger a
   fresh run after a caller change by merging the updated `ci-scans` head into
   `ci-scans-canary` (`gh api -X POST repos/<owner>/<repo>/merges -f
   base=ci-scans-canary -f head=ci-scans`).
   Keep the PR a **draft** (`gh pr ready <n> --undo`): `pull_request` triggers
   fire on drafts just the same, draft status signals "trigger vehicle, not a
   merge candidate", and it mutes the re-review churn a wildcard `CODEOWNERS`
   rule would otherwise generate on every push.
4. Comment the per-job results table and run URL on the canary PR as evidence
   (see `c3-e/c3cdao-ppubs#33` for the reference shape).

**Fleet testing:** canary **one** consumer through a pin/secrets change before
fanning out many repos. Do not re-trigger a full multi-repo Security Scan
matrix until the canary's real fail mode is fixed.

**You should see:** the check context **`security-scan / Security Gate`**
appear on the canary PR and go green. The gate's `caller-lint` job runs first
and names any scaffold violation in your copied caller before anything scans.
Job order and fail-fast wiring are reference material: see
[appendix D](#d-job-order-and-fail-fast-actions-minutes).

List the live check names on a PR head (e.g. to verify a ruleset paste by eye):

```bash
gh api repos/<owner>/<repo>/commits/<sha>/check-runs --jq '.check_runs[].name'
```

## 9. Promote to trunk (consumer + operator)

When the pilot is green, promote it to the repo's default branch:

1. In the caller, point the trigger branches at the trunk
   (`on.pull_request.branches: [main]`).
2. Re-target the ruleset: drop `ruleset.target_branch` from the ops YAML (or set
   it to the default branch) and re-run
   `./scripts/setup-ruleset.sh --config configs/local/<repo>.yaml --enable`.
3. Pin the caller's `uses:` to a release tag if it was still on `@main`.

**You should see:** real PRs into the default branch carry the
`security-scan / Security Gate` required check, and the caller pinned at a
release tag.

## 10. Clean up the scratch branches (consumer)

After promotion, the pilot branches have served their purpose — remove them so
the scratch trigger and the never-merged canary PR do not linger:

1. Close the canary PR (it is never merged — step 8).
2. Delete the canary branch and the scratch scan-target branch (e.g.
   `ci-scans-canary` and `ci-scans`):

```bash
git push origin --delete ci-scans-canary
git push origin --delete ci-scans
```

Only do this after step 9 re-targeted the ruleset away from the scratch branch;
a ruleset targeting a deleted literal ref gates nothing.

**You should see:** no `ci-scans*` branches left on the consumer repo, and the
canary PR closed.

## 11. Flip enforcement to blocking (operator)

The enforcement model has two knobs:

- **Ruleset enable** (per-consumer): `setup-ruleset.sh --enable` (step 6) makes
  `security-scan / Security Gate` a required check on the target branch.
- **`SECURITY_SCAN_BLOCKING` repo variable** (gate-internal): hard-fail posture
  for cluster-smoke and image-scan. Until it is `true` they warn instead of
  failing; a skipped/cancelled/errored blocking job still fails the gate.
  Flipping it to `true` is the **final** acceptance step — see
  [REQUIREMENTS-MAP.md](REQUIREMENTS-MAP.md).

```bash
gh variable set SECURITY_SCAN_BLOCKING --body true --repo <owner>/<repo>
```

**You should see:** the repo variable set to `true`, and subsequent gate runs
hard-failing (not warning) on cluster-smoke / image-scan findings.

## Migrating from modular scans (consumer + operator)

For a repo that already runs the older modular scan workflows:

1. Add the caller: copy `templates/callers/security-gate.yml` and edit `with:`
   (steps 1–2 above).
2. Delete modular workflows: `secret-scan.yml`, `semgrep.yml`, `sca-scan.yml`,
   `sonarqube.yml`, `helm-validate.yml`, `pr-gate.yml` (STIG stays separate if
   still needed).
3. Update the ruleset: only `security-scan / Security Gate` required.
4. Set repo variable `SECURITY_SCAN_BLOCKING=true` when ready to enforce
   vuln/cluster gates (step 11).

## Appendix (reference)

Reference prose kept out of the step flow. Operator/consumer labels do not
apply here — this is background, not action.

### A. Scripts and operator surface

Onboarding a consumer is **six one-time commands run from an operator laptop**:
four `gh secret set` (step 4), one `gh variable set SECURITY_SCAN_BLOCKING`
(step 11), and one `./scripts/setup-ruleset.sh` (steps 5–6). None of this runs
in CI, and none of it renders or rewrites the caller.

| Script | Purpose |
|--------|---------|
| `setup-ruleset.sh` | convenience wrapper around a single GitHub rulesets API call: create/update the `security-scan-gates` ruleset (created **disabled**; `--enable` to enforce; idempotent, so re-run it to re-target) |

`scripts/lib/` is mostly **not** operator tooling: `lint_caller.py`,
`evaluate_security_gate.py`, and `assert_restricted_pss.py` run inside the gate
(Layer 1); `extract_contract.py` is dev-time contract generation for this repo
(the `contract-extract` hook); only the config loader supports
`setup-ruleset.sh`.

### B. Hardened-base registry login matrix (build)

Logins are **independent** (docker stores credentials per registry host). Setting
both `CGR_PULL_*` and `IRONBANK_*` authenticates **both** in one run — required
for mixed-base repos (e.g. Chainguard primary + Iron Bank extras in the manifest).

1. `CGR_PULL_TOKEN` set → login `cgr.dev`.
2. `IRONBANK_TOKEN` set → login `registry1.dso.mil` (does **not** require CGR to
   be absent).
3. **Primary-base image swap** (separate from login): only when Chainguard is
   *absent* and Iron Bank is *present*, the primary builder/runtime may swap to
   `ironbank_builder_image` / `ironbank_runtime_image`. With both creds set, the
   primary keeps its Chainguard bases; extras pull Iron Bank bases via the
   second login.
4. Neither credential → `require_hardened_bases: false` warns and builds on the
   consumer's own bases; otherwise fail (no silent public fallback).

#### Scan boundary (proxy vs approved image)

The gate authenticates only to `cgr.dev` and `registry1.dso.mil`. It scans the
image **as built with those gate-reachable bases**. If the approved production
image uses a private mirror or entitlement the runner cannot reach, OS-layer /
approved-image attestation is **out of scope** for this gate — keep that in the
consumer IL5 / Game Warden (or equivalent) pipeline.

- Declare manifest extras for **self-authored, gate-reachable** images only.
- When `require_hardened_bases: false` (pilot escape hatch / public substitutes),
  every build and Vulnerability Scan leg emits a **proxy-scan** warning and
  job-summary label. Green ≠ approved prod image clean.

Consumers without a `ci-secctx` contract target get the gate's
bundled restricted-PSS assertion in helm-check (it runs regardless — gate
policy), and image-scan defaults empty
`.trivyignore`/`.grype.yaml` when the consumer doesn't carry them.
`helm-check` owns runner `uv` before either the consumer `ci-secctx` or bundled
PSS step; Makefile targets must not assume the caller preinstalled it.

### C. Caller-lint rule ids and notices

When `require_hardened_bases` is true (default), `caller-lint` also fails
closed if neither Chainguard (`CGR_PULL_*`) nor Iron Bank (`IRONBANK_*`)
complete pull credential pairs are present, so docker/kind never start on a
missing-credentials run. Rule ids:
`no-secrets-inherit`, `no-caller-concurrency`, `unknown-input`, `type-mismatch`,
`missing-secret-map`, `image-values-mismatch`, `unreadable-caller`, the
**blocking** contract validators `ci-contract-file`, `ci-contract-target`,
`ci-contract-manifest` (a missing optional `ci-secctx` target is a notice),
plus the `smoke_secrets` validators `smoke-secrets-json`, `smoke-secrets-name`,
`smoke-secrets-duplicate`, `smoke-secrets-literals`. The non-failing style
notice `smoke-secrets-format` fires when an array is packed onto one quoted
line — prefer a multiline YAML `|` block (see [INPUTS.md](INPUTS.md)). Rules
skipped for a stated reason announce on stderr
(`notice: skip: image-values-mismatch: --consumer-root not given`); with a
consumer checkout supplied, file-touching rules announce
`notice: active: <rule>: checked <path>`. The image-values rule reads the
values-local path from the manifest's `chart.values_local` and parses it as
YAML: a string `image` equal to `scan_image`, or `repository` + `tag` that
join to it, both pass; a comment-only mention does not.

### D. Job order and fail-fast (Actions minutes)

Gate jobs are ordered so cheap failures stop expensive work from starting:

1. **`caller-lint`** — caller contract + (when `require_hardened_bases`) hardened-registry secret presence.
2. **`helm-check`** (unless `image_only`) — helm lint/template + restricted PSS — in parallel with SAST/secrets-scan.
3. **`build`** — `make ci-build` per manifest image (matrixed) — **needs** successful `caller-lint` and, when helm runs, successful `helm-check`. A PSS failure does not start multi-minute image builds.
4. **`cluster-smoke` / `image-scan`** — need a successful `build` (all matrix
   legs, primary + extras).

This is DAG `needs:` wiring, not in-job cancellation. Prior runs on the same ref are still cancelled by workflow `concurrency:`.

### E. Why scan the shared umbrella repo at all?

Each usecase repo already builds and scans its own images, so a gate run on
`c3cdao-apps` is not primarily an image scan — image and SAST results there
largely duplicate the source repos' runs. When onboarded, its purpose is a
left-shifted final integration check on the composed umbrella chart before
handoff to the SecondFront / Game Warden vendor pipeline: umbrella-level values
overrides can silently regress a subchart's securityContext/PSS posture,
co-installed subcharts can conflict at deploy time, and the umbrella repo's own
files (prod values, env samples) need their own secrets scan that no subchart
repo covers. In short: a deliberately redundant "scan of already-scanned
subcharts" that catches integration-time regressions before the vendor pipeline
does. (A secondary rationale — vendor scanning is billed per chart, so gating
one umbrella chart is cheaper than N subcharts — is plausible but unconfirmed;
verify with SecondFront before relying on it.)

### F. Consumer onboarding blockers (checklist)

Gate product gaps for full-cluster smoke are tracked as [#23](https://github.com/c3-joshchiu/c3cdao-ci-scans/issues/23)
(manifest-extras kind-load) and [#24](https://github.com/c3-joshchiu/c3cdao-ci-scans/issues/24)
(smoke Secrets contract). **Consumer-owned** readiness gaps that repeatedly turn
Security Scan red — restricted PSS on charts, hardened-base Dockerfiles, registry
pull-secret pairs, and the canary-before-fleet process — live in
[#27](https://github.com/c3-joshchiu/c3cdao-ci-scans/issues/27). Point adoption
PRs there instead of inventing per-repo mystery reds; do not fan out an 8-repo
Security Scan matrix until one canary's real fail mode is fixed.

### G. Updating the reusable workflow (maintainer)

`.github/workflows/reusable-security-gate.yml` is hand-maintained. When the
upstream source-of-truth workflow it was derived from changes, port the relevant
diff manually and re-tag:

```bash
git commit -am "update reusable-security-gate.yml"
git tag v0.x.x && git push --tags
```

Pin consumers at `@v0.x.x` instead of `@main`.

The `contract-extract` pre-commit hook regenerates
`contract/security-gate.schema.json` and `docs/INPUTS.md` whenever the reusable
workflow changes, and CI fails on drift even when the hook is skipped — the
contract is derived output, never hand-edited.

ci-scans is public; if it ever goes private, this repo (the callee) must allow
cross-repo reusable-workflow access (Settings → Actions → Access) before
consumers can call it.

### H. Consumer build contract

The only build path (since v0.5.0). Consumer build knowledge (image builds,
secctx assertion, smoke prerequisites, chart/health metadata) lives in a
consumer-owned `Makefile.ci` (`contract_file`) exposing `ci-manifest` /
`ci-build` / `ci-secctx` / `ci-smoke-env`; `make ci-manifest` is the single
source of truth for the containers list and chart/health sections. The
bundled restricted-PSS assertion stays in-gate (gate policy). Caller lint
validates the contract file **blocking** (`ci-contract-file`,
`ci-contract-target`, `ci-contract-manifest`; a missing optional `ci-secctx`
is a notice). Interface, env vars, and the manifest JSON shape:
[CI-CONTRACT.md](CI-CONTRACT.md); reference implementation:
`templates/consumer/Makefile.ci`.

### I. Note on path efficiency

The reusable gate runs all scan jobs on every PR (full gate). Path-based skipping
(`detect-changes`) can be added later without changing the onboarding model.
