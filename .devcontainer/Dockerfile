FROM mcr.microsoft.com/devcontainers/python:3.12

WORKDIR /app
COPY setup.py setup.cfg ./
COPY pyscraper pyscraper/
RUN pip install -e ".[gateway]"

RUN pip install pytest pytest-cov pytest-mock pre-commit
