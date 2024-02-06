FROM python:3.8-slim
ENV BASEDIR=/usr/local/src/supa
WORKDIR $BASEDIR
COPY . .
RUN pip install -U pip wheel
RUN pip install -e .
RUN python setup.py gen_code
RUN python setup.py install
EXPOSE 4321/tcp 8080/tcp 50051/tcp
ENV PYTHONPATH=$PYTHONPATH:/usr/local/etc/supa:$BASEDIR/src/supa/nrm/backends
CMD supa serve
