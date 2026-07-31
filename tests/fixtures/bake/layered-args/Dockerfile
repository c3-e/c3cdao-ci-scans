# Three distinguishable layers: --set > build.args > this default.
ARG RUNTIME_IMAGE=dockerfile-default

FROM alpine:3.20 AS build
ARG RUNTIME_IMAGE
RUN echo "RUNTIME_IMAGE=${RUNTIME_IMAGE}" | tee /arg.txt

FROM alpine:3.20
COPY --from=build /arg.txt /arg.txt
CMD ["cat", "/arg.txt"]
