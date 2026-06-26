# syntax=docker/dockerfile:1@sha256:87999aa3d42bdc6bea60565083ee17e86d1f3339802f543c0d03998580f9cb89
#
# Build stage
FROM ghcr.io/astral-sh/uv:python3.14-alpine@sha256:b88327b47c610b205ce2ffd633bcc8f5ad44c6bc20c156eace6dc3d97ac71da5 AS build
WORKDIR /app
COPY pyproject.toml LICENSE.txt README.rst supa.env .
COPY src src
RUN uv build --no-cache --wheel --out-dir dist

# Final stage
FROM ghcr.io/astral-sh/uv:python3.14-alpine@sha256:b88327b47c610b205ce2ffd633bcc8f5ad44c6bc20c156eace6dc3d97ac71da5
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
