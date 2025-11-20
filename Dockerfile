# syntax=docker/dockerfile:1
#
# Build stage
FROM python:3.14-alpine AS build
#
ENV PIP_ROOT_USER_ACTION=ignore
#
WORKDIR /app
RUN set -ex; apk update && apk upgrade
RUN pip install --upgrade pip build --no-cache-dir
COPY pyproject.toml LICENSE.txt README.rst supa.env .
COPY src src
RUN python -m build --wheel --outdir dist

# Final stage
FROM python:3.14-alpine
#
ENV PIP_ROOT_USER_ACTION=ignore
ENV DATABASE_DIR=/usr/local/var/db
#
RUN set -ex; apk update && apk upgrade --no-cache
RUN pip install --upgrade pip --no-cache-dir
COPY --from=build /app/dist/*.whl /tmp/
RUN pip install /tmp/*.whl --no-cache-dir && rm /tmp/*.whl
RUN addgroup -g 1000 supa && adduser -D -u 1000 -G supa supa
RUN mkdir --parents $DATABASE_DIR && chown supa:supa $DATABASE_DIR
USER supa
#
EXPOSE 8080/tcp 50051/tcp
ENV PYTHONPATH=/usr/local/etc/supa
ENV TZ=UTC
CMD ["supa", "serve"]
