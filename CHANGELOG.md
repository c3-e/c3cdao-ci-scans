# Changelog

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
