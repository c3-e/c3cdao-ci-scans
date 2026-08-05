# Consumer contract (derived, v0.6)

The gate derives everything it builds, scans, and smokes from files your
repository already maintains for local development: the canonical Compose
file, its Dockerfiles, and the Helm chart. You hand-author no manifest, no
contract makefile, and no CI scripts — the v0.5 consumer contract
(`Makefile.ci`, driven by `make` targets) was removed at this major
version, not deprecated. Conventions are enforced by fail-closed lint in
the gate's `plan` job; a nonconforming shape blocks with a named rule and
a remediation link into the [rule table](#rule-table) below before
anything expensive runs.

## What the gate derives

- **Image set (the BOM).** `docker buildx bake --print` over your Compose
  file resolves every non-local `build:` service into a build target
  (name, dockerfile, context, args, tags). The plan job publishes the
  annotated BOM every run — job summary plus `plan-bom` artifact — with an
  `excluded:` section naming services filtered out and why, and a
  `dependencies:` section for declared downloaded dependencies. Each build
  leg re-prints its target and diffs it against the published plan, so the
  plan you review is bit-for-bit the plan that executes.
- **Build matrix.** One build + one image-scan leg per derived target
  (up to ten; `fail-fast: false`). There is no positional
  primary-versus-secondary image distinction: every leg is equal, and the
  spec's frontend and backend scanning requirement is met by declaring
  both as Compose build services.
- **Smoke target.** For chart consumers, the gate renders the chart with
  your local values and derives exactly one Service-backed HTTP readiness
  target for the post-deploy probe. Deploy and health facts stay in the
  chart; CI never extends it.

## Compose file conventions

One canonical committed Compose file (the `compose_file` input, default
`docker-compose.yml`) at your repository root. Overlay/override files are
not read by the derivation. The top level must map `services:`.

- **Build services.** Every service with `build:` becomes a build + scan
  target unless it is local-only. Local-only means the exact profile
  spelling `profiles: [local]` — `profiles: [dev]` or `[Local]` does not
  exclude. Exclusions are published in the BOM's `excluded:` section, never
  silent. At most ten non-local build services are supported.
- **Image tags.** Every non-local build service declares an explicit
  `image:` tag. Untagged references, `:latest`, and interpolated
  references (`image: app:${TAG}`) all block: the tag is the label the
  pipeline stamps on its own output and the exact-match anchor for the
  ship-set check, so it must be a committed literal. A digest cannot exist
  before the build, so no digest is required here.
- **Healthchecks.** Every non-local build service declares `healthcheck:`
  with a truthy `test` command — HTTP, TCP, or exec. Compose healthchecks
  and Helm readiness probes are separate integration points: Compose
  proves the service can run locally; Helm proves Kubernetes can route to
  a ready workload. The two need not share a command or protocol.
- **Platform.** v0.6 builds, scans, and smokes `linux/amd64` only, and the
  gate pins that platform on every build. A committed `platform:` (or
  `build.platforms`) other than `linux/amd64` blocks rather than being
  silently overridden — including on image-only dependency services.

## Downloaded runtime dependencies

A Compose service with `image:` and no `build:` (PostgreSQL, an identity
provider your chart deploys itself) is a downloaded runtime dependency
only when all three hold:

1. it declares the marker key `x-downloaded-dependency` (hyphens exactly);
2. its `image:` string pins the digest inline — `repo:tag@sha256:...` — a
   separate digest field is not read. Registry tags are mutable, so the
   digest is the real supply-chain pin; the tag stays for readability;
3. the marker records the chart-facing tag as
   `x-downloaded-dependency.chart-tag` (hyphen, not underscore).

The gate does not treat dependencies as release artifacts and does not
claim to scan them. An unmarked or tag-only external image blocks — v0.6
supports downloaded runtime dependencies, not external application release
images. The ship-set cross-check matches a rendered chart reference
against the declared `chart-tag` by **exact** string equality (no registry
or default-tag normalization): `docker.io/pgvector/pgvector:pg16` in the
chart does not match a declared `pgvector/pgvector:pg16`. Make the two
strings identical; a chart-side version bump blocks until the reviewed
Compose declaration is updated.

## Dockerfiles and build inputs

- **Blessed base ARG pair.** Every target's Dockerfile declares both
  `ARG BUILDER_IMAGE` and `ARG RUNTIME_IMAGE` — even single-stage builds
  declare both. Declaring the pair is the contract; the gate does **not**
  override either arg at build time. Consuming them for a hardened base
  (`FROM ${BUILDER_IMAGE}`, pinned to a registry the gate can authenticate
  to per [appendix B](RUNBOOK.md#b-hardened-base-registry-login-matrix))
  is your own choice, not a gate-supplied guarantee. The Dockerfile is
  resolved from `build.context`/`build.dockerfile` against the Compose
  file's directory; `dockerfile_inline` is unsupported and fails closed.
- **Committed literal args.** `build.args` must be a mapping of committed
  literal values. List syntax, null pass-through values, any environment
  interpolation in a build-affecting field, `build.secrets`, and
  `build.ssh` all block. A literal dollar needs Compose's `$$` escape.
- **Secret-like arg names.** Arg names containing `TOKEN`, `SECRET`,
  `PASSW`, or `CREDENTIAL`, ending in `_KEY`, or exactly `KEY` block even
  with harmless literal values — false positives are by design; rename
  the arg (`PUBLIC_KEY` → `PUBLIC_KEY_NAME` still blocks; pick a name
  without the fragment).
- **Build-context exclusions.** Every build context directory carries its
  own `.dockerignore` containing the four literal lines `.env`, `*.pem`,
  `*.key`, and `*credentials*`. Equivalent patterns (`**/*.pem`, `.env*`)
  do not satisfy the check — the four exact lines must be present.

## Chart conventions (non-image_only)

The gate renders `helm template <chart_path> -f <values_local>`; a render
failure fails closed before any chart rule runs.

- **Readiness.** Every container of every rendered deployable workload —
  kinds `Deployment`, `StatefulSet`, and `DaemonSet` — declares a
  `readinessProbe`, sidecars included.
- **One smoke target.** Exactly one container has an `httpGet`
  readinessProbe whose port a Service routes to. The Service's selector
  must be a label-subset of the pod template labels, and the probe port is
  matched against the Service's `targetPort` (falling back to `port`) by
  equality — a named probe port (`port: http`) needs the Service
  `targetPort` spelled identically.
- **Ship-set invariant (`S \ D ⊆ B`).** Let `B` be the tags built from
  non-local Compose build services, `D` the declared downloaded
  dependencies, and `S` every container and init-container reference in
  the render. Every rendered image must be built-and-scanned (`B`) or a
  declared dependency (`D`); anything else blocks before build. A built
  tag the chart never schedules is scanned anyway and warned about.
- **Decoupled database (ADR-08).** One standard across environments: the
  app reads a connection URL from a Secret (`app-database-url` →
  `DATABASE_URL`). Local dev gets a Compose pgvector container; smoke gets
  the gate's `postgres-pgvector` module; production gets the managed
  database. Chart-bundled databases are nonconforming by convention.

## Caller conventions

The caller workflow is a thin pointer — data, never behavior. See
[INPUTS.md](INPUTS.md) for the seven-input surface and
[RUNBOOK.md](RUNBOOK.md) for onboarding steps.

- The gate ref in `uses:` is pinned by a full 40-hex commit SHA; record
  the release tag as a trailing comment. Tags and branches block.
- All four registry secrets (`CGR_PULL_TOKEN`, `CGR_PULL_USERNAME`,
  `IRONBANK_TOKEN`, `IRONBANK_USERNAME`) are mapped explicitly;
  `secrets: inherit` blocks. Forks scanning public images still map all
  four.
- `smoke_resources` is a CSV drawn from the gate-owned catalog:
  `postgres-pgvector`, `gateway-crds`. A resource type not in the catalog
  is a ci-scans feature request, not a consumer escape hatch.
- Keep the job id `security-scan` — it is half of the required check
  context `security-scan / Security Gate`.

## Rule table

Every lint finding carries a `remediation_ref` pointing at one of the rule
headings below. Rules marked **warn** report without blocking; everything
else blocks the run before any build starts.

| Rule id | Level | Check |
|---|---|---|
| [`compose-missing`](#rule-compose-missing) | block | canonical Compose file absent or not a `services:` mapping |
| [`compose-no-builds`](#rule-compose-no-builds) | block | zero non-local `build:` services |
| [`matrix-cap`](#rule-matrix-cap) | block | more than ten non-local `build:` services |
| [`compose-image-tag`](#rule-compose-image-tag) | block | build service lacks an explicit, literal `image:` tag |
| [`compose-healthcheck`](#rule-compose-healthcheck) | block | build service lacks a `healthcheck:` with a `test` command |
| [`dependency-shape`](#rule-dependency-shape) | block | image-only service is not a conforming dependency declaration |
| [`build-input-explicit`](#rule-build-input-explicit) | block | build inputs depend on host state or a secret channel |
| [`build-context-excludes`](#rule-build-context-excludes) | block | a build context can include env/credential/key material |
| [`compose-platform`](#rule-compose-platform) | block | a platform other than `linux/amd64` is declared |
| [`bake-resolve`](#rule-bake-resolve) | block | `bake --print` fails on the Compose file |
| [`hardened-args`](#rule-hardened-args) | block | a Dockerfile lacks the blessed base ARG pair |
| [`chart-missing`](#rule-chart-missing) | block | `image_only` is false and no chart exists at `chart_path` |
| [`chart-undeclared`](#rule-chart-undeclared) | block | `image_only` is true but a Helm chart exists anywhere in the repo |
| [`chart-resolve`](#rule-chart-resolve) | block | `helm template` fails on the declared chart (e.g. unresolved dependency) |
| [`chart-readiness`](#rule-chart-readiness) | block | a rendered workload container lacks readiness |
| [`smoke-target`](#rule-smoke-target) | block | no single Service-backed HTTP readiness target |
| [`ship-set`](#rule-ship-set) | block | a rendered image is neither built nor a declared dependency |
| [`built-unscheduled`](#rule-built-unscheduled) | warn | a built tag is never scheduled by the chart |
| [`smoke-resource-unknown`](#rule-smoke-resource-unknown) | block | `smoke_resources` names a module outside the catalog |
| [`gate-ref-pin`](#rule-gate-ref-pin) | block | gate ref is not a full 40-hex commit SHA |
| [`gate-job-id`](#rule-gate-job-id) | block | the calling job id is not `security-scan` |
| [`no-secrets-inherit`](#rule-no-secrets-inherit) | block | caller uses `secrets: inherit` |
| [`missing-secret-map`](#rule-missing-secret-map) | block | one of the four registry secrets is unmapped |
| [`unknown-input`](#rule-unknown-input) | block | a `with:` key is not a v0.6 input (removed v0.5 inputs rejected by name) |
| [`unreadable-caller`](#rule-unreadable-caller) | block | the caller workflow cannot be parsed |

### Rule: compose-missing

The `compose_file` path must exist and parse to a YAML mapping with a
`services:` map. Remediation: commit the canonical Compose file at the
repository root (or point `compose_file` at it).

### Rule: compose-no-builds

At least one non-local `build:` service must exist — `image_only`
repositories included; the gate exists to build and scan at least one
image. Remediation: add a `build:` stanza for the image this repository
produces.

### Rule: matrix-cap

At most ten non-local build services are supported, as a functional bound
in place of a runtime budget. No override input exists by design.
Remediation: mark non-release services `profiles: [local]` or split the
repository.

### Rule: compose-image-tag

Every non-local build service needs `image:` with an explicit literal tag.
`:latest`, untagged, and interpolated (`app:${TAG}`) references block —
the gate builds with a scrubbed environment, so an interpolated tag would
resolve empty. Remediation: `image: app-api:1.4.2` (bump on release); a
literal dollar needs the `$$` escape.

### Rule: compose-healthcheck

Every non-local build service declares `healthcheck:` with a truthy
`test` — HTTP, TCP, or exec (`healthcheck: {disable: true}` blocks).
Remediation: `healthcheck: {test: [CMD, /app/healthcheck]}`.

### Rule: dependency-shape

An image-only service must declare `x-downloaded-dependency` with a
`chart-tag` key, and pin the digest inside the `image:` string.
Remediation:

```yaml
postgres:
  image: pgvector/pgvector:pg16@sha256:<64-hex>
  x-downloaded-dependency:
    chart-tag: pgvector/pgvector:pg16
```

### Rule: build-input-explicit

`build.args` must be a mapping of committed literals. Blocks: list-syntax
args, null pass-through values, environment interpolation in any
build-affecting field, secret-like arg names (`TOKEN`/`SECRET`/`PASSW`/
`CREDENTIAL` fragments, `_KEY` suffix, or exactly `KEY`), `build.secrets`,
and `build.ssh`. Remediation: commit the literal value, escape literal
dollars as `$$`, rename secret-like args. `BUILDER_IMAGE`/`RUNTIME_IMAGE`
are exempted from the secret-like-name check (see
[hardened-args](#rule-hardened-args)) but are not otherwise special —
the gate does not supply or override any arg value.

### Rule: build-context-excludes

Every build context directory needs its own `.dockerignore` containing the
four literal lines `.env`, `*.pem`, `*.key`, `*credentials*`. Stricter
equivalents do not satisfy the check. Remediation: append the exact four
lines.

### Rule: compose-platform

`platform:` and `build.platforms` may only say `linux/amd64`, on every
service including dependencies — an arm64 dev override committed for
Apple-silicon laptops blocks CI. Remediation: delete the field or set it
to `linux/amd64`; multi-architecture builds are a follow-up.

### Rule: bake-resolve

`docker buildx bake --print` must resolve the Compose file; bake's stderr
is attached to the verdict. Runs only after the shape rules above pass.
Remediation: fix the Compose error bake names.

### Rule: hardened-args

Every target's Dockerfile declares `ARG BUILDER_IMAGE` and
`ARG RUNTIME_IMAGE` (both, even single-stage builds). This is a
declaration-only check: the gate does not inject or override either
arg's value at build time, and never guarantees the Dockerfile's
default resolves to a hardened base — consuming the ARG in `FROM` for
an actual hardened base is the consumer's own choice. An unreadable
Dockerfile fails closed. Remediation: add both ARG lines.

### Rule: chart-missing

`image_only` is false (the default) and no `Chart.yaml` exists at
`chart_path` — a verified declaration, not a raw downstream helm error.
Remediation: author the chart at `chart_path`, or set `image_only: true`
if this repository truly has no deployable chart.

### Rule: chart-undeclared

`image_only` is true but a `Chart.yaml` exists anywhere in the repository
tree (excluding vendored dependency copies under any `charts/`
directory). The check is repo-wide, not `chart_path`-only, so an owned
chart at a different path cannot evade it. Remediation: set
`image_only: false` and declare `chart_path`, or remove the chart if it
is genuinely not deployed from this repository.

### Rule: chart-resolve

`helm template` must resolve the declared chart — helm's stderr is
attached to the verdict. A chart with an unresolved dependency (missing
`helm dependency build`, or a broken repository/path) fails here with a
named, remediation-linked message instead of a raw stack trace.
Remediation: fix the dependency declaration, or commit the vendored
`charts/` directory if the dependency source is unavailable at plan
time.

### Rule: chart-readiness

Every container of every rendered `Deployment`/`StatefulSet`/`DaemonSet`
declares a `readinessProbe` — sidecars too. Remediation: add the probe to
the named container.

### Rule: smoke-target

The render must yield exactly one container with an `httpGet`
readinessProbe whose port a Service routes to (selector is a label-subset
of the pod labels; probe port equals the Service `targetPort`, falling
back to `port` — named ports must match spelling). Zero or multiple
targets block, naming the candidates. Remediation: expose exactly one
HTTP readiness target through a matching Service.

### Rule: ship-set

Enforces `S \ D ⊆ B` over the render: a scheduled image must be a built
tag or match a declared dependency's `chart-tag` by exact string equality.
The verdict names both tags on a version-bump mismatch. Remediation: build
the image, or declare/update the digest-pinned dependency so the strings
match exactly.

### Rule: built-unscheduled

Warn only: a built tag the rendered chart never schedules is still built
and scanned (scan superset is safe). Remediation optional: schedule it or
mark the service `profiles: [local]`.

### Rule: smoke-resource-unknown

`smoke_resources` entries must come from the gate catalog:
`postgres-pgvector`, `gateway-crds`. Remediation: request the module from
ci-scans; there is no consumer escape hatch.

### Rule: gate-ref-pin

The `uses:` ref must end in a full 40-hex commit SHA; tags and branches
block. Remediation: pin the SHA and record the tag as a trailing comment.

### Rule: gate-job-id

The job calling the reusable workflow must keep the id `security-scan` —
it is half of the required check context `security-scan / Security Gate`.
A renamed id reports under a different context and the branch-protection
ruleset silently no longer matches. Remediation: rename the job id back
to `security-scan`.

### Rule: no-secrets-inherit

`secrets: inherit` silently passes nothing across owners. Remediation: map
the four registry secrets explicitly.

### Rule: missing-secret-map

All four of `CGR_PULL_TOKEN`, `CGR_PULL_USERNAME`, `IRONBANK_TOKEN`,
`IRONBANK_USERNAME` must be mapped on the gate job. Remediation: add the
missing mapping.

### Rule: unknown-input

The `with:` surface is exactly the seven v0.6 inputs; inputs removed at
this major version are rejected by name with migration guidance.
Remediation: delete the key — see the removed-inputs table in
[INPUTS.md](INPUTS.md).

### Rule: unreadable-caller

The caller workflow must parse as YAML with a jobs mapping containing one
job whose `uses:` names the gate workflow. Remediation: fix the parse
error in the verdict message.
