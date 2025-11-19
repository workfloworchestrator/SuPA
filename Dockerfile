# syntax=docker/dockerfile:1
#
# Build stage
FROM python:3.13-slim-trixie AS build
ENV PIP_ROOT_USER_ACTION=ignore
WORKDIR /app
RUN set -ex; apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*
RUN pip install --upgrade pip --no-cache-dir
RUN pip install build --no-cache-dir
COPY pyproject.toml LICENSE.txt README.rst supa.env .
COPY src src
RUN python -m build --wheel --outdir dist

# Final stage
FROM python:3.13-slim-trixie
ENV PIP_ROOT_USER_ACTION=ignore
ENV DATABASE_DIR=/usr/local/var/db
RUN set -ex; apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*
RUN pip install --upgrade pip --no-cache-dir
COPY --from=build /app/dist/*.whl /tmp/
RUN pip install /tmp/*.whl --no-cache-dir && rm /tmp/*.whl
RUN groupadd --gid 1000 supa && useradd --uid 1000 --gid 1000 supa
RUN mkdir --parents $DATABASE_DIR && chown supa:supa $DATABASE_DIR
USER supa

EXPOSE 8080/tcp 50051/tcp
ENV PYTHONPATH=/usr/local/etc/supa
CMD ["supa", "serve"]
