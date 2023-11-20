FROM mcr.microsoft.com/devcontainers/python:3.12

WORKDIR /app
COPY setup.py setup.cfg ./
COPY pyscraper pyscraper/
RUN python setup.py develop

RUN pip install pytest pre-commit
