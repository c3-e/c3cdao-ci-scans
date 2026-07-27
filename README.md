# c3cdao-ci-scans

Central **monolithic security gate** as a reusable GitHub Actions workflow. Consumers copy a small caller workflow into their repo and own it from then on — no generators, no per-repo scripting.

## Architecture

```text
c3cdao-ci-scans
├── .github/workflows/reusable-security-gate.yml   ← unified gate logic (workflow_call)
├── templates/callers/security-gate.yml            ← copy-and-own caller template
├── templates/consumer/Makefile.ci                 ← copy-and-own build contract template
└── contract/security-gate.schema.json             ← published inputs contract (generated)

consumer repo
├── .github/workflows/security-gate.yml            ← your copy: triggers + with: + uses: ...@ref
└── Makefile.ci                                    ← your build contract: ci-manifest/ci-build/ci-secctx/ci-smoke-env
```

**One required branch-protection check:** `security-scan / Security Gate` (the live
job-id-prefixed context; the workflow's display name is `Security Scan / Security Gate`).

## Quickstart

Six steps to a gated repo. Full commands and provenance: [docs/RUNBOOK.md](docs/RUNBOOK.md).
Field reference for every `with:` value: [docs/INPUTS.md](docs/INPUTS.md).

1. **Prerequisites.** `gh` (authenticated), `uv`, and **admin** on the consumer repo
   (secrets + rulesets). Your build knowledge lives in your contract makefile:
   `make ci-manifest` declares images, chart, and health probe; `ci-build` /
   `ci-secctx` / `ci-smoke-env` own the build, secctx assertion, and smoke
   prerequisites ([docs/CI-CONTRACT.md](docs/CI-CONTRACT.md)).
2. **Copy the caller and the contract.**
   `cp <ci-scans-clone>/templates/callers/security-gate.yml .github/workflows/security-gate.yml`
   and `cp <ci-scans-clone>/templates/consumer/Makefile.ci Makefile.ci`.
   You own both from here — no tooling ever rewrites them.
3. **Edit `Makefile.ci` and `with:`.** The makefile's variable block describes your
   images, chart, and health probe; each caller `with:` line carries an inline
   provenance comment. Keep the job id `security-scan` — renaming it silently
   un-gates merges. Pass secrets explicitly, never `inherit`.
4. **Set the four secrets.** `CGR_PULL_TOKEN`, `CGR_PULL_USERNAME`, `IRONBANK_TOKEN`,
   `IRONBANK_USERNAME` — via `gh secret set --repo <owner>/<repo>` or Settings → Secrets
   and variables → Actions → New repository secret.
5. **Create the ruleset.** This creates a GitHub **repository ruleset** that makes
   `security-scan / Security Gate` a required status check on your trunk branch:
   ```bash
   ./scripts/setup-ruleset.sh --config configs/local/<repo>.yaml           # create, disabled
   ./scripts/setup-ruleset.sh --config configs/local/<repo>.yaml --enable  # enforce
   ```
6. **Open a PR.** The `security-scan / Security Gate` context appears and goes green.
   Pilot on a scratch branch first — **`ci-scans`** in a single-app usecase repo (no
   token needed), then promote to trunk ([docs/RUNBOOK.md](docs/RUNBOOK.md)). The
   shared umbrella `c3cdao-apps` is the exception: it tokens its chart branches as
   `ci-chart-<usecasename>` to keep multiple usecases from colliding.

## Caller lint

The gate's first job (`caller-lint`) is a **fail-closed configuration pre-flight**: it
validates your copied caller's `with:` inputs, secret mappings, and structure against the
published contract — including blocking validation of your contract makefile and its
`ci-manifest` output. Nothing scans until it passes — it is not a security scanner.
Rule ids and local invocation: [docs/RUNBOOK.md](docs/RUNBOOK.md).

## Pin policy

Consumers pin a release tag — `uses: …/reusable-security-gate.yml@vX.Y.Z`; the
template ships pinned (`@v0.5.1`). `@main` is acceptable only during the pilot
migration window (caller lint emits a stderr notice).

## Docs

- [docs/RUNBOOK.md](docs/RUNBOOK.md) — full onboarding, ruleset provenance, enforcement
  model, caller-lint rule ids, hardened-base login (dual registry), scan boundary /
  proxy-scan posture, and maintenance.
- [docs/INPUTS.md](docs/INPUTS.md) — every `with:` field with type, default, and provenance.
- [docs/CI-CONTRACT.md](docs/CI-CONTRACT.md) — the consumer build contract: target
  interface, env vars, and the `ci-manifest` JSON shape.
- [docs/REQUIREMENTS-MAP.md](docs/REQUIREMENTS-MAP.md) — gate jobs mapped to the CI spec.
