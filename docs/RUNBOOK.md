# Onboarding runbook

Copy-and-own onboarding for the c3cdao-ci-scans security gate, as a
sequential walkthrough: make the repo conform, copy the caller, edit
`with:`, set the four secrets, create the ruleset, pilot on a scratch
branch, then promote to trunk and enforce. Every step names who runs it
(**consumer** = the gated repo's team; **operator** = whoever holds admin
on the consumer repo) and states the observable outcome.

The consumer contract itself (what the gate derives from your Compose
file, Dockerfiles, and chart, and the full lint rule table) is
[CI-CONTRACT.md](CI-CONTRACT.md). The `with:` field reference is
[INPUTS.md](INPUTS.md). Requirement traceability is
[REQUIREMENTS-MAP.md](REQUIREMENTS-MAP.md). Reference material (reading
the BOM, the registry login matrix, lint rule ids, the smoke catalog,
job ordering) lives in the [appendix](#appendix-reference).

## Branch conventions (decide first)

Pilot/scratch branch naming depends on the repo shape. Decide before step
7; steps 7–10 use these names.

| Repo shape | Convention |
|---|---|
| **Single-app usecase repo** (one app per repo) | Scan target branch is the **bare** name **`ci-scans`**. The helm-chart side mirrors this with a bare **`ci-chart`**. |
| **Shared umbrella repo** (many usecases integrated in one repo) | A token is required to avoid collisions: **`ci-chart-<usecasename>`** so each usecase's chart branch coexists. |
| **Canary (trigger) branch** (all shapes) | The canonical name **`ci-scans-canary`**: a trigger-only branch cut off the scan target head (step 8). |

Keep a single hyphenated branch as the scan target; a slash form like
`ci-scans/...` is non-conforming. Why the shared umbrella repo is scanned
at all: [appendix F](#f-why-scan-the-shared-umbrella-repo-at-all).

## 0. Make the repo conform (consumer)

The gate derives everything from committed files, so onboarding starts in
your own tree, not in CI config. Check each bullet against
[CI-CONTRACT.md](CI-CONTRACT.md); the lint rule in parentheses is what
blocks when the bullet is false.

- One canonical Compose file at the repo root; every release image is a
  `build:` service with an explicit literal `image:` tag (no `:latest`,
  no `${...}` (`compose-missing`, `compose-no-builds`,
  `compose-image-tag`) and a `healthcheck:` (`compose-healthcheck`).
  Local-only services carry `profiles: [local]`; at most ten non-local
  build services (`matrix-cap`); `linux/amd64` only (`compose-platform`).
- Downloaded runtime dependencies (PostgreSQL, an identity provider the
  chart deploys) are `image:`-only services declaring
  `x-downloaded-dependency` with a `chart-tag` and an in-image `@sha256:`
  digest pin (`dependency-shape`).
- Build args are committed literal mappings: no host pass-through, no
  secret-like names, no `build.secrets`/`build.ssh`
  (`build-input-explicit`); every build context has a `.dockerignore`
  with the four literal lines `.env`, `*.pem`, `*.key`, `*credentials*`
  (`build-context-excludes`); the Compose file resolves under
  `docker buildx bake --print` (`bake-resolve`).
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

## 1. Copy the caller: commit 1 (consumer)

```bash
cd <consumer-repo>
mkdir -p .github/workflows
cp <ci-scans-clone>/templates/callers/security-gate.yml .github/workflows/security-gate.yml
```

One file; you own it from here. No tooling ever rewrites it. There is
nothing else to copy: the gate derives build facts from the files step 0
made conform.

**You should see:** `.github/workflows/security-gate.yml` in the consumer
repo, committed as its own commit.

## 2. Edit `with:` and pin the version: commit 2 (consumer)

Every `with:` line in the template carries an inline provenance comment
naming where its value comes from. Edit each to match, and set your
trigger branches under `on.pull_request.branches`.

Three invariants the caller lint enforces; do not break them:

- Keep the job id `security-scan`. It is half of the required check
  context `security-scan / Security Gate`; renaming it silently un-gates
  merges.
- Pass secrets **explicitly**
  (`CGR_PULL_TOKEN: ${{ secrets.CGR_PULL_TOKEN }}`), never the `inherit`
  form (`no-secrets-inherit`); `inherit` only works when caller and
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

Your caller must also grant the permissions the reusable workflow needs,
`pull-requests: write`, `actions: write` (the caller is the ceiling),
and must not set `concurrency:` (the reusable workflow owns the group).

**You should see:** `OK: <caller>: caller lint clean`.

## 4. Set the four secrets: one-time (operator)

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
| `CGR_PULL_TOKEN`, `CGR_PULL_USERNAME` | plan + build legs: Chainguard (`cgr.dev`) login (skipped if your caller declares `hardened_base_registry: ironbank`) |
| `IRONBANK_TOKEN`, `IRONBANK_USERNAME` | SonarQube ephemeral + plan/build Iron Bank (`registry1.dso.mil`) login (skipped if your caller declares `hardened_base_registry: chainguard`); runs **alongside** Chainguard when both are set and `hardened_base_registry: both` (default) |

How the two logins interact, and how to declare the single registry tier
your Dockerfile actually pins to, is reference material:
[appendix B](#b-hardened-base-registry-login-matrix).

**You should see:** all four names listed under the repo's Actions
secrets.

## 5. Create the ruleset, disabled (operator)

From the ci-scans clone. `configs/local/` is gitignored; real ops
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
  `ruleset.target_branch: ci-scans`; re-run step 6 if you re-target

Full scratch-branch walkthrough:
[CI CD Workflow runbook](https://c3energy.atlassian.net/wiki/spaces/CCA/pages/10910040079/).

**You should see:** the scratch branch pushed, the caller's trigger scoped
to it, and the ruleset targeting it.

## 8. Trigger the gate with a canary PR (consumer)

The scan target branch never receives direct pushes to trigger the gate;
open a trigger-only PR into it from the canonical canary branch
**`ci-scans-canary`**:

1. Cut `ci-scans-canary` off the `ci-scans` head and add a trivial marker
   commit (e.g. a `.ci-scans-canary` file).
2. Open a PR `ci-scans-canary` → `ci-scans` titled
   `canary: security-gate @<tag>`. The `on.pull_request.branches:
   [ci-scans]` trigger fires the gate; existing rules on the repo's real
   trunk are never touched.
3. The canary PR is **never merged**; it exists only to trigger.
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

1. Close the canary PR (never merged, step 8).
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
  step; see [REQUIREMENTS-MAP.md](REQUIREMENTS-MAP.md).

```bash
gh variable set SECURITY_SCAN_BLOCKING --body true --repo <owner>/<repo>
```

**You should see:** the repo variable set to `true`, and subsequent gate
runs hard-failing (not warning) on cluster-smoke / image-scan findings.

## 12. Suppress dispositioned CVEs with OpenVEX (consumer, optional)

The image-scan legs consume a consumer-committed [OpenVEX](https://github.com/openvex/spec)
document: findings your team has formally dispositioned (`not_affected` /
`fixed`, with a justification) are filtered out of the Trivy and Grype
image scans, with the applied document preserved in every run's
[security export bundle](#i-security-export-bundle-reference). Nothing is
required — without the file, scans behave exactly as before.

**This is the only sanctioned suppression path.** A committed
`.trivyignore` or `.grype.yaml` with a real entry blocks in `plan`
(`suppression-format`) — those formats carry no justification, so the
gate no longer honors them. Migrate any existing entries to OpenVEX
statements below.

1. Commit `.openvex/templates/main.openvex.json` at your repo root (the
   `vexctl generate --init` layout). Author statements with
   `vexctl add` — pin `vexctl >= v0.3.0` (older releases silently keep
   only the last of repeated `--product` flags, which reintroduces the
   single-form footgun below).
2. **Verdicts only.** A statement is a human disposition with a
   justification — never bulk `under_investigation`, never
   scanner-derivable data, and never written by a pipeline. CI consumes
   the document; it must not author or upgrade it.
3. **Product PURL rules** — matching failures are silent (the statement
   just never suppresses), so all of these matter:
   - No `tag=` qualifier, and no `arch=` qualifier — either silently
     breaks matching (an `arch=arm64` PURL authored on Apple Silicon
     matches nothing on the gate's `amd64` runners).
   - **Gate-built images (the normal case): author against the gate's
     job-local registry identity.** The gate publishes every built image
     to `localhost:5000/<name>` before scanning, because Grype derives
     VEX product identity exclusively from registry digests — a plain
     locally-built image has none, and every PURL form silently no-ops
     on the Grype leg. Every statement needs **both** scanners' forms
     via repeated `--product`: Trivy includes the image name, Grype
     excludes it:

     ```bash
     vexctl add --in-place .openvex/templates/main.openvex.json \
       --product "pkg:oci/<name>?repository_url=localhost:5000/<name>" \
       --product "pkg:oci/<name>?repository_url=localhost:5000" \
       --vuln CVE-XXXX-NNNNN --status not_affected \
       --justification <enum>
     ```

     `<name>` is your Compose service's image name (e.g. `myapp` for
     `image: myapp:local`). The per-build digest is recorded in the
     export bundle's `metadata.json` (`image.scan_ref` + `image.digest`)
     — the committed product stays version-less so the disposition
     survives rebuilds.
   - Externally-delivered images scanned outside this gate (e.g. a
     production artifact pulled from its real registry, not the gate's
     job-local one) keep their **real registry forms** — the rule is
     always "the `repository_url` each scanner computes at scan time".
     See "Worked example: externally-delivered images" below.
   - **Older gate pins (before the job-local registry): Grype
     suppression is impossible for gate-built images.** Any committed
     product form silently no-ops on the Grype image leg; only Trivy
     matches. Re-pin before relying on Grype-side VEX.
4. Add a `CODEOWNERS` entry for `.openvex/` so every disposition change
   gets a named security reviewer.

Known limit: the Grype **image-SBOM** leg cannot consume VEX (the SBOM's
root component carries no PURL to match) — the Trivy and Grype **image**
legs are the suppression surface, and they cover the same packages.

**You should see:** the dispositioned CVE absent from the Trivy and Grype
image-scan tables on the next run, and the run's
`security-export-<service>-<short-sha>` artifact carrying your document as
`vex-applied.openvex.json` with `metadata.json` showing
`"vex": {"source": "consumer"}`.

### 12a. Worked example: externally-delivered images

Producing a standalone VEX document for an image scanned *outside* this
gate (e.g. a signed release artifact handed to a downstream receiver
alongside its SBOM) hits two footguns the in-gate case above doesn't,
verified end to end (`c3cdao-landing`, PR #4, against the real
`registry.gamewarden.io/cdao/landing` delivered artifact — vexctl 0.4.4,
syft 1.50.0, trivy 0.71.2, grype 0.114.0):

1. **Trivy has zero vulnerability data for RHEL10/UBI10-based images**
   (any Iron Bank base built on `ubi10-minimal`) — a confirmed upstream
   gap ([trivy discussions #10753](https://github.com/aquasecurity/trivy/discussions/10753),
   [#10194](https://github.com/aquasecurity/trivy/discussions/10194);
   [trivy-db#435](https://github.com/aquasecurity/trivy-db/issues/435)).
   Trivy detects the OS and loads the package list, then silently
   matches zero CVEs — no warning, indistinguishable from a genuinely
   clean image. Confirmed live on the delivered `cdao/landing` artifact:
   Trivy reports 0 findings, grype (whose `rhel` provider sources
   directly from Red Hat's own CVE feed) reports 277 on the same image.
   **Always run grype alongside Trivy on any RHEL10/UBI10-based image and
   union both CVE lists** — a Trivy-only disposition doc silently claims
   full coverage while missing everything Trivy can't see.
2. **Trivy and grype compute a *different* `repository_url` PURL
   qualifier for the same image** — the sharpest footgun here, verified
   against the delivered artifact:

   ```
   # Trivy: full repository path, including the image name
   pkg:oci/landing@sha256:<digest>?arch=amd64&repository_url=registry.example.com%2Fns%2Flanding

   # grype: repository path WITHOUT the image name (registry + namespace only)
   pkg:oci/landing@sha256:<digest>?repository_url=registry.example.com/ns
   ```

   A statement written for one scanner's form silently does not match
   the other. **Give every statement both product forms** (`vexctl add`
   takes `--product` as a repeatable flag):

   ```bash
   vexctl add --in-place main.openvex.json \
     --product "pkg:oci/landing?repository_url=registry.example.com/ns/landing" \
     --product "pkg:oci/landing?repository_url=registry.example.com/ns" \
     --vuln CVE-XXXX-NNNNN --status not_affected \
     --justification vulnerable_code_not_in_execute_path
   ```

   Confirmed by direct A/B test on the delivered image: a single-product
   statement using grype's form suppressed all 6 matches for the test
   CVE (`277 → 271` findings); the same statement using only Trivy's form
   suppressed 0. The dual-product statement suppressed all 6.

   Also: never add a `tag=` qualifier (a qualifier absent from the
   scanner's own computed PURL is treated as a mismatch — pin the
   digest, `@sha256:...`, instead), and never use a bare `pkg:oci/<name>`
   with no `repository_url` (matches *any* image with that name, on any
   registry — too broad).
3. **Digest-pinned vs. tagless product PURLs pick the failure mode for
   claims after a rebuild** — decide once, per repo, and write it down:
   - **Tagless** (`repository_url` only, no digest): claims carry over
     to the new image automatically. Fails *open* — a `not_affected`
     justification can silently outlive the conditions it was written
     under; nothing re-checks it. This is what the in-gate
     `localhost:5000/<name>` form above uses, by necessity (the
     job-local digest is different every run).
   - **Digest-pinned** (`@sha256:...` in the product PURL): every
     rebuild orphans all claims until someone re-adds them. Fails
     *closed* — safer, more churn. Appropriate for a versioned,
     externally-delivered artifact where a human already re-triages
     each release.

**Generating the full deliverable doc** (triaged template statements +
`under_investigation` for every remaining scanner finding, unioning both
scanners per point 1 above):

```bash
PRODUCT_PURL_TRIVY="pkg:oci/<name>?repository_url=<registry>/<namespace>/<name>"
PRODUCT_PURL_GRYPE="pkg:oci/<name>?repository_url=<registry>/<namespace>"
OUT=<name>-<version>.vex.json   # ships alongside the SBOM; not committed
vexctl generate "$PRODUCT_PURL_TRIVY" --templates .openvex/templates \
  --author "<org> — <repo> maintainers" --file "$OUT"
{
  jq -r '[.Results[]?.Vulnerabilities[]?.VulnerabilityID] | unique | .[]' findings-trivy.json
  jq -r '[.matches[]?.vulnerability.id] | unique | .[]' findings-grype.json
} | sort -u \
  | while read cve; do
      grep -q "\"$cve\"" "$OUT" \
        || vexctl add --in-place "$OUT" \
             --product "$PRODUCT_PURL_TRIVY" --product "$PRODUCT_PURL_GRYPE" \
             --vuln "$cve" --status under_investigation;
    done
```

The generated per-image doc is the deliverable (ships next to the SBOM —
shared drive, PR attachment, release assets); regenerate it, never hand-edit
it, never commit it. Only the template (`main.openvex.json`) is committed.

## Appendix (reference)

### A. Reading the published BOM

Every run's `plan` job publishes the derived Image BOM to the job summary
and the `plan-bom` artifact: the bake plan (`bake --print` JSON: target
name, dockerfile, context, args, tags) plus the gate's annotation document
(excluded services with reasons, declared dependencies with digest pins
and chart-facing tags, the derived smoke target, and provenance comments
for every field). To review what a commit will scan: open its run's plan
summary, or reproduce locally with
`docker buildx bake -f docker-compose.yml --print <targets>`, which is the
same resolver the gate pins.

On `pull_request`-triggered runs, `export-bundle` also posts (or, on a
later push to the same PR, updates in place — see
[Appendix I](#i-security-export-bundle-reference)) a PR comment
summarizing each built service's scan results. A scan-set *diff* against
the base branch's derived BOM is a separate, larger feature and not yet
implemented.

Reviewers verifying a leg: each build leg re-prints its own target with
identical overrides and diffs it against the published plan, so plan and
execution cannot silently diverge.

The build leg's bake execution (not the parity re-print) also sets a
per-target GitHub Actions cache scope (`security-scan-<target>`) for
buildx layers, so parallel legs never collide or evict each other's
cache. On fork PRs, cache writes are read-only-scoped by GitHub Actions
and simply no-op — this is expected and not a failure.

### B. Hardened-base registry login matrix

Logins are **independent** (docker stores credentials per registry host).
Setting both `CGR_PULL_*` and `IRONBANK_*` authenticates **both** in one
run — when `hardened_base_registry` is left at its default `both`. The
gate's posture is fail-closed: no successful login among the attempted
registry(s) means the plan job blocks before docker or kind ever start;
there is no public fallback and no consumer-side escape hatch. Base
images and the failover order are gate-owned configuration for the
login/failover resolution action itself; the gate does not inject or
override any base-image build arg. Using a hardened base in `FROM` is the
consumer's own choice; the gate scans whatever the Dockerfile builds.

The gate authenticates only to `cgr.dev` and `registry1.dso.mil` and
scans images **as built with those gate-reachable bases**. Approved-image
/ OS-layer attestation for private-mirror or entitlement-unreachable
bases stays with the consumer IL5 / Game Warden pipeline.

**Declared tier (`hardened_base_registry`).** A live fleet survey found
pilots pin their Dockerfiles to exactly one hardened registry, never
both. Declaring `hardened_base_registry: chainguard` or `ironbank` (in
your caller's `with:`) makes the login step skip the other registry's
login attempt entirely — no credential check, no `docker login` call, no
retry/backoff burned against a registry your images never reference. The
default, `both`, attempts both logins exactly as before (unchanged
behavior for callers that don't set the input): with `both`, a failure on
one registry with a success on the other still passes (at-least-one
semantics); a failure on every *attempted* registry — one, in the scoped
cases, or both, in the default case — fails closed the same as today.

### C. Lint rule ids and remediation

Every verdict names its rule and links a remediation anchor in the
[CI-CONTRACT.md rule table](CI-CONTRACT.md#rule-table). Convention rules
(fail-closed, run in `plan`): `compose-missing`, `compose-no-builds`,
`matrix-cap`, `compose-image-tag`, `compose-healthcheck`,
`dependency-shape`, `build-input-explicit`, `build-context-excludes`,
`compose-platform`, `bake-resolve`, `chart-missing`,
`chart-undeclared`, `chart-resolve`, `chart-readiness`,
`smoke-target`, `ship-set`, `smoke-resource-unknown`,
`suppression-format`, plus the warn-only
`built-unscheduled`. Caller-structure rules: `gate-ref-pin`,
`gate-job-id`, `decoy-gate-job`, `no-secrets-inherit`, `missing-secret-map`,
`unknown-input`, `unreadable-caller`.

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

1. **`plan`**: fail-closed lint + registry login/failover + BOM + build
   matrix. Nothing scans until it passes.
2. **`helm-check`**, **`secrets-scan`**, **SAST**: parallel after plan;
   `build` legs also start in parallel (matrixed, `fail-fast: false`).
3. **`cluster-smoke`**: needs every build leg and helm-check;
   **`image-scan`** legs need build only, so smoke and scanning consume
   the same artifacts concurrently.
4. **`Security Gate`**: fan-in over all jobs with `if: always()`; the one
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
no subchart repo covers. (A secondary rationale, vendor scanning is
billed per chart, so gating one umbrella chart is cheaper than N
subcharts, is plausible but unconfirmed; verify with the vendor before
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
are guarded by `tests/docs/`; a surface change fails CI until the docs
move with it.

ci-scans is public; if it ever goes private, this repo (the callee) must
allow cross-repo reusable-workflow access (Settings → Actions → Access)
before consumers can call it.

### H. Note on path efficiency

The reusable gate runs all scan jobs on every PR (full gate). Path-based
skipping can be added later without changing the onboarding model.

### I. Security export bundle reference

Every image-scan matrix leg uploads `security-export-<service>-<short-sha>`
(repo default artifact retention; uploads even when a blocking scan
fails). Download with
`gh run download <run-id> -p 'security-export-*'`. Contents:

| File | What it is |
| --- | --- |
| `sbom-image.cdx.json` | CycloneDX SBOM of the scanned image (same artifact the SBOM legs consume) |
| `trivy-image.json` | Trivy image findings, JSON, same severity filter and suppression surface as the gating table scan |
| `grype-image.json` | Grype image findings, JSON, same config and VEX surface as the gating table scan |
| `vex-applied.openvex.json` | The OpenVEX document exactly as applied — your committed template, or the gate's empty-statements default |
| `metadata.json` | `image` (tag + `scan_ref`, the job-local-registry reference the scanners actually scanned + registry digest), `blocking` flag, `vex.source` (`consumer` / `empty-default`), `scanners` (Trivy + Grype versions and vulnerability-DB metadata), `gate` (workflow ref + sha), `run` (caller sha + run id) |

Scan results are only interpretable next to the exact VEX statements that
were applied — the bundle is self-contained so an auditor needs nothing
else from the run.

**Combined download.** A run with N built services produces N of the
per-service bundles above, plus `sbom-source` and `plan-bom` — several
separate artifacts to click through one at a time in the Actions UI
(there is no "download all" button). The `export-bundle` job (`if:
always()`, needs `plan` + `image-scan`) re-packages exactly those three
artifact kinds — every `security-export-<service>-<short-sha>`,
`sbom-source`, `plan-bom` — into one combined
`security-export-full-<short-sha>` artifact, each service's files kept in
its own subdirectory (no `metadata.json`-name collisions). It is
convenience-only: not a required check, excluded from `security-gate`'s
`needs:` so an assembly failure (e.g. zero image-scan legs ran) can never
block the gate, and it changes nothing about the per-service bundles
themselves.

**PR comment.** On `pull_request`-triggered runs only (never
`merge_group`/`schedule`/`workflow_dispatch`), `export-bundle` also
posts a comment on the triggering PR summarizing, per built service, the
Trivy and Grype High+Critical finding counts (read straight from the
bundle's `trivy-image.json`/`grype-image.json`) and the VEX source
(`consumer` / `empty-default`, from `metadata.json`), plus a link to the
run page (`.../actions/runs/<run_id>` — the Artifacts list, including the
consolidated bundle, lives there; there is no standalone
authenticated-free download link for an individual artifact) and the
consolidated artifact's name with a copy-paste
`gh run download <run_id> -n security-export-full-<short-sha>` line. A
hidden `<!-- security-export-summary -->` marker lets the job find its
own prior comment on the same PR and `PATCH` it instead of posting a new
one on every push. This is commentary only: both the comment-body and
comment-posting steps are `continue-on-error: true`, gated on
`github.event_name == 'pull_request'`, and live in the same non-blocking
`export-bundle` job described above — a posting failure (e.g. a
permissions edge case) can never affect `Security Gate`.

**Pending-VEX-disposition report.** Appended to the same PR comment.
Read-only enumeration (`scripts/lib/pending_disposition_report.py`):
diffs each service's `trivy-image.json`/`grype-image.json` against that
service's own `vex-applied.openvex.json` (any statement covering a CVE
excludes it, regardless of status) and splits what's left by the
scanners' own fix metadata (Trivy `FixedVersion`, Grype `fix.state`)
into two tables — **remediate** (a fix already exists; bump the
dependency, don't disposition it) and **VEX-disposition candidates**
(no fix available; the only findings worth a human `vexctl add`). The
report never writes anything under `.openvex/` and never authors a
statement — it only reads bundle JSON already produced by the scan and
renders markdown. Same non-blocking posture as the rest of
`export-bundle`: `continue-on-error: true`, `pull_request`-gated only,
outside `security-gate`'s `needs:`.

