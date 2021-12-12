# syntax = docker/dockerfile:experimental
FROM python:3.9-alpine

RUN apk add --no-cache firefox-esr chromium chromium-chromedriver curl libxslt ffmpeg && \
    apk add --no-cache --virtual .lxml-deps build-base libc-dev libxslt-dev && \
    pip install lxml && \
    apk del .lxml-deps && \
    apk add --no-cache --virtual .geckodriver-deps tar && \
    curl -L https://github.com/mozilla/geckodriver/releases/download/v0.30.0/geckodriver-v0.30.0-linux64.tar.gz | tar xz -C /usr/local/bin/ && \
    apk del .geckodriver-deps

# No module named 'setuptools_rust'を回避するため
RUN pip install -U setuptools

RUN apk add --no-cache --virtual .python-deps build-base libffi-dev

WORKDIR /app
COPY setup.py setup.cfg ./
COPY pyscraper pyscraper/
RUN python setup.py install -n && \
    rm -r *

RUN apk del .python-deps

#RUN --mount=target=/app pip install /app
