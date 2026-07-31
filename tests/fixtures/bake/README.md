# Bake fixture forks: derivation-assumption proofs

Four fixtures prove the bake-engine assumptions behind the v0.6 gate
design. Each section records the run command and the captured output from
a real local run (macOS host, buildx v0.29.1, helm v4.2.0, 2026-07-31).
The proof scripts themselves are throwaway; only captured output is
committed. The same four checks re-run on a GitHub-hosted runner before
any downstream work builds on them.

Fixtures:

- `n3-local-profile/` - three build services, one `profiles: [local]`
  build service, one digest-pinned `x-downloaded-dependency` image
  service, plus a chart rendering exactly the three built tags
- `n1/` - single build service plus a single-image chart
- `layered-args/` - one service with `RUNTIME_IMAGE` defined at all three
  layers (Dockerfile ARG default, compose `build.args`, `--set`)
- `env-interpolated/` - one service whose build arg interpolates
  `${HOST_VAR:-default-value}`, with a committed `.env`

## Proof 1: explicit target selection excludes local-profile services

Bake ignores Compose `profiles:` when given no targets, so explicit
selection is load-bearing: the derivation layer must pass the non-local
service names on every `--print` and execution call.

```console
$ docker buildx bake -f tests/fixtures/bake/n3-local-profile/docker-compose.yml --print \
    | python3 -c "import json,sys; print(sorted(json.load(sys.stdin)['target']))"
['svc-a', 'svc-b', 'svc-c', 'svc-local']

$ docker buildx bake -f tests/fixtures/bake/n3-local-profile/docker-compose.yml --print svc-a svc-b svc-c \
    | python3 -c "import json,sys; print(sorted(json.load(sys.stdin)['target']))"
['svc-a', 'svc-b', 'svc-c']
```

Execution with the same explicit targets (run from the fixture directory,
see finding A below) builds exactly the same set; the local-profile
service is never built:

```console
$ docker buildx bake -f docker-compose.yml svc-a svc-b svc-c   # exit 0
$ docker images "bake-spike/*" --format "{{.Repository}}:{{.Tag}}" | sort
bake-spike/svc-a:0.1.0
bake-spike/svc-b:0.1.0
bake-spike/svc-c:0.1.0
```

The image-only dependency service (`dep-db`) never appears as a bake
target in any run, as expected.

Accept: plan and execution target sets are `svc-a svc-b svc-c` exactly,
excluding the local-profile service. PASS.

### Finding A: compose `context:` resolves against the process cwd

`bake --print` reports `"context": "."` verbatim and execution resolves it
against the invoking process cwd, not the compose file directory. Running
from the repo root fails with `failed to read dockerfile`; running from
the fixture directory succeeds. The gate must run bake with the consumer
checkout root as cwd (which is also where the consumer compose file
lives), or derivation must normalize contexts to absolute paths.

### Finding B: service-level `platform:` does not reach the bake target

Compose `platform: linux/amd64` on a service does not surface in the bake
plan; the local execution produced a `linux/arm64` image on this arm64
host. The pin must be applied at invocation time and it works there:

```console
$ docker buildx bake -f docker-compose.yml --print --set '*.platform=linux/amd64' svc-a \
    | python3 -c "import json,sys; print(json.load(sys.stdin)['target']['svc-a'].get('platforms'))"
['linux/amd64']
```

## Proof 2: `--set` argument override beats compose and Dockerfile layers

Plan without override shows the compose `build.args` value winning over
the Dockerfile ARG default:

```console
$ docker buildx bake -f tests/fixtures/bake/layered-args/docker-compose.yml --print \
    | python3 -c "import json,sys; print(json.load(sys.stdin)['target']['layered']['args'])"
{'RUNTIME_IMAGE': 'compose-args'}
```

Plan with the override shows `--set` winning:

```console
$ docker buildx bake -f tests/fixtures/bake/layered-args/docker-compose.yml \
    --set '*.args.RUNTIME_IMAGE=spike-x' --print \
    | python3 -c "import json,sys; print(json.load(sys.stdin)['target']['layered']['args'])"
{'RUNTIME_IMAGE': 'spike-x'}
```

The executed build receives the identical value (baked into the image and
read back at runtime):

```console
$ docker buildx bake -f docker-compose.yml --set '*.args.RUNTIME_IMAGE=spike-x' --no-cache   # exit 0
$ docker run --rm bake-spike/layered:0.1.0
RUNTIME_IMAGE=spike-x
```

Accept: `--set` beats `build.args` beats Dockerfile ARG default, and
`--print` args equal executed args. PASS.

## Proof 3: scrubbed-environment plans are deterministic; interpolation is environment-dependent

The same compose file yields three different plans depending on cwd and
host environment, which is exactly why the explicit-input lint
(`build-input-explicit`) is load-bearing:

```console
$ env -i PATH="$PATH" HOME="$HOME" docker buildx bake \
    -f tests/fixtures/bake/env-interpolated/docker-compose.yml --print \
    | python3 -c "import json,sys; print(json.load(sys.stdin)['target']['app']['args'])"
{'EXTRA_ARG': 'default-value'}          # repo root: .env not loaded

$ cd tests/fixtures/bake/env-interpolated
$ env -i PATH="$PATH" HOME="$HOME" docker buildx bake -f docker-compose.yml --print | ...
{'EXTRA_ARG': 'from-env-file'}          # fixture dir: .env loaded

$ env -i PATH="$PATH" HOME="$HOME" HOST_VAR=from-host-env docker buildx bake -f docker-compose.yml --print | ...
{'EXTRA_ARG': 'from-host-env'}          # host env beats .env
```

With the environment scrubbed, two consecutive plans are byte-identical
from both cwds:

```console
$ env -i PATH="$PATH" HOME="$HOME" docker buildx bake -f ... --print > /tmp/a.json
$ env -i PATH="$PATH" HOME="$HOME" docker buildx bake -f ... --print > /tmp/b.json
$ diff /tmp/a.json /tmp/b.json && echo DETERMINISTIC
DETERMINISTIC
```

Accept: scrubbed-env double runs are byte-identical, and the captured
provenance shows the interpolated value comes from `.env`/default,
proving the future `build-input-explicit` lint is load-bearing. PASS.

## Proof 4: explicit compose tags survive plan normalization and match rendered chart references

N=1:

```console
$ diff <(docker buildx bake -f tests/fixtures/bake/n1/docker-compose.yml --print \
      | python3 -c "import json,sys; [print(t) for tgt in json.load(sys.stdin)['target'].values() for t in tgt['tags']]" | sort) \
    <(helm template tests/fixtures/bake/n1/chart | sed -nE 's/.*image: "?([^" ]+)"?.*/\1/p' | sort) \
  && echo N1_MATCH
N1_MATCH        # both sides: bake-spike/app:0.1.0
```

N=3 (explicit non-local targets):

```console
$ diff <(docker buildx bake -f tests/fixtures/bake/n3-local-profile/docker-compose.yml --print svc-a svc-b svc-c \
      | python3 -c "import json,sys; [print(t) for tgt in json.load(sys.stdin)['target'].values() for t in tgt['tags']]" | sort) \
    <(helm template tests/fixtures/bake/n3-local-profile/chart | sed -nE 's/.*image: "?([^" ]+)"?.*/\1/p' | sort) \
  && echo N3_MATCH
N3_MATCH        # both sides: bake-spike/svc-{a,b,c}:0.1.0
```

Accept: normalized plan tags equal rendered chart image references exactly
for both fixtures. PASS.
