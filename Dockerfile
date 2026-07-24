# syntax=docker/dockerfile:1@sha256:87999aa3d42bdc6bea60565083ee17e86d1f3339802f543c0d03998580f9cb89
#
# Build stage
FROM ghcr.io/astral-sh/uv:python3.14-alpine@sha256:bc51d7be0e521c3851c883229c731f238388db3db0a41775ec2d4ca1babd64d8 AS build
WORKDIR /app
COPY pyproject.toml LICENSE.txt README.rst supa.env .
COPY src src
RUN uv build --no-cache --wheel --out-dir dist

# Final stage
FROM ghcr.io/astral-sh/uv:python3.14-alpine@sha256:bc51d7be0e521c3851c883229c731f238388db3db0a41775ec2d4ca1babd64d8
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
