# N=3 fixture service image (T-2; upgraded bootable by T-7 for the live
# cluster-smoke proof): a static HTTP server that serves /srv/healthz and
# stays alive, runnable on a read-only root filesystem as nonroot. The
# gate injects hardened bases via the blessed ARG pair; the runtime base
# resolves to a Chainguard python image, so the chart runs
# `python3 -m http.server`. The alpine defaults exist only so the ARG
# pair has committed literals (hardened-args lint checks presence).
ARG BUILDER_IMAGE=alpine:3.20
ARG RUNTIME_IMAGE=alpine:3.20

FROM ${BUILDER_IMAGE} AS build
ARG SVC_NAME=unset
# /tmp, not /: hardened builder bases (gate-injected BUILDER_IMAGE) run
# nonroot and cannot write to the filesystem root.
RUN mkdir -p /tmp/srv && echo "built ${SVC_NAME}" > /tmp/srv/healthz \
    && cp /tmp/srv/healthz /tmp/srv/svc.txt

FROM ${RUNTIME_IMAGE}
COPY --from=build /tmp/srv /srv
# Port comes from the chart's per-container args (one pod shares a
# network namespace, so each fixture container needs its own port).
ENTRYPOINT ["python3", "-m", "http.server", "-d", "/srv"]
CMD ["8080"]
