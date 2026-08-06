# c3cdao-ci-scans

Central **monolithic security gate** as a reusable GitHub Actions workflow. Consumers copy a small caller workflow into their repo and own it from then on; the gate derives what to build, scan, and smoke from the Compose file, Dockerfiles, and Helm chart the repo already maintains. No generators, no per-repo scripting, no CI-only artifacts.

## Architecture

```text
c3cdao-ci-scans
├── .github/workflows/reusable-security-gate.yml   ← unified gate logic (workflow_call)
├── templates/callers/security-gate.yml            ← copy-and-own caller template
└── scripts/lib/                                   ← derivation + fail-closed convention lint

consumer repo
├── .github/workflows/security-gate.yml            ← your copy: triggers + with: + uses: ...@<sha>
├── docker-compose.yml                             ← build truth: images, tags, healthchecks, dependencies
└── chart/                                         ← runtime truth: readiness, Services, values
```

**One required branch-protection check:** `security-scan / Security Gate` (the live
job-id-prefixed context; the workflow's display name is `Security Scan / Security Gate`).

## Quickstart

Six steps to a gated repo. Full commands and provenance: [docs/RUNBOOK.md](docs/RUNBOOK.md).
Field reference for every `with:` value: [docs/INPUTS.md](docs/INPUTS.md).

1. **Make the repo conform.** The derived contract reads files you already
   maintain: every release image is a Compose `build:` service with an explicit
   tag and healthcheck, and the chart exposes readiness plus one Service-backed
   HTTP smoke target ([docs/CI-CONTRACT.md](docs/CI-CONTRACT.md)).
2. **Copy the caller.**
   `cp <ci-scans-clone>/templates/callers/security-gate.yml .github/workflows/security-gate.yml`.
   One file; you own it from here. No tooling ever rewrites it.
3. **Edit `with:` and pin.** Each `with:` line carries an inline provenance
   comment. Keep the job id `security-scan`; renaming it un-gates
   merges. Pass secrets explicitly, never `inherit`. Pin `uses:` to a full
   40-hex commit SHA (record the release tag as a comment).
4. **Set the four secrets.** `CGR_PULL_TOKEN`, `CGR_PULL_USERNAME`, `IRONBANK_TOKEN`,
   `IRONBANK_USERNAME`, via `gh secret set --repo <owner>/<repo>` or Settings → Secrets
   and variables → Actions → New repository secret.
5. **Create the ruleset.** This creates a GitHub **repository ruleset** that makes
   `security-scan / Security Gate` a required status check on your trunk branch:
   ```bash
   ./scripts/setup-ruleset.sh --config configs/local/<repo>.yaml           # create, disabled
   ./scripts/setup-ruleset.sh --config configs/local/<repo>.yaml --enable  # enforce
   ```
6. **Open a PR.** The `security-scan / Security Gate` context appears and goes
   green. Pilot on a scratch branch first (**`ci-scans`** in a single-app
   usecase repo), then promote to trunk ([docs/RUNBOOK.md](docs/RUNBOOK.md)).
   Shared umbrella repos token their chart branches as `ci-chart-<usecasename>`
   to keep multiple usecases from colliding.

## Caller lint

The gate's first job (`plan`) is a **fail-closed configuration pre-flight**: it
validates your caller's structure and your repo's Compose/Dockerfile/chart
shapes against the published conventions, then derives and publishes the exact
build/scan set (the BOM) before anything expensive runs. Every finding names a
rule id and links its remediation: [docs/CI-CONTRACT.md](docs/CI-CONTRACT.md).
Local invocation: [docs/RUNBOOK.md](docs/RUNBOOK.md).

## Pin policy

Consumers pin the immutable release revision:
`uses: …/reusable-security-gate.yml@<40-hex sha>  # v0.6.0`. Tags and branches
are rejected by the `gate-ref-pin` lint rule.

## Docs

- [docs/RUNBOOK.md](docs/RUNBOOK.md): full onboarding, ruleset provenance, enforcement
  model, lint remediation flow, reading the BOM, registry login matrix, smoke
  catalog, and maintenance.
- [docs/INPUTS.md](docs/INPUTS.md): the seven `with:` fields + four secrets, and the
  removed-inputs migration table.
- [docs/CI-CONTRACT.md](docs/CI-CONTRACT.md): the derived consumer contract: Compose,
  Dockerfile, and chart conventions, plus the full lint rule table.
- [docs/REQUIREMENTS-MAP.md](docs/REQUIREMENTS-MAP.md): gate jobs mapped to the CI spec.
