# syntax=docker/dockerfile:1@sha256:2780b5c3bab67f1f76c781860de469442999ed1a0d7992a5efdf2cffc0e3d769
#
# Build stage
FROM ghcr.io/astral-sh/uv:python3.14-alpine@sha256:be28b44a377567c053ab1817da02ba6721264a9e3880ec8fe197180ae8b19f41 AS build
WORKDIR /app
COPY pyproject.toml LICENSE.txt README.rst supa.env .
COPY src src
RUN uv build --no-cache --wheel --out-dir dist

# Final stage
FROM ghcr.io/astral-sh/uv:python3.14-alpine@sha256:be28b44a377567c053ab1817da02ba6721264a9e3880ec8fe197180ae8b19f41
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
