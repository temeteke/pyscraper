# syntax = docker/dockerfile:experimental
FROM python:3.8.0-alpine3.10

RUN apk add --no-cache firefox-esr chromium chromium-chromedriver curl libxslt && \
    apk add --no-cache --virtual .lxml-deps gcc libc-dev libxslt-dev && \
    pip install lxml && \
    apk del .lxml-deps && \
    apk add --no-cache --virtual .geckodriver-deps tar && \
    curl -L https://github.com/mozilla/geckodriver/releases/download/v0.25.0/geckodriver-v0.25.0-linux64.tar.gz | tar xz -C /usr/local/bin/ && \
    apk del .geckodriver-deps

WORKDIR /app
COPY setup.py setup.cfg ./
COPY pyscraper pyscraper/
RUN python setup.py install -n && \
    rm -r *

#RUN --mount=target=/app pip install /app
