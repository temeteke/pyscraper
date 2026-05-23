FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg libxslt-dev && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir lxml

WORKDIR /app
COPY setup.py setup.cfg ./
COPY pyscraper pyscraper/
RUN pip install --no-cache-dir . && \
    rm -r *
