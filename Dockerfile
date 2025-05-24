FROM python:3.12-alpine

RUN apk add --no-cache ffmpeg && \
    apk add --no-cache --virtual .lxml-deps build-base libc-dev libxslt-dev && \
    pip install --no-cache-dir lxml && \
    apk del .lxml-deps

WORKDIR /app
COPY setup.py setup.cfg ./
COPY pyscraper pyscraper/
RUN pip install --no-cache-dir . && \
    rm -r *
