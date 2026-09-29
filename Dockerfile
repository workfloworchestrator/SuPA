# syntax=docker/dockerfile:1@sha256:ecfaec9ed6d810b56388c508f4121597bfbba70d41a6dfeee4d8cad5f295fc32
#
# Build stage
FROM ghcr.io/astral-sh/uv:python3.14-alpine@sha256:ea7c8f721b5042fb12f6eb051b63469edfeb61c7c00551dbe67d71f182810c66 AS build
ARG VERSION
ENV SETUPTOOLS_SCM_PRETEND_VERSION_FOR_SUPA=${VERSION}
WORKDIR /app
COPY pyproject.toml LICENSE.txt README.rst supa.env .
COPY src src
RUN uv build --no-cache --wheel --out-dir dist

# Final stage
FROM ghcr.io/astral-sh/uv:python3.14-alpine@sha256:ea7c8f721b5042fb12f6eb051b63469edfeb61c7c00551dbe67d71f182810c66
ENV DATABASE_DIR=/usr/local/var/db
COPY --from=build /app/dist/*.whl /tmp/
RUN uv pip install --system --no-cache /tmp/*.whl && rm /tmp/*.whl
RUN addgroup -g 1000 supa && adduser -D -u 1000 -G supa supa
RUN mkdir --parents $DATABASE_DIR && chown supa:supa $DATABASE_DIR
USER supa
EXPOSE 8080/tcp 50051/tcp
ENV PYTHONPATH=/usr/local/etc/supa
ENV TZ=UTC
CMD ["supa", "serve"]
