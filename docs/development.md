# Development Guide

Development guide for the pyscraper project.

## Setup

### Development Environment

```bash
# Clone repository
git clone https://github.com/temeteke/pyscraper.git
cd pyscraper

# Install development dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/
```

### Recommended Tools

Linting and formatting are handled by ruff (see `pyproject.toml` and
`.pre-commit-config.yaml`):

```bash
# Run the linter
ruff check .

# Run the formatter
ruff format .
```

---

## Project Structure

```
pyscraper/
├── pyscraper/          # Source code
│   ├── webpage.py      # Abstract WebPage base class
│   ├── webpage_requests.py  # requests-based backend
│   ├── webpage_curl.py      # curl-based backend
│   ├── webpage_selenium.py  # Selenium backend (Firefox/Chrome)
│   ├── webpage_playwright.py  # Playwright backend (Chromium/Firefox/WebKit)
│   ├── webfile.py      # Web file download
│   ├── hlsfile.py      # HLS stream handling
│   ├── requests.py     # HTTP request mixin
│   ├── utils.py        # Utilities
│   └── constants.py    # Shared constants
│
├── tests/              # Test code
│   ├── conftest.py     # pytest fixtures & mocks
│   ├── test_webpage.py # WebPage tests (unit + Selenium integration)
│   ├── test_webpage_playwright.py  # Playwright tests
│   ├── test_webfile.py # WebFile tests (unit & integration)
│   ├── test_hlsfile.py # HLSFile tests
│   └── test_utils.py   # Utility tests
│
├── docs/               # Documentation
│   ├── architecture.md # Module responsibilities and design decisions
│   ├── development.md  # Development guide (this file)
│   ├── operations.md   # Grid/Hub operation and Docker
│   └── testing.md      # Testing guide
│
├── servers/            # Container servers (flat, family-prefixed)
│   ├── playwright_hub.py               # Hub relay + node registry
│   ├── playwright_node.py              # launch-server node
│   ├── playwright-entrypoint-node.sh   # Xvfb/x11vnc/noVNC chain
│   ├── playwright_session_manager.py   # Playwright sessions + save + state-files
│   └── selenium_session_manager.py     # Selenium sessions (Grid REST)
│
└── pyproject.toml      # Project configuration
```

For module responsibilities and design decisions, see
[architecture.md](architecture.md). Test counts and line counts are
intentionally not listed here; use `pytest --collect-only -q` for the
current test inventory.

---

## Versioning

### Version Scheme

Follows SemVer (major.minor.patch).

| Bump | Criteria |
|------|----------|
| major | Incompatible API changes |
| minor | Backward-compatible feature additions |
| patch | Backward-compatible bug fixes |

### Tag Format

```
v<major>.<minor>.<patch>
```

Examples: `v1.0.0`, `v1.1.0`, `v2.0.0`

### Version Resolution

Resolved automatically by setuptools-scm from Git tags.
Not written to files; obtained at runtime via `pyscraper.__version__`.

### Release Procedure

```bash
# Create a GitHub Release (creates tag + release notes + triggers Docker build)
# gh CLI is pre-installed on GitHub Actions runners and in the devcontainer
gh release create v1.1.0 --generate-notes

# For hotfixes targeting a specific commit:
gh release create v1.1.0 --generate-notes --target <commit-hash>
```

---

## Test-Driven Development

### Development Flow

```bash
# 1. Write tests for new feature (tests/test_*.py)
# 2. Verify test fails
pytest tests/test_your_module.py::test_new_feature -v

# 3. Implement feature
# 4. Verify test passes
pytest tests/test_your_module.py::test_new_feature -v

# 5. Run all unit tests
pytest tests/ -v

# 6. Add integration tests if needed
pytest tests/ -m integration -v
```

For test-writing guidelines (unit vs integration examples), mock
infrastructure, and execution strategy, see [testing.md](testing.md).

---

## Coding Conventions

### Python Style

```python
# Follow PEP 8
# Indentation: 4 spaces
# Line length: 99 characters max (see [tool.ruff] in pyproject.toml)

# Class names: PascalCase
class WebPageRequests:
    pass

# Function/variable names: snake_case
def download_file(url, filename):
    file_path = Path(filename)
    ...

# Constants: UPPER_CASE
DEFAULT_TIMEOUT = 10
MAX_RETRIES = 3
```

### Docstrings

```python
def download_file(url: str, directory: Path) -> Path:
    """Download a file from the specified URL.

    Args:
        url: Download source URL
        directory: Destination directory

    Returns:
        Path to the downloaded file

    Raises:
        WebFileError: When download fails
    """
    ...
```

---

## Contributing

### Pull Request Workflow

1. **Create or check Issue**
2. **Create branch**
   ```bash
   git checkout -b feature/your-feature
   ```

3. **Development**
   - Write code
   - Write tests
   - Run unit tests

4. **Commit**
   ```bash
   pytest tests/ -v
   git add -A
   git commit -m "Add your feature"
   ```

5. **Push**
   ```bash
   git push origin feature/your-feature
   ```

6. **Create Pull Request**
   - Create PR on GitHub
   - CI/CD runs unit tests
   - Wait for review

7. **After Merge**
   - Integration tests run on main branch

---

## References

### External Documentation
- [pytest](https://docs.pytest.org/)
- [requests](https://requests.readthedocs.io/)
- [lxml](https://lxml.de/)
- [Selenium](https://selenium-python.readthedocs.io/)
- [Playwright](https://playwright.dev/python/)
- [ffmpy](https://github.com/Ch00k/ffmpy)

### Project Documentation
- [architecture.md](architecture.md) - Module responsibilities and design decisions
- [operations.md](operations.md) - Grid/Hub operation and Docker
- [testing.md](testing.md) - Testing guide
