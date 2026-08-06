# N=3 fixture service image (upgraded bootable for the live
# cluster-smoke proof): a static HTTP server that serves /srv/healthz and
# stays alive, runnable on a read-only root filesystem as nonroot. The
# gate injects no base images; the committed defaults are the bases the
# build uses. The runtime default carries python3 so the chart's
# `python3 -m http.server` entrypoint boots (the chart runs each
# container as uid 65532 with a read-only root filesystem).
ARG BUILDER_IMAGE=alpine:3.20
ARG RUNTIME_IMAGE=python:3.12-alpine

FROM ${BUILDER_IMAGE} AS build
ARG SVC_NAME=unset
# /tmp, not /: nonroot builder bases cannot write to the filesystem root.
RUN mkdir -p /tmp/srv && echo "built ${SVC_NAME}" > /tmp/srv/healthz \
    && cp /tmp/srv/healthz /tmp/srv/svc.txt

FROM ${RUNTIME_IMAGE}
COPY --from=build /tmp/srv /srv
# Port comes from the chart's per-container args (one pod shares a
# network namespace, so each fixture container needs its own port).
ENTRYPOINT ["python3", "-m", "http.server", "-d", "/srv"]
CMD ["8080"]
