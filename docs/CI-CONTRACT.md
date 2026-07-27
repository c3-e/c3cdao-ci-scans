# Consumer build contract

The contract is the **only** build path (since v0.5.0): the gate never owns
your build knowledge. It drives four make targets in a contract makefile you
own (`contract_file` input, default `Makefile.ci`, path relative to your repo
root). Start from
[`templates/consumer/Makefile.ci`](../templates/consumer/Makefile.ci) — a
working single-image baseline; edit it for your repo.

`make ci-manifest` is the single source of truth for your containers list and
chart/health metadata — there are no per-field `with:` inputs to mirror or
merge (one owner, no merge rules).

## Target interface

| Target | Invocation | Env provided by the gate |
| --- | --- | --- |
| `ci-manifest` | `make -s -f <contract_file> ci-manifest` | — |
| `ci-build` | `make -f <contract_file> ci-build IMAGE=<name>` | `CI_BUILDER_BASE`, `CI_RUNTIME_BASE`, `CI_IMAGE_TAG` |
| `ci-secctx` | `make -f <contract_file> ci-secctx` | — |
| `ci-smoke-env` | `make -f <contract_file> ci-smoke-env NAMESPACE=<ns>` | — |

`ci-manifest`, `ci-build`, and `ci-smoke-env` are **required** — caller lint
fails when any is missing. `ci-secctx` is optional (its absence is a notice).

- **`ci-manifest`** prints a JSON document to stdout:

  ```json
  {
    "images": [{"name": "...", "dockerfile": "...", "context": "...",
                "target": "...", "build_args": "KEY=VALUE\n...",
                "image": "optional-tag:local"}],
    "chart":  {"path": "...", "values": "...", "values_local": "...",
               "release": "...", "namespace": "..."},
    "health": {"path": "...", "port": "...", "workload_match": "..."}
  }
  ```

  Required shape (blocking in caller lint): `images[]` non-empty, each entry
  with `name`/`dockerfile`/`context`; `chart{}` with all five keys; `health{}`
  with all three keys. `target`/`build_args` are informational for your own
  `ci-build` — the gate does not consume them.

  `images[0]` is the **primary** — the gate always tags it with its
  `scan_image` input (an `image` key on the primary is ignored; `scan_image`
  stays authoritative because caller lint pins it against your
  `chart.values_local` file). `images[1:]` are the extras — tagged by their
  optional `image` key, or `<name>:local` when absent. **The extras tag must
  match what your values file schedules with `pullPolicy: Never`** — a
  mismatch is ErrImageNeverPull at smoke time. The manifest also feeds
  helm-check (`chart.path`/`values`/`release`) and cluster-smoke
  (`chart.values_local`/`namespace`, `health.*`).
- **`ci-build IMAGE=<name>`** must produce the local-daemon tag the gate
  passes as `CI_IMAGE_TAG`. `CI_BUILDER_BASE` / `CI_RUNTIME_BASE` are the
  hardened base images after the gate's registry-login failover resolution
  (Chainguard / Iron Bank) — consume them as your base-image build args.
  The gate verifies the tag exists after the target runs, then SBOMs,
  saves, and uploads the image.
- **`ci-secctx`** is your own pod-security assertion. A missing target is a
  notice, not a failure. **The gate's bundled restricted-PSS assertion
  always runs in-gate** — it is gate policy and cannot be edited out of a
  consumer contract file.
- **`ci-smoke-env NAMESPACE=<ns>`** provisions cluster-smoke prerequisites
  before `helm install`: the reference implementation deploys the pgvector
  Postgres + Service, creates the `app-database-url` secret, and installs
  the Gateway API CRDs. The gate has already created the namespace and
  kind-loaded the built images; `smoke_secrets` are still created by the
  gate after this target runs.

## Caller lint

`lint_caller.py` validates the contract file **blocking** (violations fail
the gate): `ci-contract-file` (contract file missing under the consumer
root), `ci-contract-target` (`make -n` cannot resolve `ci-manifest` /
`ci-build` / `ci-smoke-env`), `ci-contract-manifest` (`ci-manifest` fails to
run, prints invalid JSON, or is off the required shape). A missing
`ci-secctx` is a stderr notice. The `image-values-mismatch` rule reads
`chart.values_local` from the manifest and requires `scan_image` to be
pinned there. The `extras-values-mismatch` rule applies the same pin check
to every manifest extra (`images[1:]`), tagged by its optional `image` key
or `<name>:local`.
