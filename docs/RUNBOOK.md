# Onboarding runbook

Copy-and-own onboarding for the c3cdao-ci-scans security gate, as a
sequential walkthrough: make the repo conform, copy the caller, edit
`with:`, set the four secrets, create the ruleset, pilot on a scratch
branch, then promote to trunk and enforce. Every step names who runs it
(**consumer** = the gated repo's team; **operator** = whoever holds admin
on the consumer repo) and states the observable outcome.

The consumer contract itself — what the gate derives from your Compose
file, Dockerfiles, and chart, and the full lint rule table — is
[CI-CONTRACT.md](CI-CONTRACT.md). The `with:` field reference is
[INPUTS.md](INPUTS.md). Requirement traceability is
[REQUIREMENTS-MAP.md](REQUIREMENTS-MAP.md). Reference material — reading
the BOM, the registry login matrix, lint rule ids, the smoke catalog,
job ordering — lives in the [appendix](#appendix-reference).

## Branch conventions (decide first)

Pilot/scratch branch naming depends on the repo shape. Decide before step
7; steps 7–10 use these names.

| Repo shape | Convention |
|---|---|
| **Single-app usecase repo** (one app per repo) | Scan target branch is the **bare** name **`ci-scans`**. The helm-chart side mirrors this with a bare **`ci-chart`**. |
| **Shared umbrella repo** (many usecases integrated in one repo) | A token is required to avoid collisions: **`ci-chart-<usecasename>`** so each usecase's chart branch coexists. |
| **Canary (trigger) branch** (all shapes) | The canonical name **`ci-scans-canary`** — a trigger-only branch cut off the scan target head (step 8). |

Keep a single hyphenated branch as the scan target; a slash form like
`ci-scans/...` is non-conforming. Why the shared umbrella repo is scanned
at all: [appendix F](#f-why-scan-the-shared-umbrella-repo-at-all).

## 0. Make the repo conform (consumer)

The gate derives everything from committed files, so onboarding starts in
your own tree, not in CI config. Check each bullet against
[CI-CONTRACT.md](CI-CONTRACT.md); the lint rule in parentheses is what
blocks when the bullet is false.

- One canonical Compose file at the repo root; every release image is a
  `build:` service with an explicit literal `image:` tag — no `:latest`,
  no `${...}` (`compose-missing`, `compose-no-builds`,
  `compose-image-tag`) — and a `healthcheck:` (`compose-healthcheck`).
  Local-only services carry `profiles: [local]`; at most ten non-local
  build services (`matrix-cap`); `linux/amd64` only (`compose-platform`).
- Downloaded runtime dependencies (PostgreSQL, an identity provider the
  chart deploys) are `image:`-only services declaring
  `x-downloaded-dependency` with a `chart-tag` and an in-image `@sha256:`
  digest pin (`dependency-shape`).
- Build args are committed literal mappings — no host pass-through, no
  secret-like names, no `build.secrets`/`build.ssh`
  (`build-input-explicit`); every build context has a `.dockerignore`
  with the four literal lines `.env`, `*.pem`, `*.key`, `*credentials*`
  (`build-context-excludes`); every Dockerfile declares
  `ARG BUILDER_IMAGE` and `ARG RUNTIME_IMAGE` (`hardened-args`); the
  Compose file resolves under `docker buildx bake --print`
  (`bake-resolve`).
- The chart renders with your local values; every workload container has
  a `readinessProbe` (`chart-readiness`); exactly one container exposes an
  HTTP readiness target through a Service whose `targetPort` matches the
  probe port (`smoke-target`); every scheduled image is built or a
  declared dependency (`ship-set`; unscheduled built tags warn via
  `built-unscheduled`).
- Databases follow the decoupled standard (ADR-08): the app reads
  `DATABASE_URL` from the `app-database-url` Secret. Compose provides a
  local container; the gate's `postgres-pgvector` module provides it at
  smoke; production provides a managed service. No chart-bundled database.

Tooling: `gh` (authenticated), `uv`, and **admin** on the consumer repo
(secrets and rulesets).

**You should see:** every bullet true for your repo; the operator holds
admin, and `gh`/`uv` are available on the operator laptop.

## 1. Copy the caller — commit 1 (consumer)

```bash
cd <consumer-repo>
mkdir -p .github/workflows
cp <ci-scans-clone>/templates/callers/security-gate.yml .github/workflows/security-gate.yml
```

One file; you own it from here — no tooling ever rewrites it. There is
nothing else to copy: the gate derives build facts from the files step 0
made conform.

**You should see:** `.github/workflows/security-gate.yml` in the consumer
repo, committed as its own commit.

## 2. Edit `with:` and pin the version — commit 2 (consumer)

Every `with:` line in the template carries an inline provenance comment
naming where its value comes from. Edit each to match, and set your
trigger branches under `on.pull_request.branches`.

Three invariants the caller lint enforces — do not break them:

- Keep the job id `security-scan`. It is half of the required check
  context `security-scan / Security Gate`; renaming it silently un-gates
  merges.
- Pass secrets **explicitly**
  (`CGR_PULL_TOKEN: ${{ secrets.CGR_PULL_TOKEN }}`), never the `inherit`
  form (`no-secrets-inherit`) — `inherit` only works when caller and
  callee share an org/enterprise; across owners it silently passes
  nothing.
- Pin the gate by a **full 40-hex commit SHA** (`gate-ref-pin`), recording
  the release tag as a trailing comment:

```yaml
uses: c3-e/c3cdao-ci-scans/.github/workflows/reusable-security-gate.yml@<40-hex sha>  # v0.6.0
```

**You should see:** every `with:` value traced to its provenance source,
trigger branches set, the job id still `security-scan`, secrets explicit,
and the ref pinned to a 40-hex SHA.

## 3. Lint the caller locally (consumer)

Run the same fail-closed lint the gate's plan job runs, before you push:

```bash
uv run <ci-scans-clone>/scripts/lib/lint_caller.py \
  .github/workflows/security-gate.yml \
  --consumer-root .
```

Every finding prints a rule id and a remediation link into the
[CI-CONTRACT.md rule table](CI-CONTRACT.md#rule-table). Without
`--consumer-root` only the caller-structure rules run; with it the full
Compose/Dockerfile/chart convention pipeline runs (chart rules need
`helm`; bake resolution needs `docker buildx`). The rule-id list:
[appendix C](#c-lint-rule-ids-and-remediation).

Your caller must also grant the permissions the reusable workflow needs —
`pull-requests: write`, `actions: write` (the caller is the ceiling) —
and must not set `concurrency:` (the reusable workflow owns the group).

**You should see:** `OK: <caller>: caller lint clean`.

## 4. Set the four secrets — one-time (operator)

```bash
gh secret set CGR_PULL_TOKEN     --repo <owner>/<repo>
gh secret set CGR_PULL_USERNAME  --repo <owner>/<repo>
gh secret set IRONBANK_TOKEN     --repo <owner>/<repo>
gh secret set IRONBANK_USERNAME  --repo <owner>/<repo>
```

These four names are exactly what the workflow declares. UI alternative:
Settings → Secrets and variables → Actions → New repository secret.

| Secret | Job |
|--------|-----|
| `CGR_PULL_TOKEN`, `CGR_PULL_USERNAME` | plan + build legs — Chainguard (`cgr.dev`) login |
| `IRONBANK_TOKEN`, `IRONBANK_USERNAME` | SonarQube ephemeral + plan/build Iron Bank (`registry1.dso.mil`) login — runs **alongside** Chainguard when both are set |

How the two logins interact is reference material:
[appendix B](#b-hardened-base-registry-login-matrix).

**You should see:** all four names listed under the repo's Actions
secrets.

## 5. Create the ruleset — disabled (operator)

From the ci-scans clone. `configs/local/` is gitignored — real ops
configs (org names, local paths) live there.

```bash
cp configs/examples/example.yaml configs/local/<repo>.yaml
# edit target.* / ci_scans.* / ruleset.*

./scripts/setup-ruleset.sh --config configs/local/<repo>.yaml            # create, disabled
```

`setup-ruleset.sh` creates the `security-scan-gates` ruleset **disabled**
by default (safe rollout). Private repos need a paid org/enterprise plan
to enforce. Add `--dry-run` to preview the API payload without writing.

The ops YAML is schema-validated at load and carries **operations-only**
fields: `target`, `ci_scans`, `ruleset`, plus optional `workflows`. Gate
values live in your caller's `with:`, not here.

If piloting on a scratch branch, scope the ruleset now:
`target.trunk_branches: [ci-scans]` and `ruleset.target_branch: ci-scans`
(use your name from the
[branch conventions](#branch-conventions-decide-first)).

**You should see:** the `security-scan-gates` ruleset in the consumer
repo's Settings → Rules → Rulesets, in the **disabled** state.

## 6. Enable the ruleset (operator)

```bash
./scripts/setup-ruleset.sh --config configs/local/<repo>.yaml --enable   # enforce
```

**You should see:** the ruleset flip to **active**, and
`security-scan / Security Gate` listed as a required status check on the
target branch.

## 7. Set up the scratch-branch pilot (consumer + operator)

To pilot on a shared repo without touching its real trunk, cut a scratch
branch and scope both the trigger and the ruleset to it:

- caller: `on.pull_request.branches: [ci-scans]` (single-app repo)
- ops YAML: `target.trunk_branches: [ci-scans]` and
  `ruleset.target_branch: ci-scans` — re-run step 6 if you re-target

Full scratch-branch walkthrough:
[CI CD Workflow runbook](https://c3energy.atlassian.net/wiki/spaces/CCA/pages/10910040079/).

**You should see:** the scratch branch pushed, the caller's trigger scoped
to it, and the ruleset targeting it.

## 8. Trigger the gate with a canary PR (consumer)

The scan target branch never receives direct pushes to trigger the gate —
open a trigger-only PR into it from the canonical canary branch
**`ci-scans-canary`**:

1. Cut `ci-scans-canary` off the `ci-scans` head and add a trivial marker
   commit (e.g. a `.ci-scans-canary` file).
2. Open a PR `ci-scans-canary` → `ci-scans` titled
   `canary: security-gate @<tag>`. The `on.pull_request.branches:
   [ci-scans]` trigger fires the gate; existing rules on the repo's real
   trunk are never touched.
3. The canary PR is **never merged** — it exists only to trigger.
   Re-trigger after a caller change by merging the updated `ci-scans` head
   into `ci-scans-canary` (`gh api -X POST repos/<owner>/<repo>/merges -f
   base=ci-scans-canary -f head=ci-scans`). Keep the PR a **draft**
   (`gh pr ready <n> --undo`): `pull_request` triggers fire on drafts just
   the same, and draft status signals "trigger vehicle, not a merge
   candidate".
4. Comment the per-job results table and run URL on the canary PR as
   evidence.

**Fleet testing:** canary **one** consumer through a pin/secrets change
before fanning out many repos.

**You should see:** the check context **`security-scan / Security Gate`**
appear on the canary PR and go green. The gate's `plan` job runs first:
it lints your caller and repo shapes fail-closed, then publishes the
[BOM](#a-reading-the-published-bom) before any build starts. Job order:
[appendix E](#e-job-order-and-fail-fast-actions-minutes).

List the live check names on a PR head:

```bash
gh api repos/<owner>/<repo>/commits/<sha>/check-runs --jq '.check_runs[].name'
```

## 9. Promote to trunk (consumer + operator)

When the pilot is green:

1. In the caller, point the trigger branches at the trunk
   (`on.pull_request.branches: [main]`).
2. Re-target the ruleset: drop `ruleset.target_branch` from the ops YAML
   (or set it to the default branch) and re-run
   `./scripts/setup-ruleset.sh --config configs/local/<repo>.yaml
   --enable`.
3. Confirm the caller's `uses:` pin is the released 40-hex SHA.

**You should see:** real PRs into the default branch carry the
`security-scan / Security Gate` required check.

## 10. Clean up the scratch branches (consumer)

1. Close the canary PR (never merged — step 8).
2. Delete the canary branch and the scratch scan-target branch:

```bash
git push origin --delete ci-scans-canary
git push origin --delete ci-scans
```

Only after step 9 re-targeted the ruleset away from the scratch branch; a
ruleset targeting a deleted literal ref gates nothing.

**You should see:** no `ci-scans*` branches left on the consumer repo,
and the canary PR closed.

## 11. Flip enforcement to blocking (operator)

The enforcement model has two knobs:

- **Ruleset enable** (per-consumer): step 6 makes
  `security-scan / Security Gate` a required check.
- **`SECURITY_SCAN_BLOCKING` repo variable** (gate-internal): hard-fail
  posture for cluster-smoke and image-scan findings. Until it is `true`
  they warn instead of failing; a skipped/cancelled/errored blocking job
  still fails the gate. Flipping it to `true` is the **final** acceptance
  step — see [REQUIREMENTS-MAP.md](REQUIREMENTS-MAP.md).

```bash
gh variable set SECURITY_SCAN_BLOCKING --body true --repo <owner>/<repo>
```

**You should see:** the repo variable set to `true`, and subsequent gate
runs hard-failing (not warning) on cluster-smoke / image-scan findings.

## Migrating from v0.5.x (consumer)

The v0.6 cutover is a hard major-version migration — the consumer contract
makefile path was removed, not deprecated:

1. Delete the contract makefile and its targets from your repo; the gate
   no longer reads them.
2. Make the repo conform (step 0): the Compose file, Dockerfiles, and
   chart now carry the facts the makefile used to declare.
3. Delete the removed inputs from your caller's `with:` — the
   `unknown-input` rule names each one; the replacement table is in
   [INPUTS.md](INPUTS.md#removed-inputs-v05--v06-migration).
4. Re-pin `uses:` to a v0.6 40-hex SHA and re-run step 3's local lint.

## Appendix (reference)

### A. Reading the published BOM

Every run's `plan` job publishes the derived Image BOM to the job summary
and the `plan-bom` artifact: the bake plan (`bake --print` JSON — target
name, dockerfile, context, args, tags) plus the gate's annotation document
(excluded services with reasons, declared dependencies with digest pins
and chart-facing tags, the derived smoke target, and provenance comments
for every field). A PR comment shows the scan-set diff whenever the
derived set differs from the base branch. To review what a commit will
scan: open its run's plan summary — or reproduce locally with
`docker buildx bake -f docker-compose.yml --print <targets>`, which is the
same resolver the gate pins.

Reviewers verifying a leg: each build leg re-prints its own target with
identical overrides and diffs it against the published plan, so plan and
execution cannot silently diverge.

### B. Hardened-base registry login matrix

Logins are **independent** (docker stores credentials per registry host).
Setting both `CGR_PULL_*` and `IRONBANK_*` authenticates **both** in one
run. The gate's posture is fail-closed: no complete credential pair means
the plan job blocks before docker or kind ever start — there is no public
fallback and no consumer-side escape hatch. Base images and the failover
order are gate-owned configuration; your Dockerfiles consume whatever the
gate resolves through the `BUILDER_IMAGE`/`RUNTIME_IMAGE` ARGs.

The gate authenticates only to `cgr.dev` and `registry1.dso.mil` and
scans images **as built with those gate-reachable bases**. Approved-image
/ OS-layer attestation for private-mirror or entitlement-unreachable
bases stays with the consumer IL5 / Game Warden pipeline.

### C. Lint rule ids and remediation

Every verdict names its rule and links a remediation anchor in the
[CI-CONTRACT.md rule table](CI-CONTRACT.md#rule-table). Convention rules
(fail-closed, run in `plan`): `compose-missing`, `compose-no-builds`,
`matrix-cap`, `compose-image-tag`, `compose-healthcheck`,
`dependency-shape`, `build-input-explicit`, `build-context-excludes`,
`compose-platform`, `bake-resolve`, `hardened-args`, `chart-readiness`,
`smoke-target`, `ship-set`, `smoke-resource-unknown`, plus the warn-only
`built-unscheduled`. Caller-structure rules: `gate-ref-pin`,
`no-secrets-inherit`, `missing-secret-map`, `unknown-input`,
`unreadable-caller`.

Remediation flow: read the verdict message (it names the offending
service/file/workload), open the linked rule heading for the required
shape, fix the committed file, re-run the local lint from step 3.

### D. Smoke catalog contract

Smoke prerequisites are declared, not scripted: the caller's
`smoke_resources` CSV selects gate-owned modules that `cluster-smoke`
applies into the namespace **before** `helm install`, gating on each
module's readiness (a timeout fails naming the module). Catalog:

| Module | Provides |
|---|---|
| `postgres-pgvector` | pgvector Postgres + Service + the `app-database-url` Secret (→ `DATABASE_URL`, ADR-08) with fixture credentials only |
| `gateway-crds` | Gateway API CRDs, waited to Established |

A resource type not in the catalog is a ci-scans feature request, not a
consumer escape hatch (`smoke-resource-unknown`). Dependencies your chart
deploys itself are not catalog resources: declare them in Compose as
digest-pinned downloaded dependencies and let `helm install` deploy the
chart's own copy (ADR-07).

### E. Job order and fail-fast (Actions minutes)

Gate jobs are ordered so cheap failures stop expensive work from starting:

1. **`plan`** — fail-closed lint + registry login/failover + BOM + build
   matrix. Nothing scans until it passes.
2. **`helm-check`**, **`secrets-scan`**, **SAST** — parallel after plan;
   `build` legs also start in parallel (matrixed, `fail-fast: false`).
3. **`cluster-smoke`** — needs every build leg and helm-check;
   **`image-scan`** legs need build only, so smoke and scanning consume
   the same artifacts concurrently.
4. **`Security Gate`** — fan-in over all jobs with `if: always()`; the one
   required check, immune to dynamic matrix leg names.

This is DAG `needs:` wiring, not in-job cancellation. Prior runs on the
same ref are cancelled by workflow `concurrency:`.

### F. Why scan the shared umbrella repo at all?

Each usecase repo already builds and scans its own images, so a gate run
on the shared umbrella repo is not primarily an image scan. When
onboarded, its purpose is a left-shifted final integration check on the
composed umbrella chart before handoff to the vendor pipeline:
umbrella-level values overrides can silently regress a subchart's
securityContext/PSS posture, co-installed subcharts can conflict at deploy
time, and the umbrella repo's own files need their own secrets scan that
no subchart repo covers. (A secondary rationale — vendor scanning is
billed per chart, so gating one umbrella chart is cheaper than N
subcharts — is plausible but unconfirmed; verify with the vendor before
relying on it.)

### G. Updating the reusable workflow (maintainer)

`.github/workflows/reusable-security-gate.yml` is hand-maintained. Port
upstream diffs manually, re-tag, and publish the release SHA:

```bash
git commit -am "update reusable-security-gate.yml"
git tag v0.x.x && git push --tags
```

Consumers pin the 40-hex commit SHA of the release (the tag rides along
as a comment). The `with:` surface and the four secret names are guarded
by `tests/lib/test_workflow_scan_fanin.py`; the docs in this directory
are guarded by `tests/docs/` — a surface change fails CI until the docs
move with it.

ci-scans is public; if it ever goes private, this repo (the callee) must
allow cross-repo reusable-workflow access (Settings → Actions → Access)
before consumers can call it.

### H. Note on path efficiency

The reusable gate runs all scan jobs on every PR (full gate). Path-based
skipping can be added later without changing the onboarding model.
