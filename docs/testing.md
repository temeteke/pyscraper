# Testing Guide

This guide explains how to run tests in the pyscraper project.

## Overview

Pyscraper maintains two distinct types of tests: **Unit Tests** and **Integration Tests**.

| Test Type | External Dependencies | Speed | Default Execution | Use Case |
|-----------|----------------------|-------|-------------------|----------|
| **Unit Tests** | None (mocked) | Fast (~1s) | ✅ Yes | Daily development, CI/CD |
| **Integration Tests** | Yes (real services) | Slow (minutes) | ❌ No | Pre-release verification |

```
Total Tests: 218

Unit Tests (default): 114 (52%)
├── WebFile: 47
├── HLSFile: 27
├── Utils: 14
└── WebPage (Requests): 26

Integration Tests (opt-in): 104 (48%)
├── WebFile (HTTP): 11
├── WebPageCurl: 16
├── Selenium Firefox: 39
└── Selenium Chrome: 38
```

---

## Quick Start

```bash
# Unit tests only (default, recommended)
pytest tests/

# Integration tests only
pytest tests/ -m integration -v

# All tests
pytest tests/ -m "" -v
```

---

## Unit Tests

### Characteristics

- ✅ **No external dependencies**: All external services are mocked
- ✅ **Fast execution**: Completes in ~1.2 seconds
- ✅ **Offline capable**: No internet connection required
- ✅ **100% reproducible**: Environment-independent
- ✅ **CI/CD friendly**: Can run on every commit

### Execution

```bash
# Default execution (unit tests only)
pytest tests/

# Explicit specification
pytest tests/ -m "not integration"

# Verbose output
pytest tests/ -v

# Coverage measurement
pytest tests/ --cov=pyscraper --cov-report=html
```

### Test Coverage (114 tests)

#### WebFile - 47 tests ✅
- HTTP downloads (mocked)
- Range requests (mocked)
- Error handling
- Progress callbacks
- File I/O operations

#### HLSFile - 27 tests ✅
- HLS stream parsing (mocked)
- Video segment downloads (mocked)
- FFmpeg integration (mocked)
- Cache management

#### Utils - 14 tests ✅
- CachedGenerator
- LazyList

#### WebPage (Requests) - 26 tests ✅
- HTML parsing
- XPath processing
- Encoding
- HTTP communication (mocked)

### Results

```
114/114 passed (100%)
Execution time: 1.22s
```

---

## Integration Tests

### Characteristics

- ⚠️ **Environment dependent**: Uses actual HTTP, Curl, Selenium
- ⚠️ **Slow execution**: Takes seconds to minutes
- ⚠️ **Network required**: Internet connection necessary
- ⚠️ **Environment specific**: Requires browsers, curl installation
- ⚠️ **Selective execution**: Excluded by default

### Execution

```bash
# Integration tests only
pytest tests/ -m integration -v

# Control via environment variable
INTEGRATION_TEST=1 pytest tests/ -v

# All tests (unit + integration)
pytest tests/ -m "" -v
```

### Test Coverage (104 tests)

#### WebFile HTTP Integration Tests - 11 tests
- Real HTTP requests (httpbin.org)
- Range requests
- Redirect handling
- Timeout handling
- Content-Type detection

**Location:** `tests/test_webfile.py::TestWebFileIntegration`

#### WebPageCurl Integration Tests - 16 tests
- Actual curl command execution
- HTML download and parsing
- XPath processing

**Location:** `tests/test_webpage.py::TestWebPageCurl`

**Note:** Real curl commands are executed. Tests may fail in restricted environments due to access limitations.

#### Selenium Integration Tests - 77 tests
- **Firefox automation tests (39 tests)**
- **Chrome automation tests (38 tests)**
- Selenium WebDriver operations
- JavaScript execution
- DOM manipulation

**Location:** `tests/test_webpage.py::TestWebPageFirefox`, `TestWebPageChrome`

### Requirements

```bash
# Network connectivity
ping httpbin.org
ping temeteke.github.io

# Curl command
curl --version

# Browser drivers (for Selenium)
# Firefox: geckodriver
# Chrome: chromedriver
```

---

## Execution Strategy

### Local Development

```bash
# Normal development (unit tests only)
pytest tests/

# Specific module only
pytest tests/test_webfile.py -v

# Coverage measurement
pytest tests/ --cov=pyscraper --cov-report=html
```

### Before Commit

```bash
# Ensure all unit tests pass
pytest tests/ -v

# Commit if successful
git add -A
git commit -m "..."
```

### Pull Request (CI/CD)

```yaml
# GitHub Actions example
- name: Run unit tests
  run: pytest tests/ -v --cov=pyscraper
```

**Executed tests:**
- ✅ Unit tests (114 tests)
- ❌ Integration tests (excluded)

### After Main Branch Merge

```yaml
# GitHub Actions example
- name: Run integration tests
  run: pytest tests/ -m integration -v
  if: github.ref == 'refs/heads/main'
```

**Executed tests:**
- ✅ Integration tests (104 tests)

### Before Release

```bash
# Run all tests
pytest tests/ -m "" -v

# Or
pytest tests/ --override-ini="addopts=" -v
```

