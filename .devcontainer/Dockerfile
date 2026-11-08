FROM mcr.microsoft.com/devcontainers/python:3.12

ENV PATH="/home/vscode/.local/bin:${PATH}"

WORKDIR /app
RUN chown vscode:vscode /app
USER vscode
COPY --chown=vscode:vscode pyproject.toml setup.py setup.cfg ./
COPY --chown=vscode:vscode pyscraper pyscraper/
# The image only COPYs the sources (no .git); pass a placeholder version for
# the editable install. postCreateCommand reinstalls from the mounted
# workspace (which includes .git) with the real version.
RUN SETUPTOOLS_SCM_PRETEND_VERSION_FOR_PYSCRAPER=0.0 \
    python -m pip install --user -e ".[console]"

RUN python -m pip install --user \
    pytest==9.2.0 pytest-cov==7.1.0 pytest-mock==3.17.0 pre-commit==4.7.0
