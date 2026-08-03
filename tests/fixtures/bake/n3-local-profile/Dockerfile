ARG BUILDER_IMAGE=alpine:3.20
ARG RUNTIME_IMAGE=alpine:3.20

FROM ${BUILDER_IMAGE} AS build
ARG SVC_NAME=unset
# /tmp, not /: hardened builder bases (gate-injected BUILDER_IMAGE) run
# nonroot and cannot write to the filesystem root.
RUN echo "built ${SVC_NAME}" > /tmp/svc.txt

FROM ${RUNTIME_IMAGE}
COPY --from=build /tmp/svc.txt /svc.txt
CMD ["cat", "/svc.txt"]
