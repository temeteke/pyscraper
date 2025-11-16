# Claude AI Assistant Guide for PyScraper

This document provides context for Claude AI assistants working on the pyscraper project.

## Project Overview

**PyScraper** is a Python library for web scraping and file downloading with support for:
- HTTP requests (via `requests` library)
- Browser automation (via Selenium - Firefox/Chrome)
- Command-line tools (via `curl`)
- HLS (HTTP Live Streaming) video downloads

**Key Stats:**
- 2,446 lines of code across 7 modules
- 153 methods
- 218 tests (114 unit + 104 integration)
- Test execution: ~1.2s (unit), minutes (integration)

## Architecture

### Class Hierarchy

```
WebPage (abstract base)
├── WebPageRequests    # Uses requests library, HTTP mocking available
├── WebPageCurl        # Uses curl command, subprocess mocking available
└── WebPageSelenium    # Uses Selenium WebDriver
    ├── WebPageFirefox
    └── WebPageChrome

WebFile (file downloads)
├── RequestsMixin      # HTTP session management
└── HLSFile           # HLS stream handling with FFmpeg
```

### Core Modules

1. **webpage.py** (692 lines)
   - Web page fetching and parsing
   - XPath/CSS selector support
   - Selenium WebDriver integration

2. **webfile.py** (423 lines)
   - HTTP file downloads
   - Range request support
   - Progress callbacks

3. **hlsfile.py** (249 lines)
   - HLS playlist parsing
   - Video segment merging with FFmpeg

4. **requests.py**
   - HTTP session management mixin
   - Shared request functionality

5. **utils.py**
   - CachedGenerator
   - LazyList utilities

## Test Strategy

### Critical Understanding

**Two-tier test system**: Unit (default) vs Integration (opt-in)

```bash
# Unit tests (default) - Always run these
pytest tests/                    # 114 tests, ~1.2s

# Integration tests - Run before releases
pytest tests/ -m integration     # 104 tests, minutes

# All tests
pytest tests/ -m ""              # 218 tests
```

### Test Configuration

**Location:** `pyproject.toml`
```toml
[tool.pytest.ini_options]
markers = [
    "integration: Integration tests (HTTP, Curl, Browser)",
]
addopts = "-m 'not integration'"  # Exclude integration by default
```

### Mock Infrastructure

**Location:** `tests/conftest.py`

**Automatic mocking** (disabled for `@pytest.mark.integration`):
- HTTP requests via `requests.Session.get`
- FFmpeg via `subprocess.run` and `ffmpy.FFmpeg`
- UserAgent generation
- Curl commands via `subprocess.run`

**Key fixtures:**
- `mock_external_http` - Mocks all HTTP traffic
- `mock_ffmpeg` - Mocks FFmpeg execution
- `mock_useragent` - Mocks user agent generation

### Test Organization

```
tests/
├── conftest.py           # Fixtures, mocks (462 lines)
├── test_webpage.py       # WebPage tests (unit + Selenium integration)
├── test_webfile.py       # WebFile tests (unit + HTTP integration)
├── test_hlsfile.py       # HLSFile tests (unit only)
└── test_utils.py         # Utility tests (unit only)
```

**Unit Tests (114):**
- WebFile: 47 tests
- HLSFile: 27 tests
- Utils: 14 tests
- WebPageRequests: 26 tests

**Integration Tests (104):**
- WebFile HTTP: 11 tests (httpbin.org)
- WebPageCurl: 16 tests (real curl)
- Selenium Firefox: 39 tests (real browser)
- Selenium Chrome: 38 tests (real browser)

## Development Workflow

### Before Making Changes

```bash
# 1. Ensure all unit tests pass
pytest tests/ -v

# 2. Check current test coverage
pytest tests/ --cov=pyscraper --cov-report=term-missing
```

### Making Changes

```bash
# 1. Write tests first (TDD)
# 2. Implement feature
# 3. Run specific tests
pytest tests/test_your_module.py -v

# 4. Run all unit tests
pytest tests/ -v

# 5. For network-dependent features, add integration tests
pytest tests/ -m integration -v
```

### Before Committing

```bash
# Always run unit tests
pytest tests/ -v

# All tests must pass
# Execution time should be ~1-2 seconds for unit tests
```

## Important Design Decisions

### 1. Test Classification (Unit vs Integration)

**Decision:** Separate unit tests (mocked, fast) from integration tests (real services, slow)

**Rationale:**
- Fast feedback during development (~1s)
- CI/CD cost reduction (unit tests only by default)
- Integration tests verify production compatibility

**Implementation:** pytest markers + automatic mock fixtures

### 2. Mock Everything by Default

**Decision:** All external dependencies (HTTP, FFmpeg, curl) are mocked in unit tests

**Rationale:**
- 99% faster execution (minutes → 1.2s)
- Offline development possible
- 100% reproducible tests
- No external service dependencies

**Implementation:** `autouse=True` fixtures in `conftest.py` that check for `integration` marker

### 3. WebPageCurl as Integration Test Only

**Decision:** TestWebPageCurl runs real curl commands, excluded from unit tests

**Rationale:**
- curl is a thin wrapper around `subprocess.run(['curl', url])`
- Mocking subprocess defeats the purpose
- HTML parsing is already tested in WebPageRequests
- Real curl execution validates actual behavior

**Trade-off:** May fail in restricted networks, but this is acceptable for opt-in integration tests

### 4. Consolidated Test Files

**Decision:** Integration tests live in the same files as unit tests, differentiated by markers

