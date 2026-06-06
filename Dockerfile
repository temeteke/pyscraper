FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg libxslt-dev && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir lxml

ARG VERSION=0.0

WORKDIR /app
COPY pyproject.toml setup.py setup.cfg ./
COPY pyscraper pyscraper/
RUN VERSION_CLEAN="$(echo "$VERSION" | sed 's/^v//' | grep -oE '^[0-9]+\.[0-9]+\.[0-9]+' || echo '0.0')" && \
    SETUPTOOLS_SCM_PRETEND_VERSION_FOR_PYSCRAPER="$VERSION_CLEAN" \
    pip install --no-cache-dir . && \
    rm -r *
