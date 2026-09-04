# Changelog

## [0.8.0](https://github.com/c3-e/c3cdao-ci-scans/compare/v0.7.4...v0.8.0) (2026-09-04)


### Features

* add caller template + lint rule for publish-staging-chart ([49a37d6](https://github.com/c3-e/c3cdao-ci-scans/commit/49a37d63fde5d5eb97b7d20149726cbeb8e1ca40))
* add composed-smoke.yml reusable workflow (PR-3b) ([a85846f](https://github.com/c3-e/c3cdao-ci-scans/commit/a85846f38001c2501b1f7cb7fc8ac6f54ede46a1))
* add publish-staging-chart.yml reusable workflow ([1e8d877](https://github.com/c3-e/c3cdao-ci-scans/commit/1e8d877bac3c19172009345d9e9f4664fd1f1f68))
* add publish-staging-chart.yml reusable workflow ([376dcaf](https://github.com/c3-e/c3cdao-ci-scans/commit/376dcaf2387fca6bbbaac6d9750c5b631465f139))
* derive publish-staging-chart's image targets from compose_file, not hand-typed images: ([6fac89a](https://github.com/c3-e/c3cdao-ci-scans/commit/6fac89a371359554a10edcce9c9e64850154e0ba))
* implement publish-images-deferred job for real (PR-1) ([cbcf19d](https://github.com/c3-e/c3cdao-ci-scans/commit/cbcf19d031053bf005e0aef7b2288cc49aec12ab))
* validate chart shape before publishing staging chart ([#35](https://github.com/c3-e/c3cdao-ci-scans/issues/35)) ([680da46](https://github.com/c3-e/c3cdao-ci-scans/commit/680da46638885b8d49a67e39782f09acd4bef26e))


### Bug Fixes

* composed-smoke.yml can't helm-dependency-build local/packaged deps ([39ade11](https://github.com/c3-e/c3cdao-ci-scans/commit/39ade1105236b6c201a120c1b6662e32f93f7613))
* **composed-smoke:** capture helm-test hook pod diagnostics on failure too ([130f847](https://github.com/c3-e/c3cdao-ci-scans/commit/130f847b3eae2326aafb7ec0daffef25c704cc7d))
* **composed-smoke:** layered umbrella_values + init-container log capture ([57c1d7f](https://github.com/c3-e/c3cdao-ci-scans/commit/57c1d7f88da22e09e8fb708a6623c308c352153e))
* **composed-smoke:** support layered umbrella_values + capture init-container logs on failure ([94c77ae](https://github.com/c3-e/c3cdao-ci-scans/commit/94c77aed325bb7204a5f5aa2e36c7cd9f1dab10f))
* correct stale packages:write test to match d2dea05's actual fix ([5fd9337](https://github.com/c3-e/c3cdao-ci-scans/commit/5fd93376374e0196406dfa20217ef4202441266f))
* doc drift, stale test, dead code, resolver hardening, wire pytest into CI ([dd3649d](https://github.com/c3-e/c3cdao-ci-scans/commit/dd3649d0e743fb573861bbb7294344a44e34c06e))
* gate hardened-registry ok-flags on login exit status, add declared tier ([f1f8f56](https://github.com/c3-e/c3cdao-ci-scans/commit/f1f8f56e3c4876ba08e39742bb91d2f47726c74b))
* harden publish-staging-chart/composed-smoke callee-ref resolvers, consolidate their tests ([19005bf](https://github.com/c3-e/c3cdao-ci-scans/commit/19005bfed15b0fd26ac12241fdb9512f83c03eb0))
* hardened-registry login exit-status bug + caller-declared registry tier ([a86b114](https://github.com/c3-e/c3cdao-ci-scans/commit/a86b1141bff6f5028e75e01e7181d83c00e9b6f6))
* invalid OCI reference in selftest destination tag; remove temp registration trigger ([38066f7](https://github.com/c3-e/c3cdao-ci-scans/commit/38066f79f87f77babee3039ac9137a265e818fc4))
* move packages:write to workflow-level permissions, not job-level ([d2dea05](https://github.com/c3-e/c3cdao-ci-scans/commit/d2dea050f71ddae57d3fc30d6f9fbcd47c809692))
* omit trailing pilot segment from OCI dest to match locked path shape ([#33](https://github.com/c3-e/c3cdao-ci-scans/issues/33)) ([44c8ed6](https://github.com/c3-e/c3cdao-ci-scans/commit/44c8ed67d84dd13f7265ef7df95d9f240cc7533c))
* pin composed-smoke.yml's setup-uv/setup-helm to real commit SHAs, drop internal-only labels from shipped output ([e8ac133](https://github.com/c3-e/c3cdao-ci-scans/commit/e8ac133ebe4633205e9cd56957ac3093d1b720e6))
* recognize publish_images in caller-lint KNOWN_INPUTS ([f0ea378](https://github.com/c3-e/c3cdao-ci-scans/commit/f0ea378a55db43ebdd598c9edcb30a34bbc45dd1))
* replace derive_bom.py's hand-rolled --set/--out-dir parser with argparse ([#38](https://github.com/c3-e/c3cdao-ci-scans/issues/38)) ([21bf77a](https://github.com/c3-e/c3cdao-ci-scans/commit/21bf77a45320fc9430e3f14664d71e4901ea1cc3))
* replace grep-based helm.sh/hook detection with a real yq parse ([db6432a](https://github.com/c3-e/c3cdao-ci-scans/commit/db6432a65e2afa238cbff7c0c43f4c3f91efcedb))
* resolve callee (ci-scans) ref via yq in composed-smoke.yml and publish-staging-chart.yml too ([4b2e945](https://github.com/c3-e/c3cdao-ci-scans/commit/4b2e9457f7068f4240cc7acb3f315634f0b319ef))
* run helm dependency build before packaging ([#34](https://github.com/c3-e/c3cdao-ci-scans/issues/34)) ([8613d62](https://github.com/c3-e/c3cdao-ci-scans/commit/8613d62c5bd3e25c0caf0504b1db488cdc8d8cd6))
* **security:** callee-ref resolver — yq parsing, decoy-job/fail-closed/single-site hardening ([#37](https://github.com/c3-e/c3cdao-ci-scans/issues/37)) ([c8de4ce](https://github.com/c3-e/c3cdao-ci-scans/commit/c8de4ce7dd8a3dc77fa6244cb43ca73186e856a3))


### Documentation

* document caller permissions gotcha (workflow-level XOR job-level) ([#32](https://github.com/c3-e/c3cdao-ci-scans/issues/32)) ([eae5d22](https://github.com/c3-e/c3cdao-ci-scans/commit/eae5d22a87d83cc01fe864814dbd26a83f3eefa5))
* document publish_images in INPUTS.md, fix stale field count ([27ef22c](https://github.com/c3-e/c3cdao-ci-scans/commit/27ef22c19d7bad73342a6f5539a97f7b5ddb0b5d))
* fix regressed em-dash, drop umbrella repo name from 2 docs, scope a false-positive test ([55f8745](https://github.com/c3-e/c3cdao-ci-scans/commit/55f8745e51d39226a2643cf425c6a2f5743e62fb))
* mention the helm.sh/hook: test exemption in RUNBOOK.md ([3061103](https://github.com/c3-e/c3cdao-ci-scans/commit/30611039887b21f09c2bf1cfe1534d5bd2417af7))
* **site:** add publish-staging-chart.yml and composed-smoke.yml ([5e2d57a](https://github.com/c3-e/c3cdao-ci-scans/commit/5e2d57af10b45272676e9a8f194df76c5cb0583e))

## [0.7.4](https://github.com/c3-e/c3cdao-ci-scans/compare/v0.7.3...v0.7.4) (2026-08-11)


### Bug Fixes

* extract build-matrix emission into scripts/lib ([1f4eb26](https://github.com/c3-e/c3cdao-ci-scans/commit/1f4eb26a713770abaed9484b7ed95be025cf331c))


### Documentation

* **site:** sync design site with the shipped gate ([454360c](https://github.com/c3-e/c3cdao-ci-scans/commit/454360c47fe67e695319680364d862d4a7142003))

## [0.7.3](https://github.com/c3-e/c3cdao-ci-scans/compare/v0.7.2...v0.7.3) (2026-08-07)


### Documentation

* document release-please's Conventional Commits requirement ([#24](https://github.com/c3-e/c3cdao-ci-scans/issues/24)) ([5c80396](https://github.com/c3-e/c3cdao-ci-scans/commit/5c803963dadb201eb1afe068c36ec7fc91d1499e))

## [0.7.2](https://github.com/c3-e/c3cdao-ci-scans/compare/v0.7.1...v0.7.2) (2026-08-07)


### Documentation

* **runbook:** add worked example for externally-delivered image VEX ([#20](https://github.com/c3-e/c3cdao-ci-scans/issues/20)) ([db225b7](https://github.com/c3-e/c3cdao-ci-scans/commit/db225b72f6460130d5088a39442e22e17ee8d137))

## [0.7.1](https://github.com/c3-e/c3cdao-ci-scans/compare/v0.7.0...v0.7.1) (2026-08-07)


### Performance

* **gate:** add GHA layer caching to build job ([#18](https://github.com/c3-e/c3cdao-ci-scans/issues/18)) ([d38bd47](https://github.com/c3-e/c3cdao-ci-scans/commit/d38bd476015f08abbf26d58e5425447b4c7c10d0))

## [0.7.0](https://github.com/c3-e/c3cdao-ci-scans/compare/v0.6.0...v0.7.0) (2026-08-07)


### Features

* add release-please version automation ([370b109](https://github.com/c3-e/c3cdao-ci-scans/commit/370b109823352e6eeb6b674ea9dab64a0d8cf93c))
* add release-please version automation ([4a0f336](https://github.com/c3-e/c3cdao-ci-scans/commit/4a0f3366818bec3020b48f27d50dbb29a97fb9de))
* **export-bundle:** post/update PR comment with scan-results summary ([f69b637](https://github.com/c3-e/c3cdao-ci-scans/commit/f69b63766c9b71e059ad8512c74c845139249f40))
* **export-bundle:** PR comment with scan-results summary ([77fd094](https://github.com/c3-e/c3cdao-ci-scans/commit/77fd09427d8d14bd981b812d100a76df3b00af6a))
* **gate:** Trivy SARIF upload to code scanning, fail-soft [VEX-8] ([fe1142b](https://github.com/c3-e/c3cdao-ci-scans/commit/fe1142b645e0651845b0110a36530d5ad5a01a67))


### Bug Fixes

* **gate:** Grype VEX identity via job-local registry [VEX-7] ([21583b1](https://github.com/c3-e/c3cdao-ci-scans/commit/21583b18b9213c438deeaf1fb95c364de038b4f4))
* **gate:** job-local registry gives gate-built images a Grype-matchable VEX identity [VEX-7] ([11ebf33](https://github.com/c3-e/c3cdao-ci-scans/commit/11ebf33d39f38996d9f7a6d6efcf865347ccb62f))
* **gate:** registry idempotency guard checks running state, not mere existence ([3df9ef8](https://github.com/c3-e/c3cdao-ci-scans/commit/3df9ef800afa8201898c4b27b0e64fd5749db2b0))
* **gate:** remove duplicate security-events permission key [VEX-8] ([980f0da](https://github.com/c3-e/c3cdao-ci-scans/commit/980f0dafe03d36e8851ac800a28e3c08f10514a7))
* **gate:** remove SARIF-upload-to-code-scanning (VEX-8 reversal) ([32d98ab](https://github.com/c3-e/c3cdao-ci-scans/commit/32d98ab3af994bcd2b087a87b8cc9a7852634b01))
* **gate:** remove SARIF-upload-to-code-scanning (VEX-8 reversal) ([a3c1eb1](https://github.com/c3-e/c3cdao-ci-scans/commit/a3c1eb1874bbf0d19554c9e8130e8987a7304096))
* **gate:** resolvable upload-sarif pin + namespaced SARIF category [VEX-8] ([d391c91](https://github.com/c3-e/c3cdao-ci-scans/commit/d391c9128689d2d68dc0dfdb185c917e40d1fc90))
* **gate:** review findings — SCAN_REF fallback on always() steps, document fail-closed publish [VEX-7/VEX-8] ([a81a607](https://github.com/c3-e/c3cdao-ci-scans/commit/a81a607f049baaa701c59b05a013b79b6fe2e033))
* **gate:** Trivy SARIF upload to code scanning, fail-soft [VEX-8] ([7d2523d](https://github.com/c3-e/c3cdao-ci-scans/commit/7d2523d82729ec712edf09474e98344053549f78))
* **gate:** use job.workflow_sha/job.workflow_ref, not github.job_workflow_sha ([26aa631](https://github.com/c3-e/c3cdao-ci-scans/commit/26aa6319afe1111d11cd6d8b7419eb8867e9a868))
* **gate:** use job.workflow_sha/job.workflow_ref, not github.job_workflow_sha ([566efd0](https://github.com/c3-e/c3cdao-ci-scans/commit/566efd068b23ce3bb451502b8fb8cb045c20c4c2))
* **release-please:** register the root path as a package ([#17](https://github.com/c3-e/c3cdao-ci-scans/issues/17)) ([a826e90](https://github.com/c3-e/c3cdao-ci-scans/commit/a826e907999be7bedd96e7bff4c7a4fcb301fce5))
* **release-please:** stop forcing non-manifest mode ([#16](https://github.com/c3-e/c3cdao-ci-scans/issues/16)) ([4e7a250](https://github.com/c3-e/c3cdao-ci-scans/commit/4e7a250d12f3669130e007f8d210f03a8431ec3f))
