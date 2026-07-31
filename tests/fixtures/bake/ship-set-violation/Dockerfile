ARG BUILDER_IMAGE=alpine:3.20
ARG RUNTIME_IMAGE=alpine:3.20

FROM ${BUILDER_IMAGE} AS build
ARG SVC_NAME=unset
RUN echo "built ${SVC_NAME}" > /svc.txt

FROM ${RUNTIME_IMAGE}
COPY --from=build /svc.txt /svc.txt
CMD ["cat", "/svc.txt"]
