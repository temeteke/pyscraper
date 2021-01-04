# syntax = docker/dockerfile:experimental
FROM python:3.9-alpine

RUN apk add --no-cache firefox-esr chromium chromium-chromedriver curl libxslt && \
    apk add --no-cache --virtual .lxml-deps gcc libc-dev libxslt-dev && \
    pip install lxml && \
    apk del .lxml-deps

WORKDIR /app
COPY setup.py setup.cfg ./
COPY pyscraper pyscraper/
RUN python setup.py install -n && \
    rm -r *

#RUN --mount=target=/app pip install /app
