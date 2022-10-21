FROM python:3.9-alpine

WORKDIR /app
COPY setup.py setup.cfg ./
COPY pyscraper pyscraper/
RUN python setup.py install -n && \
    rm -r *
