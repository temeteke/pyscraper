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

```bash
# Code formatter
pip install black isort

# Linters
pip install flake8 pylint

# Type checking
pip install mypy
```

---

## Project Structure

```
pyscraper/
├── pyscraper/          # Source code
│   ├── webpage.py      # Web page handling (692 lines)
│   ├── webfile.py      # Web file download (423 lines)
│   ├── hlsfile.py      # HLS stream handling (249 lines)
│   ├── requests.py     # HTTP request mixin
│   └── utils.py        # Utilities
│
├── tests/              # Test code
│   ├── conftest.py     # pytest fixtures & mocks
│   ├── test_webpage.py # WebPage tests
│   ├── test_webfile.py # WebFile tests (unit & integration)
│   ├── test_hlsfile.py # HLSFile tests
│   └── test_utils.py   # Utility tests
│
├── docs/               # Documentation
│   ├── testing.md      # Testing guide
│   ├── development.md  # Development guide (this file)
│   └── analysis/       # Detailed analysis
│
└── pyproject.toml      # Project configuration
```

**Statistics:**
- Total lines of code: 2,446 lines (7 modules)
- Total methods: 153
- Total tests: 218 (unit 114 + integration 104)

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

### Test Writing Guidelines

#### Unit Tests (Recommended)

```python
# tests/test_your_module.py

def test_download_file():
    """Test file download functionality"""
    # No marker needed
    # External HTTP dependencies are automatically mocked

    wf = WebFile("https://example.com/file.txt")
    with wf as f:
        content = f.read()
        assert len(content) > 0
```

#### Integration Tests (When Necessary)

```python
# tests/test_your_module.py

@pytest.mark.integration
def test_download_real_file():
    """Test file download with actual HTTP communication"""
    # Real network access occurs

    wf = WebFile("https://httpbin.org/bytes/1024")
    with wf as f:
        content = f.read()
        assert len(content) == 1024
```

---

## Coding Conventions

### Python Style

```python
# Follow PEP 8
# Indentation: 4 spaces
# Line length: 100 characters max (recommended)

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

## Recent Improvements

### Test Infrastructure Enhancements (2024)

#### 1. Unified to pytest
**Before:** unittest and pytest were mixed
**After:** All tests unified to pytest

**Benefits:**
- ✅ Leverage fixtures
- ✅ Simplified parametrized tests
- ✅ Access to plugin ecosystem

#### 2. HTTP Communication Mocking
**Before:** All tests used real HTTP communication (slow, unstable)
**After:** Unit tests fully mock HTTP communication

**Implementation:**
```python
# tests/conftest.py

@pytest.fixture(autouse=True)
def mock_external_http(request, mocker):
    """Automatically mock external HTTP"""
    if 'integration' in request.keywords:
        yield  # Skip mocks for integration tests
        return

    # Mock requests.Session.get
    mocker.patch('requests.Session.get', side_effect=mock_get)
```

**Benefits:**
- ✅ Test execution time: minutes → 1.2s (99% reduction)
- ✅ Offline execution possible
- ✅ 100% reproducibility

#### 3. Systematized Test Classification
**Before:** All tests ran by default (slow)
**After:** Clear separation between unit and integration tests

**Implementation:**
```python
# pyproject.toml

[tool.pytest.ini_options]
markers = [
    "integration: Integration tests (HTTP, Curl, Browser)",
]
addopts = "-m 'not integration'"
```

**Benefits:**
- ✅ Default execution: unit tests only (114 tests, 1.2s)
- ✅ Explicit execution: integration tests (104 tests, minutes)
- ✅ CI/CD cost reduction

#### 4. FFmpeg Mocking
**Before:** Actual ffmpeg command execution (slow, environment-dependent)
**After:** subprocess.run mocked

**Implementation:**
```python
# tests/conftest.py

class MockFFmpeg:
    """Mock FFmpeg that creates output files without running ffmpeg."""
    def run(self, *args, **kwargs):
        # Create output file (don't actually run ffmpeg)
        if self.outputs:
            output_file = list(self.outputs.keys())[0]
            Path(output_file).write_bytes(b'mock ffmpeg output')
```

**Benefits:**
- ✅ HLS tests: minutes → <1s
- ✅ ffmpeg installation not required (unit tests)

#### 5. WebPageCurl Integration Test Migration
**Before:** subprocess.run(['curl', ...]) mocked (can't verify actual behavior)
**After:** Migrated to integration tests, executes real curl commands

**Implementation:**
```python
# tests/test_webpage.py

@pytest.mark.integration
class TestWebPageCurl(MixinTestWebPage):
    """Integration tests for WebPageCurl using actual curl command."""
```

**Benefits:**
- ✅ Can verify actual curl behavior
- ✅ Excluded from unit tests (faster)
- ✅ Clarified as environment-dependent test

---

## Architecture

### Main Class Responsibilities

#### WebPage Family
```
WebPage (abstract base class)
├── WebPageRequests   # Uses requests library
├── WebPageCurl       # Uses curl command
└── WebPageSelenium   # Uses Selenium
    ├── WebPageFirefox
    └── WebPageChrome
```

**Responsibilities:**
- Fetch HTML from URLs
- Parse HTML (lxml)
- Element retrieval via XPath/CSS selectors

#### WebFile
```
WebFile
├── RequestsMixin     # HTTP session management
└── HLSFile          # HLS-specific extension
```

**Responsibilities:**
- File downloads
- Range request support
- Progress callbacks
- HLS stream processing (HLSFile)

---

## Known Technical Issues

### Refactoring Candidates

#### 1. Consolidate State Validation [Priority: High]
**Problem:** State checks like `if self.driver is None:` appear in 28+ places

**Proposal:**
```python
def _ensure_open(self):
    """Ensure driver is opened."""
    if self.driver is None:
        raise WebPageError("Driver is not opened yet")

# Usage
@property
def html(self):
    self._ensure_open()
    return self.driver.page_source
```

**Impact:** ~50 lines of boilerplate removed

#### 2. Unify Selenium Driver Classes [Priority: Medium]
**Problem:** `WebPageFirefox` and `WebPageChrome` have 95% identical code

**Proposal:**
```python
class WebPageSelenium:
    def __init__(self, url, driver_type='firefox', ...):
        self.driver_type = driver_type

    def _create_driver(self):
        if self.driver_type == 'firefox':
            return self._create_firefox_driver()
        elif self.driver_type == 'chrome':
            return self._create_chrome_driver()
```

**Impact:** ~40-50 lines of duplication removed

#### 3. Simplify Cache Invalidation [Priority: High]
**Problem:** `hlsfile.py` `clear_cache()` has 5 repeated try/except blocks

**Current:**
```python
try:
    del self.m3u8_obj
except AttributeError:
    pass
# ... repeated 4 times
```

**Proposal:**
```python
for prop_name in ['m3u8_obj', 'm3u8_content', 'web_files', 'filestem', 'filesuffix']:
    try:
        delattr(self, prop_name)
    except AttributeError:
        pass
```

**Impact:** ~10 lines removed, better maintainability

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
- [ffmpy](https://github.com/Ch00k/ffmpy)

### Project Documentation
- [testing.md](./testing.md) - Testing guide
- [analysis/codebase.md](./analysis/codebase.md) - Codebase analysis
- [analysis/modules.md](./analysis/modules.md) - Module structure
