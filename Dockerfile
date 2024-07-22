# syntax=docker/dockerfile:1
#
FROM python:3.12-slim-bookworm
RUN set -ex; apt-get update; apt-get upgrade -y; rm -rf /var/lib/apt/lists/*
ENV BASEDIR=/usr/local/src/supa
WORKDIR $BASEDIR
COPY . .
RUN pip install -U pip wheel
RUN pip install -e .
RUN python setup.py gen_code
RUN python setup.py install
RUN set -ex; groupadd --gid 1000 supa; useradd --create-home --uid 1000 --gid supa supa
RUN set -ex; mkdir -pv /usr/local/var/db/; chown supa:supa /usr/local/var/db/
USER supa
WORKDIR /home/supa
EXPOSE 8080/tcp 50051/tcp
ENV PYTHONPATH=$PYTHONPATH:/usr/local/etc/supa:$BASEDIR/src/supa/nrm/backends
CMD supa serve
