ARG EXTRA_ARG=unset

FROM alpine:3.20
ARG EXTRA_ARG
RUN echo "EXTRA_ARG=${EXTRA_ARG}" > /arg.txt
CMD ["cat", "/arg.txt"]
