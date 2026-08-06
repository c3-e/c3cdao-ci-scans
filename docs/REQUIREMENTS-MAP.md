# Requirements map: gate jobs → Game Warden MVP CI spec

Every job in the reusable security gate, traced to the CI requirement it
fulfills and its current enforcement posture.

**Authoritative spec:** [Continuous Integration: Game Warden MVP](https://c3energy.atlassian.net/wiki/spaces/CCA/pages/10839163045/) (Confluence CCA `10839163045`).
**Runbook page:** [CI CD Workflow](https://c3energy.atlassian.net/wiki/spaces/CCA/pages/10910040079/) (Confluence CCA `10910040079`).

Source of truth for the job list is
`.github/workflows/reusable-security-gate.yml`. The
`test_every_job_mapped` drift guard fails if a job ships without a row
here.

| Job | Spec gate / requirement | Tool(s) | Target | Current posture | Alignment |
|---|---|---|---|---|---|
| `plan` | (scaffolding pre-flight, not a spec gate) | `lint_caller.py` (v0.6 convention rules) + `derive_bom.py` (`bake --print` plan + annotated BOM + build matrix) | caller config + Compose/Dockerfiles/chart | always fail-closed | aligned (guards the gate) |
| `build` | build images gate-side (`bake <target>`, matrixed over the plan's derived targets, `--set` platform pin only; the gate supplies no build args) + dual-registry login (CGR and/or Iron Bank) | Docker buildx bake + CGR/Iron Bank | images | always blocking | aligned |
| `secrets-scan` | Secrets detection | TruffleHog | source | job blocking; finding advisory until `SECURITY_SCAN_BLOCKING=true` | aligned |
| `sast-semgrep` | SAST | Semgrep | source | warn-only (`continue-on-error`) | intentional ramp |
| `sast-sonarqube` | SAST | SonarQube | source | warn-only (`continue-on-error`) | intentional ramp |
| `helm-check` | Helm lint + restricted-PSS | helm + PSS assert | chart | blocking unless `image_only` | aligned |
| `cluster-smoke` | kind deploy + health probe (catalog `smoke_resources` provisioned before install; probe target derived from the rendered chart) | kind + kubectl + helm | chart+images | skipped when `image_only`; else advisory until `SECURITY_SCAN_BLOCKING=true` | intentional ramp |
| `image-scan` | Image + SBOM vuln scan (matrixed over the same derived targets as `build`; one designated leg carries the source-SBOM scans) | Trivy (image+source SBOM) + Grype (image+source+image SBOM) | images + SBOM | advisory until `SECURITY_SCAN_BLOCKING=true` | aligned |
| `export-bundle` | (convenience, not a spec gate) re-package the per-service export bundles + `sbom-source` + `plan-bom` into one `security-export-full-<short-sha>` download | `actions/download-artifact` (pattern) + `actions/upload-artifact` | evidence artifacts | `if: always()`; excluded from `security-gate`'s `needs:`, so it can never block | aligned (never gates) |
| `security-gate` | aggregate required check | — | — | the one required check (`security-scan / Security Gate`) | aligned |

## Deliberate deviations & path to steady-state

These are intentional posture choices, not gaps to remediate now.

### Warn-only SAST and advisory cluster-smoke/image-scan are a verification ramp

Semgrep and SonarQube run warn-only, and cluster-smoke and image-scan stay
advisory, until the operator sets the `SECURITY_SCAN_BLOCKING=true` repo
variable. This is a deliberate ramp: it lets a consumer verify the
technical implementation (that every job runs, resolves its inputs, and
produces signal) before findings can block a merge. The spec's "all
Phase 2 blocking" state is reached by flipping
`SECURITY_SCAN_BLOCKING=true` as the **final acceptance step**, taken only
after that verification. That flip is the last milestone to steady-state,
never a defect. A skipped, cancelled, or errored blocking job still fails
the gate regardless of the flag, so a broken build can never sign off
green.

### The derived build matrix fulfills the "frontend AND backend" requirement

The spec requires scanning both the frontend **and** backend images. The
`build` and `image-scan` jobs matrix over every non-local `build:` service
in the consumer's Compose file: backend, frontend, and any sidecars each
get their own equal build + scan leg (no positional primary image).
Single-image consumers declare one build service and run a one-leg matrix;
the `matrix-cap` rule bounds the fan-out at ten.

### Suppression files: unsuppressed by default, consumer-owned overrides

The spec's "no suppression of unfixed findings" is the gate's **default**
posture: image-scan defaults empty `.trivyignore` / `.grype.yaml` when the
consumer doesn't carry them. Consumer-carried suppression files are
honored when present: the gate defaults to the spec posture, and a
consumer that commits an ignore file explicitly owns the deviation in its
own reviewable tree.

The same model covers OpenVEX: image-scan defaults an empty-statements
VEX document when the consumer has no `.openvex/`, and a committed
`.openvex/templates/main.openvex.json` is consumed by the Trivy/Grype
image legs. Unlike raw ignore files, a VEX statement carries a status and
justification, and the document as applied is preserved in every run's
security export bundle (RUNBOOK appendix I).

### App build is subsumed into the container build (no separate Phase-1 stage)

The spec's Phase 1 sequences an app build (`pnpm build`) before the
container build. The gate has no standalone app-build job; the app build
lives in the consumer's multi-stage Dockerfile, whose builder stage runs
it first. The fail-fast intent is preserved by DAG ordering (plan → build)
plus Docker layer ordering; a first-class app-build stage would push
toolchain knowledge onto the runner for no earlier signal.

### Merge-gate enforcement is partial by default

`setup-ruleset.sh` creates only the required-status-check rule. The spec's
no-direct-push rule and merge queue are separate GitHub-side configuration
the operator adds per repo (the caller template already carries the
`merge_group:` trigger, so the gate is queue-ready), and the payload's
bypass list (OrganizationAdmin + maintainer + admin roles) is broader than
the spec's admin-only break-glass; trim `bypass_actors` where the spec
posture is required. The gate itself needs no changes for any of this.

### Out of scope for the reusable gate (named, not silently missing)

Spec items intentionally owned elsewhere:

- **Stage-2 GHCR publish**: pushing the frontend and backend images to
  GHCR at the short SHA is a publish/release concern, not a PR gate. The
  reusable gate is deliberately push-free (fork-safe, no
  `packages: write`); images move between jobs as artifacts and never
  reach a registry. GHCR publish is owned by the consumer's release
  workflow.
- **`harden` clean-baseline bootstrap**: the one-time `harden` step that
  establishes a clean SAST/vuln baseline is a bootstrap action run once
  per repo, a prerequisite the operator completes before flipping
  `SECURITY_SCAN_BLOCKING=true`, not part of the reusable gate.
- **Approved-image / private-mirror OS-layer scan**: the gate only builds
  and scans images whose bases are pullable via `cgr.dev` /
  `registry1.dso.mil`. Private-mirror or entitlement-unreachable prod
  bases (and attestation that the *approved* image is clean) remain with
  the consumer IL5 / Game Warden pipeline.
