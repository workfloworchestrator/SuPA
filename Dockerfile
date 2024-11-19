# syntax=docker/dockerfile:1
#
FROM python:3.12-slim-bookworm
RUN set -ex; apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*
ENV BASEDIR=/usr/local/src/supa
WORKDIR $BASEDIR
COPY . .
RUN pip install -U pip wheel
RUN pip install -r requirements.txt
RUN python setup.py gen_code
RUN python setup.py install
EXPOSE 8080/tcp 50051/tcp
ENV PYTHONPATH=/usr/local/etc/supa:$BASEDIR/src/supa/nrm/backends
CMD ["supa", "serve"]