**Executed tests:**
- ✅ Unit tests (114 tests)
- ✅ Integration tests (104 tests)

---

## Practical Usage

### Running Specific Tests

```bash
# By file
pytest tests/test_webfile.py

# By class
pytest tests/test_webfile.py::TestWebFile

# By method
pytest tests/test_webfile.py::TestWebFile::test_download_unlink

# Pattern matching
pytest tests/ -k download              # Tests containing "download"
pytest tests/ -k "not slow"            # Tests not containing "slow"
```

### Debug Options

```bash
# Verbose output
pytest tests/ -v                       # verbose
pytest tests/ -vv                      # more verbose

# Debugging on failure
pytest tests/ -x                       # Stop at first failure
pytest tests/ -s                       # Show stdout
pytest tests/ --lf                     # Run last failed tests only
pytest tests/ --pdb                    # Start debugger on failure

# Stack trace control
pytest tests/ --tb=short               # Short trace
pytest tests/ --tb=no                  # No trace
```

### Coverage Measurement

```bash
# Measure coverage
pytest tests/ --cov=pyscraper

# Generate HTML report
pytest tests/ --cov=pyscraper --cov-report=html
open htmlcov/index.html

# Show missing lines
pytest tests/ --cov=pyscraper --cov-report=term-missing
```

### Parallel Execution

```bash
# Parallel execution (requires pytest-xdist)
pip install pytest-xdist

# 4 processes
pytest tests/ -n 4

# Auto-detect CPU cores
pytest tests/ -n auto
```

---

## Writing New Tests

### Unit Tests (Recommended)

```python
# tests/test_your_module.py

def test_download_file():
    """Test file download functionality"""
    # No marker needed (defaults to unit test)
    # External HTTP dependencies are automatically mocked

    wf = WebFile("https://example.com/file.txt")
    with wf as f:
        content = f.read()
        assert len(content) > 0
```

### Integration Tests

```python
# tests/test_your_module.py

@pytest.mark.integration
def test_download_real_file():
    """Test file download with actual HTTP communication"""
    # Actual network access occurs

    wf = WebFile("https://httpbin.org/bytes/1024")
    with wf as f:
        content = f.read()
        assert len(content) == 1024
```

---

## FAQ

### Q: Why separate unit and integration tests?

**A:** To balance development speed and quality.

- **Unit tests**: Fast feedback (~1s) enables TDD
- **Integration tests**: Verify real-world compatibility

Having both enables fast development cycles and safe releases.

### Q: Shouldn't curl and Selenium tests be separate categories?

**A:** No, both are "environment-dependent tests" in the same category.

- Both require external dependencies
- Both should not run by default
- Same execution timing (pre-release, scheduled runs)

The only difference is the type of dependency (HTTP vs Curl vs Browser), but they're essentially the same.

### Q: Should all tests run every time?

**A:** No, use different strategies for different situations.

| Situation | Tests to Run | Reason |
|-----------|-------------|--------|
| During development | Unit tests only | Fast feedback |
| Before commit | Unit tests only | CI/CD cost reduction |
| Before release | All tests | Production compatibility check |

---

## Troubleshooting

### Tests Not Found

```bash
# Check collected tests
pytest tests/ --collect-only

# Verbose display
pytest tests/ --collect-only -v

# Check markers
pytest --markers
```

### Slow Tests

```bash
# Identify slowest tests
pytest tests/ --durations=10

# Parallel execution
pytest tests/ -n auto
```

### Mocks Not Working

```bash
# Check fixtures
pytest tests/ --fixtures | grep mock

# Check markers
pytest --markers

# Check environment variables
echo $INTEGRATION_TEST
```

### Integration Tests Failing

```bash
# Check network connectivity
curl https://httpbin.org/get

# Check curl command
curl --version

# Extend timeout
pytest tests/ -m integration -v --timeout=300
```

---

## Useful Aliases

Add to `.bashrc` or `.zshrc`:

```bash
# Unit tests
alias ptu='pytest tests/'
alias ptuv='pytest tests/ -v'

# Integration tests
alias pti='pytest tests/ -m integration -v'

# All tests
alias pta='pytest tests/ -m "" -v'

# Unit tests with coverage
alias ptc='pytest tests/ --cov=pyscraper --cov-report=html'

# Last failed tests only
alias ptlf='pytest tests/ --lf -v'
```

Usage:
```bash
ptu        # Run unit tests
pti        # Run integration tests
pta        # Run all tests
ptc        # Measure coverage
```

---

## Summary

**Benefits of two-tier test classification:**

- ✅ **Faster development**: Unit tests provide fast feedback (~1s)
- ✅ **Quality assurance**: Integration tests verify production compatibility
- ✅ **CI/CD cost reduction**: Default is unit tests only
- ✅ **Clear strategy**:明確 when to run what
- ✅ **Industry standard**: Standard test classification approach

This strategy enables both fast development cycles and high-quality releases.

---

## References

- [pytest official documentation](https://docs.pytest.org/)
- [pytest-cov plugin](https://pytest-cov.readthedocs.io/)
- [pytest-xdist plugin](https://pytest-xdist.readthedocs.io/)
