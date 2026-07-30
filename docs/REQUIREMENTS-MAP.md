# Requirements map — gate jobs → Game Warden MVP CI spec

Every job in the reusable security gate, traced to the CI requirement it
fulfills and its current enforcement posture.

**Authoritative spec:** [Continuous Integration — Game Warden MVP](https://c3energy.atlassian.net/wiki/spaces/CCA/pages/10839163045/) (Confluence CCA `10839163045`).
**Runbook page:** [CI CD Workflow](https://c3energy.atlassian.net/wiki/spaces/CCA/pages/10910040079/) (Confluence CCA `10910040079`).

Source of truth for the job list is
`.github/workflows/reusable-security-gate.yml`. The
`test_every_job_mapped` drift guard fails if a job ships without a row here.

| Job | Spec gate / requirement | Tool(s) | Target | Current posture | Alignment |
|---|---|---|---|---|---|
| `caller-lint` | (scaffolding pre-flight — not a spec gate) | `lint_caller.py` + consumer contract validation | caller config + `Makefile.ci` | always fail-closed | aligned (guards the gate) |
| `build` | build hardened images via consumer contract (`make ci-build`, matrixed over the manifest images) + dual-registry login (CGR and/or Iron Bank) | Docker + CGR/Iron Bank | images | always blocking | aligned |
| `secrets-scan` | Secrets detection | TruffleHog | source | job blocking; finding advisory until `SECURITY_SCAN_BLOCKING=true` | aligned |
| `sast-semgrep` | SAST | Semgrep | source | warn-only (`continue-on-error`) | intentional ramp |
| `sast-sonarqube` | SAST | SonarQube | source | warn-only (`continue-on-error`) | intentional ramp |
| `helm-check` | Helm lint + restricted-PSS | helm + PSS assert | chart | blocking unless `image_only` | aligned |
| `cluster-smoke` | kind deploy + health probe (+ kind-load extras, optional `smoke_secrets`) | kind + kubectl | chart+image | skipped when `image_only`; else advisory until `SECURITY_SCAN_BLOCKING=true` | intentional ramp |
| `image-scan` | Image + SBOM vuln scan (matrixed over the same manifest images as `build`) | Trivy (image+source SBOM) + Grype (image+source+image SBOM) | images + SBOM | advisory until `SECURITY_SCAN_BLOCKING=true` | aligned (Trivy covers the SBOM requirement via the source SBOM; the image SBOM is scanned by Grype) |
| `security-gate` | aggregate required check | — | — | the one required check | aligned |

## Deliberate deviations & path to steady-state

These are intentional posture choices, not gaps to remediate now.

### Warn-only SAST and advisory cluster-smoke/image-scan are a verification ramp

Semgrep and SonarQube run warn-only, and cluster-smoke and image-scan stay
advisory, until the operator sets the `SECURITY_SCAN_BLOCKING=true` repo
variable. This is a deliberate ramp: it lets a consumer verify the technical
implementation — that every job runs, resolves its inputs, and produces signal —
before findings can block a merge. The spec's "all Phase 2 blocking" state is
reached by flipping `SECURITY_SCAN_BLOCKING=true` as the **final acceptance
step**, taken only after that verification. That flip is the last milestone to
steady-state, never a defect. A skipped, cancelled, or errored blocking job
still fails the gate regardless of the flag, so a broken build can never sign
off green.

### Manifest extras fulfill the "frontend AND backend" requirement

The spec requires scanning both the frontend **and** backend images. The
`build` and `image-scan` jobs matrix over every image the consumer's
`ci-manifest` declares: `images[0]` (the backend primary) plus every extra
entry — the frontend and any sidecars — so the multi-image scanning
requirement is met. Single-image consumers declare one manifest image and run
a one-leg matrix.

### Suppression files: unsuppressed by default, consumer-owned overrides

The spec's "no suppression of unfixed findings" is the gate's **default** posture:
image-scan defaults empty `.trivyignore` / `.grype.yaml` when the consumer
doesn't carry them. Consumer-carried suppression files are honored when
present — the same ownership model as `require_hardened_bases: false`: the
gate defaults to the spec posture, and a consumer that commits an ignore file
explicitly owns the deviation in its own reviewable tree.

### App build is subsumed into `ci-build` (no separate Phase-1 stage)

The spec's Phase 1 sequences an app build (`pnpm build`) before the container
build. The gate has no standalone app-build job — both live in the consumer's
`make ci-build`, typically as a multi-stage Dockerfile whose builder stage
runs the app build first. The fail-fast intent is preserved by DAG ordering
(caller-lint → helm-check → build) plus Docker layer ordering; a first-class
app-build stage would push toolchain knowledge onto the runner and grow the
contract for no earlier signal.

### Merge-gate enforcement is partial by default

`setup-ruleset.sh` creates only the required-status-check rule. The spec's
no-direct-push rule and merge queue are separate GitHub-side configuration
the operator adds per repo (the caller template already carries the
`merge_group:` trigger, so the gate is queue-ready), and the payload's bypass
list (OrganizationAdmin + maintainer + admin roles) is broader than the
spec's admin-only break-glass — trim `bypass_actors` where the spec posture
is required. The gate itself needs no changes for any of this.

### Out of scope for the reusable gate (named, not silently missing)

Two spec items are intentionally owned elsewhere:

- **Stage-2 GHCR publish** — pushing the frontend and backend images to GHCR at
  the short SHA is a publish/release concern, not a PR gate. The reusable gate
  is deliberately push-free (fork-safe, no `packages: write`); images move
  between jobs as artifacts and never reach a registry. GHCR publish is owned by
  the consumer's release workflow.
- **`harden` clean-baseline bootstrap** — the one-time `harden` step that
  establishes a clean SAST/vuln baseline is a bootstrap action run once per repo,
  not a per-PR job. It is a prerequisite the operator runs before flipping
  `SECURITY_SCAN_BLOCKING=true`, not part of the reusable gate.
- **Approved-image / private-mirror OS-layer scan** — the gate only builds and
  scans images whose bases are pullable via `cgr.dev` / `registry1.dso.mil`.
  Private-mirror or entitlement-unreachable prod bases (and attestation that the
  *approved* image is clean) remain with the consumer IL5 / Game Warden pipeline.
  When `require_hardened_bases: false`, image-scan labels a **proxy scan**.
