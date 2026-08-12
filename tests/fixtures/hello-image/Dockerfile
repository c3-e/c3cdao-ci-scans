# Minimal, harmless fixture image for selftest-publish-images.yml
# (.github/workflows/selftest-publish-images.yml) — proves the SAME
# build+login+push mechanics publish-images-deferred uses (PR-1), against
# a fixed, trivial fixture, without any external runtime dependency.
#
# FROM scratch (not even a distro base) so this builds fast and has zero
# transitive pull dependencies of its own — the point is to exercise the
# docker/setup-buildx-action + docker/login-action + docker/build-push-action
# mechanics, not to produce anything runnable.
FROM scratch

# GREETING is a trivial ARG so the selftest workflow can also exercise the
# publish-images-deferred job's build_args passthrough path (jq-derived
# newline-delimited KEY=value string -> docker/build-push-action's
# build-args: input) end-to-end, not just the no-build-args path.
ARG GREETING=hello-from-default
COPY hello.txt /hello.txt
LABEL selftest.greeting="${GREETING}"
