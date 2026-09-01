# Minimal, harmless fixture image for selftest-publish-images.yml
# (.github/workflows/selftest-publish-images.yml) — proves the digest-
# verified quarantine publish round trip (quarantine push -> imagetools
# inspect -> imagetools create retag -> digest-match verify) that
# reusable-security-gate.yml's build job and publish-staging-chart.yml's
# publish-images-deferred job together implement, against a fixed, trivial
# fixture, without any external runtime dependency.
#
# FROM scratch (not even a distro base) so this builds fast and has zero
# transitive pull dependencies of its own — the point is to exercise the
# docker/setup-buildx-action + docker/login-action + imagetools
# inspect/create mechanics, not to produce anything runnable.
FROM scratch

# GREETING is a trivial ARG so the selftest workflow's build step has
# something distinctive to bake in (visible in `docker inspect`), proving
# the fixture that gets pushed to quarantine, retagged, and verified is
# actually THIS build, not some other cached image.
ARG GREETING=hello-from-default
COPY hello.txt /hello.txt
LABEL selftest.greeting="${GREETING}"
