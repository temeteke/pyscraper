FROM mcr.microsoft.com/devcontainers/python:3.12

WORKDIR /app
COPY pyproject.toml setup.py setup.cfg ./
COPY pyscraper pyscraper/
# The image only COPYs the sources (no .git); pass a placeholder version for
# the editable install. postCreateCommand reinstalls from the mounted
# workspace (which includes .git) with the real version.
RUN SETUPTOOLS_SCM_PRETEND_VERSION_FOR_PYSCRAPER=0.0 \
    pip install -e ".[gateway]"

RUN pip install pytest pytest-cov pytest-mock pre-commit
