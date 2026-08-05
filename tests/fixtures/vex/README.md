# VEX fixture forks: scanner-passthrough proofs

Two fixtures prove the OpenVEX-consumption assumptions behind T1/T2: a
small, fast Alpine-style image (both scanners have coverage) and a
RHEL10/UBI10-based image (Trivy has no advisory data at all — T0 — so this
fixture is what actually proves `GRYPE_VEX_DOCUMENTS` matters for
GameWarden-bound/Iron-Bank consumers). Every statement in both docs is
dual-product (T0b): Trivy computes `repository_url` with the image name
included, Grype computes it without — a single-form statement silently
suppresses on only one scanner.

Each fixture's `main.openvex.json` is a real `vexctl add`-authored document
(vexctl 0.4.4), not hand-rolled JSON; the digest and CVE are real and
public. Local runs below: macOS host, trivy 0.71.2 / grype 0.114.0
(matching the exact pinned CLI versions used by trivy-action `57a97c7…`
v0.35.0 → trivy 0.69.3 and scan-action `e116508…` v7.4.0 → grype 0.110.0,
each independently re-verified via `docker run` against those exact
version tags — see T1 in `.plan/vex/tickets.md` for the pinned-version
run commands and output), captured 2026-08-05.

Fixtures:

- `alpine-known-cve/` — `alpine:3.12`
  (`sha256:c75ac27b49326926b803b9ed43bf088bc220d22556de1bc5f72d742c91398f69`),
  `CVE-2022-37434` (zlib heap overflow, present in both scanners' DBs).
- `ubi10-rhel-gap/` — `registry.access.redhat.com/ubi10/ubi:latest`
  (`sha256:aad065f8857f86a136994c648ecc714f8cb59c96bf25ae54320e59e155dfca09`),
  `CVE-2024-13176` (OpenSSL ECDSA timing side-channel, ​Grype-only per T0 —
  Trivy has zero RHEL10 advisory data). Publicly pullable, no Iron Bank
  registry auth required.

## Proof 1: `alpine-known-cve` — both scanners honor the doc

Without VEX, both scanners report the CVE:

```console
$ trivy image --quiet --format json alpine:3.12 | jq -r '[.Results[].Vulnerabilities[]?.VulnerabilityID] | unique'
["CVE-2022-37434"]          # (1 of 1 Trivy finding on this image)

$ grype alpine:3.12 -o json | jq -r '[.matches[].vulnerability.id] | unique | length'
45                           # CVE-2022-37434 is one of the 45
```

With the fixture doc (`TRIVY_VEX` / `GRYPE_VEX_DOCUMENTS` env, mirroring
how each pinned action wires the CLI):

```console
$ TRIVY_VEX=tests/fixtures/vex/alpine-known-cve/main.openvex.json \
    trivy image --quiet --format json alpine:3.12 | jq -r '[.Results[].Vulnerabilities[]?.VulnerabilityID] | unique'
[]                            # dropped

$ GRYPE_VEX_DOCUMENTS=tests/fixtures/vex/alpine-known-cve/main.openvex.json \
    grype alpine:3.12 -o json | jq -r '[.matches[].vulnerability.id] | unique | length'
44                            # 45 -> 44; CVE-2022-37434 dropped
```

Grype SBOM leg (`anchore/sbom-action@e22c389…` v0.24.0 pins Syft v1.42.3;
re-verified via `docker run anchore/syft:v1.42.3 alpine:3.12 -o
cyclonedx-json@1.5`, not just local Syft 1.50.0): the CycloneDX root
`metadata.component` Syft emits for a container has **no `purl` field at
all** — only `name`/`version` — so there is no product identifier for
`GRYPE_VEX_DOCUMENTS` to match against, at any PURL form (bare
`pkg:oci/alpine`, name-only `alpine`, and the dual-product form above
were all tried; none suppress the finding on the SBOM leg). This is the
"Grype SBOM leg is the likely deviant" finding predicted in
`.handoff/plan-openvex-gate.md` step 3, confirmed: **the SBOM leg does not
honor VEX with this SBOM producer**, independent of PURL construction —
see T1's acceptance record in `.plan/vex/tickets.md` for the decision this
drives for T2 (image legs only).

Accept: Trivy and Grype **image** legs both drop the fixture CVE with the
env var set, restore it when unset; product identity in both cases is the
image PURL (`pkg:oci/alpine@sha256:...`), not a name-only match — proven
by testing bare/name-only forms that do NOT match on the image legs either
(only the correctly-scoped `repository_url` form works). Grype **SBOM**
leg does not honor VEX at all with an `anchore/sbom-action`-produced
CycloneDX SBOM (no root PURL to match). PASS on image legs; SBOM leg is a
confirmed non-goal for T2, not a spike failure.

## Proof 2: `ubi10-rhel-gap` — T0's Trivy gap, Grype carries the whole burden

Without VEX:

```console
$ trivy image --quiet --format json registry.access.redhat.com/ubi10/ubi:latest \
    | jq -r '.Metadata.OS, ([.Results[]?.Vulnerabilities[]?.VulnerabilityID] | unique | length)'
{"Family":"redhat","Name":"10.2"}
0                              # T0: confirmed, zero Trivy findings on RHEL10/UBI10

$ grype registry.access.redhat.com/ubi10/ubi:latest -o json | jq -r '[.matches[].vulnerability.id] | unique | length'
216                            # CVE-2024-13176 is one of the 216
```

With the fixture doc:

```console
$ TRIVY_VEX=tests/fixtures/vex/ubi10-rhel-gap/main.openvex.json \
    trivy image --quiet --format json registry.access.redhat.com/ubi10/ubi:latest \
    | jq -r '[.Results[]?.Vulnerabilities[]?.VulnerabilityID] | unique | length'
0                              # still 0 — expected no-op (T0), not a spike failure:
                               # there was nothing to suppress in the first place

$ GRYPE_VEX_DOCUMENTS=tests/fixtures/vex/ubi10-rhel-gap/main.openvex.json \
    grype registry.access.redhat.com/ubi10/ubi:latest -o json | jq -r '[.matches[].vulnerability.id] | unique | length'
215                            # 216 -> 215; CVE-2024-13176 dropped
```

Re-verified against the exact pinned Grype CLI (`docker run
anchore/grype:v0.110.0 ...`, not just local Grype 0.114.0): 45→44 on the
Alpine fixture and the `TRIVY_VEX` env-var passthrough both reproduce
identically against `aquasec/trivy:0.69.3` (trivy-action's pinned CLI).

Accept: Trivy leg is a confirmed no-op on this fixture (0 findings with or
without the doc — the RHEL10 advisory-data gap, not a passthrough
failure); Grype image leg drops the fixture CVE with the env var set.
`GRYPE_VEX_DOCUMENTS` is therefore the only lever that matters for
RHEL10/UBI10 (Iron-Bank-based) consumers, exactly as T0 predicts. PASS.

## Both scanners compute different `repository_url` for the same image (T0b, confirmed on both fixtures)

A single-product statement using only one scanner's `repository_url` form
silently fails to match the other scanner — no warning, no error. Verified
by omitting each form in turn (not committed as separate fixtures, see
run log in `.plan/vex/tickets.md` T1's acceptance record):

- Alpine: Trivy's PURL includes the image name
  (`repository_url=index.docker.io/library/alpine`); Grype's excludes it
  (`repository_url=index.docker.io/library`).
- UBI10: Trivy would use
  `repository_url=registry.access.redhat.com/ubi10/ubi`; Grype uses
  `repository_url=registry.access.redhat.com/ubi10` (Trivy's leg can't be
  exercised on this fixture at all per T0, so only Grype's form was
  directly confirmed here — consistent with the Alpine fixture's
  confirmed divergence).

Both fixture docs above carry both forms per statement (repeated
`--product` via `vexctl add`), per the c3cdao-landing worked example
(`.openvex/templates/README.md`, "PURL matching footguns").
