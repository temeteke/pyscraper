FROM python:3.9-alpine

RUN apk add --no-cache ffmpeg && \
    apk add --no-cache --virtual .lxml-deps build-base libc-dev libxslt-dev && \
    pip install lxml && \
    apk del .lxml-deps

WORKDIR /app
COPY setup.py setup.cfg ./
COPY pyscraper pyscraper/
RUN python setup.py install -n && \
    rm -r *