**Rationale:**
- Related tests stay together
- Simpler directory structure
- Marker-based filtering is sufficient
- Easier maintenance

**Example:**
```python
# tests/test_webfile.py

def test_download():        # Unit test (no marker)
    ...

@pytest.mark.integration    # Integration test (marked)
def test_real_download():
    ...
```

## Known Issues & Refactoring Candidates

### High Priority

1. **State Validation Duplication** (~50 lines)
   - Problem: `if self.driver is None:` repeated 28+ times
   - Solution: Extract to `_ensure_open()` method

2. **Cache Invalidation in hlsfile.py** (~10 lines)
   - Problem: 5 identical try/except blocks in `clear_cache()`
   - Solution: Loop over property names

### Medium Priority

3. **Selenium Driver Classes** (~40-50 lines duplication)
   - Problem: WebPageFirefox and WebPageChrome are 95% identical
   - Solution: Factory pattern or parameterized driver type

## File Locations

### Source Code
- `pyscraper/webpage.py` - Web page handling
- `pyscraper/webfile.py` - File downloads
- `pyscraper/hlsfile.py` - HLS streaming
- `pyscraper/requests.py` - HTTP mixin
- `pyscraper/utils.py` - Utilities

### Tests
- `tests/conftest.py` - **CRITICAL**: Mock infrastructure
- `tests/test_webpage.py` - WebPage tests
- `tests/test_webfile.py` - WebFile tests (includes integration)
- `tests/test_hlsfile.py` - HLS tests
- `tests/test_utils.py` - Utility tests
- `tests/testdata/` - Test fixtures (HTML, m3u8, video segments)

### Configuration
- `pyproject.toml` - pytest configuration, test markers
- `requirements.txt` - Dependencies

### Documentation
- `README.md` - Project overview
- `docs/testing.md` - Comprehensive testing guide
- `docs/development.md` - Development guide
- `docs/analysis/` - Detailed analysis documents

## Common Tasks

### Running Tests

```bash
# Default: unit tests only
pytest tests/

# With coverage
pytest tests/ --cov=pyscraper --cov-report=html

# Integration tests
pytest tests/ -m integration -v

# Specific test file
pytest tests/test_webfile.py -v

# Specific test
pytest tests/test_webfile.py::TestWebFile::test_download_unlink -v
```

### Adding New Features

1. Write unit test (no marker needed)
2. Implement feature
3. Verify unit tests pass: `pytest tests/ -v`
4. If feature requires network: add `@pytest.mark.integration` test
5. Document in relevant docstrings

### Debugging Test Failures

```bash
# Verbose output with full traces
pytest tests/test_file.py -vv --tb=long

# Stop at first failure
pytest tests/ -x

# Show print statements
pytest tests/ -s

# Run only failed tests
pytest tests/ --lf
```

### Checking Mocks

```bash
# List available fixtures
pytest --fixtures

# Verify integration marker is working
pytest tests/ --collect-only -q          # Should show 114
pytest tests/ -m integration --collect-only -q  # Should show 104
```

## Critical Reminders

1. **Never commit failing unit tests** - They run on every PR
2. **Unit tests must be fast** - Target < 2 seconds total
3. **Integration tests are opt-in** - They should not run by default
4. **Check `conftest.py` before modifying mocks** - Central mock configuration
5. **Use markers for integration tests** - `@pytest.mark.integration`
6. **Don't hardcode test counts in docs** - They change frequently

## Environment Variables

- `INTEGRATION_TEST=1` - Force integration tests (alternative to `-m integration`)
- `SELENIUM_FIREFOX_URL` - Remote Firefox WebDriver URL
- `SELENIUM_CHROME_URL` - Remote Chrome WebDriver URL
- `HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY` - Proxy configuration

## Recent Major Changes

1. **Test Infrastructure Overhaul** (2024)
   - Unified to pytest (from mixed unittest/pytest)
   - Implemented comprehensive HTTP mocking
   - Created two-tier test system (unit/integration)
   - Reduced test time from minutes to ~1 second

2. **Documentation Reorganization** (2024)
   - Created `docs/` directory structure
   - Unified documentation language to English
   - Separated testing, development, and analysis docs

3. **WebPageCurl Migration** (2024)
   - Moved from unit tests (mocked) to integration tests (real curl)
   - Better reflects actual curl behavior verification

## Quick Context for Common Scenarios

### "Tests are failing"
1. Check if unit tests: `pytest tests/` (should be ~1s and pass)
2. If integration tests fail, that's expected in restricted networks
3. Check `conftest.py` for mock configuration

### "Need to add HTTP feature"
1. Write unit test (HTTP will be mocked automatically)
2. Add `@pytest.mark.integration` test for real HTTP validation
3. Both should exist for network-dependent features

### "Test is slow"
1. Check if it has `@pytest.mark.integration` - if not, should be fast
2. Verify mocks are working: check `conftest.py` fixture
3. Unit tests should all complete in ~1-2 seconds total

### "Refactoring code"
1. Run unit tests frequently: `pytest tests/ -v`
2. Use `--lf` to rerun only failed tests
3. Integration tests before final commit

## Contact Points

- **Test Strategy**: See `docs/testing.md`
- **Mock Configuration**: See `tests/conftest.py`
- **Architecture Details**: See `docs/analysis/codebase.md`
- **Module Structure**: See `docs/analysis/modules.md`

---

**Last Updated:** 2024-11
**Maintained By:** Project contributors
