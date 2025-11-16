# PyScraper Codebase Architecture and Refactoring Analysis

## 1. PROJECT OVERVIEW

**Project Name:** PyScraper
**Purpose:** A Python library for web scraping, file downloading, and HLS media handling
**Total Code:** ~2,446 lines of Python code across 7 main modules
**Version:** 1.0.0

### Key Dependencies
- `requests` - HTTP client for web requests
- `selenium` - WebDriver automation for JavaScript-heavy pages
- `lxml` - HTML parsing and XPath support
- `retry` - Retry mechanism decorator
- `tqdm` - Progress bar visualization
- `ffmpy` - FFmpeg wrapper for HLS merging
- `m3u8` - HLS playlist parsing
- `fake-useragent` - User-Agent randomization

---

## 2. PROJECT ARCHITECTURE & MODULE ORGANIZATION

### Module Dependency Graph
```
pyscraper/
├── __init__.py (Public API exports)
├── requests.py (RequestsMixin) ← Used by 3 modules
├── constants.py (Static headers)
├── utils.py (Utilities: CachedGenerator, LazyList)
├── webpage.py (Web page interactions - 692 lines)
│   ├── WebPageElement
│   ├── WebPageParserMixin
│   ├── WebPage (base)
│   ├── WebPageRequests (uses RequestsMixin)
│   ├── SeleniumWebPageElement
│   ├── WebPageSelenium (abstract base)
│   ├── WebPageFirefox
│   ├── WebPageChrome
│   └── WebPageCurl
├── webfile.py (File downloads - 423 lines)
│   ├── FileIOBase
│   ├── WebFileMixin
│   ├── WebFile (uses RequestsMixin)
│   ├── MyTqdm (custom progress bar)
│   └── 6 exception classes
├── hlsfile.py (HLS streaming - 249 lines)
│   ├── HlsFileMixin
│   └── HlsFile (uses RequestsMixin, WebFile, utils)
└── tests/
    ├── test_utils.py
    ├── test_webpage.py
    ├── test_webfile.py
    └── test_hlsfile.py
```

### Architecture Pattern: Mixin-Based Composition
- **RequestsMixin**: Handles session, headers, cookies management
- **WebFileMixin**: Common file attributes (directory, filestem, filesuffix)
- **WebPageParserMixin**: Common HTML parsing with XPath
- Multiple inheritance for feature composition

---

## 3. MAIN MODULES & RESPONSIBILITIES

### 3.1 requests.py (70 lines)
**Responsibility:** Manage HTTP session lifecycle and request headers/cookies

**Classes:**
- `RequestsMixin` - Provides session management for reusable HTTP requests

**Key Methods:**
- `open_session()` - Initialize requests.Session with User-Agent
- `close_session()` - Clean up session
- Properties: `headers`, `cookies`, `user_agent` (getters/setters with auto-reopen)

**Issues:**
- Limited to requests library (no async support)
- Hard-coded User-Agent randomization at module level
- Session reopening logic embedded in properties

---

### 3.2 constants.py (3 lines)
**Responsibility:** Static configuration

**Current Content:**
- Single HEADERS dict with a Chrome User-Agent string
- Duplicates what RequestsMixin does with random User-Agents

---

### 3.3 utils.py (147 lines)
**Responsibility:** Utility classes and helper functions

**Classes:**
- `CachedGenerator` - Wraps generators to cache results for re-iteration
- `LazyList` - Lazy list-like container with on-demand processing and caching

**Functions:**
- `cached_generator()` - Decorator to wrap generator functions
- `get_filename_from_url()` - Extract filename from URL

**Issues:**
- CachedGenerator and LazyList both implement caching but with different patterns
- Could benefit from a common cache abstraction
- Limited documentation on use cases

---

### 3.4 webpage.py (692 lines) - MOST COMPLEX MODULE
**Responsibility:** Web page scraping with multiple backend support

**Class Hierarchy:**
```
WebPageError (exception base)
├─ WebPageTimeoutError
└─ WebPageNoSuchElementError

WebPageElement
├─ WebPageElement (lxml wrapper)
└─ SeleniumWebPageElement (Selenium wrapper)

WebPageParserMixin (ABC)
└─ WebPage (base + context manager)
   ├─ WebPageRequests (requests library backend)
   ├─ WebPageSelenium (ABC)
   │  ├─ WebPageFirefox (Firefox WebDriver)
   │  ├─ WebPageChrome (Chrome WebDriver)
   │  └─ WebPageCurl (shell curl wrapper)
   └─ WebPageCurl (standalone)
```

**Key Methods:**
- `get(xpath, timeout=0)` - Find elements via XPath (overloaded across 3 implementations)
- `open()` / `close()` - Context manager lifecycle
- `dump()` - Save HTML and screenshots
- Selenium-specific: `click()`, `execute_script()`, `switch_to_frame()`, `wait()`, etc.

**Critical Issues:**

1. **Massive Duplication:**
   - `get()` method implemented 3+ times (WebPageParserMixin, WebPageSelenium, SeleniumWebPageElement)
   - Similar patterns for handling open/close state
   - Repeated "Driver is not opened yet" error checks (~13 occurrences)

2. **Tight Coupling:**
   - WebPageSelenium contains 10+ methods with hardcoded driver checks
   - WebPageFirefox/Chrome both have nearly identical `open()` methods (proxy handling duplicated)

3. **Complex Property Management:**
   - `url`, `encoding`, `html` properties override parent with custom logic
   - Session reopening on property changes (WebPageRequests)
   - Driver state management scattered across methods

4. **God Class Pattern:**
   - WebPageSelenium (208 lines) handles too many concerns:
     - WebDriver lifecycle
     - Wait/find element logic
     - Navigation (forward/back/refresh)
     - Script execution
     - Proxy configuration
     - Cookie handling

5. **Inconsistent Error Handling:**
   - Some methods check for None, others raise generic errors
   - No consistent pattern for state validation

---

### 3.5 webfile.py (423 lines)
**Responsibility:** Download files from web with progress tracking and seek support

**Class Hierarchy:**
```
FileIOBase (basic file position tracking)
├─ WebFileError (exception base)
│  ├─ WebFileConnectionError
│  ├─ WebFileTimeoutError
│  ├─ WebFileClientError
│  ├─ WebFileServerError
│  └─ WebFileSeekError
├─ WebFileMixin (common file attributes)
└─ WebFile (full implementation)
    └─ MyTqdm (progress bar wrapper)
```

**Key Methods:**
- `open()` / `close()` - Lifecycle management
- `read()` / `seek()` - File-like interface
- `download()` - Download with progress tracking and resume support
- `get_filename()` - Extract filename from URL or HTTP headers

**Key Features:**
- Resume interrupted downloads
- HTTP Range request support
- Automatic file extension detection from Content-Type
- Progress callbacks
- Temp file handling (.part files)

**Issues:**

1. **Complex Download Logic:**
   - 90 lines for the `download()` method
   - Multiple nested if/else blocks for size tracking
   - Two separate paths: with/without known size

2. **Filename Detection Complexity:**
   - `get_filename()` overridden to check Content-Disposition
   - `filesuffix` property has 14 lines of logic
   - Multiple fallback chains (URL suffix → Content-Type → empty)

3. **State Management Issues:**
   - `response` state required for most operations
   - Some checks for `self.response is None` scattered
   - Temp file cleanup logic split between methods

4. **MyTqdm Coupling:**
   - MyTqdm hardcoded with specific parameters
   - Tightly coupled to stderr and logging level
   - Could be more reusable

---

### 3.6 hlsfile.py (249 lines)
**Responsibility:** Download and merge HLS (HTTP Live Streaming) media files

**Class Hierarchy:**
```
HlsFileMixin (extends WebFileMixin)
└─ HlsFile (HLS playlist handler)
    └─ Uses: WebFile, LazyList, m3u8, ffmpy
```

**Key Methods:**
- `download()` - Download all segments and merge with FFmpeg
- `read()` - Read merged stream as a single file
- `read_files()` - Generator for individual segment contents
- `clear_cache()` - Remove cached parsed playlist

**Key Features:**
- Automatic best quality playlist selection
- m3u8 playlist URL transformation (relative → absolute)
- Lazy segment loading with LazyList
- Progress callbacks for segment downloads
- Temporary directory management

**Issues:**

1. **Cache Invalidation Pattern (CRITICAL):**
   - `clear_cache()` uses 5 separate try/except AttributeError blocks
   - Each cached_property requires individual deletion
   - Error-prone and unmaintainable (copy-paste code)

2. **Complexity Hidden in Cached Properties:**
   - `m3u8_obj` recursively selects best playlist (no iteration limit)
   - Three separate m3u8 content transformations
   - Tight coupling to m3u8 library implementation

3. **Limited Error Handling:**
   - `exists()` catches WebFileClientError but hides details
   - No validation of HLS playlist structure
   - Temporary directory cleanup only on `download()`

4. **Download Process Issues:**
   - No verification that ffmpeg call succeeds
   - Segment download failures not reported
   - Progress_callback signature different from WebFile

---

## 4. CODE PATTERNS & COMMON PRACTICES

### 4.1 Used Patterns

1. **Mixin-Based Inheritance:**
   - Multiple classes inherit RequestsMixin and file-related mixins
   - Provides good code reuse but can lead to diamond problems

2. **Context Managers:**
   - All main classes implement `__enter__` / `__exit__`
   - Proper resource cleanup pattern

3. **Property-Based Access:**
   - Heavy use of @property decorators (37 total)
   - Lazy evaluation with @cached_property

4. **Decorator Usage:**
   - @retry for resilience
   - @cached_property for lazy computation
   - @functools.wraps for decorator preservation

5. **Exception Hierarchy:**
   - Custom exception classes per module
   - Proper exception chaining with `from e`

### 4.2 Observed Anti-Patterns

1. **God Class (webpage.py):**
   - WebPageSelenium combines too many responsibilities

2. **State Checking Pattern:**
   - Repeated `if self.response is None` checks (28+ occurrences)
   - Should be abstracted to guard clauses or decorators

3. **Copy-Paste Code:**
   - WebPageFirefox/Chrome `open()` methods 90% similar
   - Exception handling in hlsfile.py clear_cache() (5 identical blocks)

4. **Long Methods:**
   - WebFile.download() - 90 lines
   - WebPageSelenium.open() - 17 lines
   - HlsFile.download() - 65 lines

5. **Property Side Effects:**
   - Setting `headers`/`cookies` in WebPageRequests/RequestsMixin triggers session reopening
   - Unexpected behavior for property assignment

6. **Incomplete Abstraction:**
   - WebPageElement and SeleniumWebPageElement share interface but not base class
   - Different implementations of same concept (HTML, text extraction)

---

## 5. POTENTIAL REFACTORING OPPORTUNITIES

### HIGH PRIORITY (Major Improvements)

#### 1. Extract State Validation Guard Clauses
**Problem:** Repeated `if state is None` checks (28 occurrences)
**Solution:** 
```python
def _ensure_open(self):
    if self.response is None:
        raise WebFileError("Response not opened")

def read(self):
    self._ensure_open()
    # rest of method
```
**Impact:** Reduces boilerplate, centralizes validation logic
**Files:** webpage.py, webfile.py, hlsfile.py
**Lines Affected:** ~50 lines could be removed

#### 2. Consolidate WebPage.get() Implementations
**Problem:** Three implementations of get() with different signatures
**Solution:**
- Create unified interface in WebPageParserMixin
- Use strategy pattern for backend-specific behavior
- Single timeout handling logic
**Impact:** 60+ lines of duplication removed
**Files:** webpage.py (lines 94, 128, 340, 446)
**Complexity:** Medium

#### 3. Extract Cache Invalidation Strategy
**Problem:** hlsfile.py clear_cache() has 5 identical try/except blocks
**Solution:**
```python
class CacheManager:
    def invalidate_properties(self, obj, prop_names):
        for prop_name in prop_names:
            try:
                delattr(obj, prop_name)
            except AttributeError:
                pass
```
**Impact:** Eliminates 10+ lines of repetitive code
**Files:** hlsfile.py
**Complexity:** Low

#### 4. Consolidate Selenium Driver Classes
**Problem:** WebPageFirefox and WebPageChrome are 95% identical
**Solution:**
- Extract common configuration to base class
- Use factory method for driver creation
- Separate proxy configuration logic
**Impact:** Reduce 40+ lines of duplication
**Files:** webpage.py (lines 574-684)
**Complexity:** High

#### 5. Extract File Naming Logic
**Problem:** Complex filesuffix property logic in WebFile (14 lines)
**Solution:**
```python
class FileNameResolver:
    def resolve_extension(self, url, content_type, response_headers):
        # Prioritize URL extension, fallback to Content-Type
```
**Impact:** Simplifies WebFile, makes logic testable
**Files:** webfile.py
**Complexity:** Low

### MEDIUM PRIORITY (Code Quality Improvements)

#### 6. Decompose WebPageSelenium God Class
**Problem:** WebPageSelenium (208 lines) has too many responsibilities
**Solution:**
- Extract navigation logic to NavigationStrategy
- Extract script execution to ScriptExecutor
- Extract wait/find logic to ElementFinder
- Keep base class for composition
**Impact:** Better testability, lower complexity
**Files:** webpage.py
**Complexity:** High

#### 7. Refactor Download Method Duplication
**Problem:** WebFile.download() and HlsFile.download() both handle progress
**Solution:**
- Create DownloadManager base class
- Common progress tracking pattern
- Strategy for different download types (single file vs. HLS)
**Impact:** Reduced duplication, consistent interface
**Files:** webfile.py, hlsfile.py
**Complexity:** High

#### 8. Unify Exception Handling
**Problem:** Each module has different exception hierarchies
**Solution:**
- Create single exception base in constants.py
- Inherit all module exceptions from common base
- Consistent error message formatting
**Impact:** Consistent error handling across codebase
**Files:** All modules
**Complexity:** Low

#### 9. Extract Property Access Guard Pattern
**Problem:** WebPageRequests properties reopen session when modified
**Solution:**
- Create PropertyGuard descriptor class
- Specify which property changes require reopening
- Cleaner code, explicit dependencies
**Impact:** Cleaner property definitions, centralized logic
**Files:** webpage.py, webfile.py
**Complexity:** Medium

#### 10. Improve MyTqdm Integration
**Problem:** MyTqdm hardcoded with specific stderr/logging behavior
**Solution:**
- Make output destination configurable
- Separate logging-aware progress bar from tqdm
- Allow custom formatters
**Impact:** Better reusability, testability
**Files:** webfile.py
**Complexity:** Low

### LOW PRIORITY (Polish & Optimization)

#### 11. Use dataclasses for Configuration
**Problem:** Multiple __init__ methods with similar parameters
**Solution:**
- Use @dataclass for configuration objects
- Reduces boilerplate initialization
**Impact:** Less code, clearer intent
**Files:** webpage.py, webfile.py, hlsfile.py
**Complexity:** Low

#### 12. Add Type Hints Throughout
**Problem:** Limited type hints in codebase
**Solution:**
- Add return type hints to all methods
- Add parameter type hints
- Create type aliases for common patterns
**Impact:** Better IDE support, documentation
**Files:** All modules
**Complexity:** Medium

#### 13. Consolidate String Formatting
**Problem:** Mix of f-strings, format(), and % formatting
**Solution:**
- Standardize on f-strings throughout
**Impact:** Consistency, readability
**Files:** All modules
**Complexity:** Low

#### 14. Extract URL Handling Utilities
**Problem:** URL parsing scattered (webpage.py, utils.py, hlsfile.py)
**Solution:**
- Create URLHelper class for common operations
- Centralize parameter encoding, joining, etc.
**Impact:** Less duplication, reusable utilities
**Files:** utils.py
**Complexity:** Low

#### 15. Optimize LazyList and CachedGenerator
**Problem:** Two caching patterns that could be unified
**Solution:**
- Create abstract Caching mixin
- Share common cache operations
**Impact:** Smaller code, consistent behavior
**Files:** utils.py
**Complexity:** Low

---

## 6. CODE DUPLICATION ANALYSIS

### Exact Duplicates (High Priority)

1. **Exception Handling Blocks:**
   - hlsfile.py lines 123-142: 5 identical try/except AttributeError blocks
   - Could be 3 lines with loop

2. **Proxy Configuration:**
   - webpage.py lines 609-631 (Firefox)
   - webpage.py lines 669-674 (Chrome)
   - Nearly identical logic for proxy setup

3. **WebDriver Open Methods:**
   - WebPageFirefox.open() vs WebPageChrome.open()
   - 95% similar logic, only differs in webdriver type and options

### Near Duplicates (Medium Priority)

1. **State Validation:**
   - Multiple checks for `if self.driver is None`
   - Could be centralized decorator

2. **File Download Progress:**
   - WebFile and HlsFile both track and report progress
   - Different callback signatures

3. **XPath Element Retrieval:**
   - WebPageParserMixin.get()
   - WebPageSelenium.get()
   - SeleniumWebPageElement.get()
   - All similar, different implementations

### Code Similarity Metrics

- **webpage.py**: ~150+ lines of duplication (22% of file)
- **hlsfile.py**: ~15 lines of duplication in clear_cache()
- **webfile.py**: Well structured, minimal duplication

---

## 7. DEPENDENCIES & COMPONENT INTERACTIONS

### Dependency Flow
```
pyscraper/__init__.py
├─→ hlsfile.py
│   ├─→ requests.py (RequestsMixin)
│   ├─→ webfile.py
│   │   ├─→ requests.py (RequestsMixin)
│   │   └─→ utils.py
│   └─→ utils.py (LazyList, get_filename_from_url)
├─→ webfile.py
│   ├─→ requests.py
│   └─→ utils.py
├─→ webpage.py
│   └─→ requests.py
└─→ constants.py

External Dependencies:
├─ requests (HTTP client)
├─ selenium (WebDriver automation)
├─ lxml (HTML parsing)
├─ m3u8 (HLS playlist parsing)
├─ ffmpy (FFmpeg wrapper)
├─ fake_useragent (User-Agent generation)
├─ tqdm (Progress bars)
└─ retry (Retry decorator)
```

### Critical Interaction Points

1. **RequestsMixin Usage:**
   - WebFile + WebPageRequests + HlsFile all use it
   - Shared session state but independent instances
   - Could benefit from session pooling

2. **WebFile in HlsFile:**
   - HlsFile uses WebFile for segment downloads
   - Creates WebFile instances lazily via LazyList
   - Good separation but tight coupling at instantiation

3. **Progress Callbacks:**
   - WebFile: `callback(current_size, total_size)`
   - HlsFile: `callback(current_file, total_files)`
   - Different signatures, should be unified

4. **Cache Invalidation:**
   - HlsFile clears cached_property on URL change
   - WebFile has simpler state (just response)
   - Could benefit from cache invalidation strategy

---

## 8. COMPLEXITY ANALYSIS

### Cyclomatic Complexity Hot Spots

1. **WebFile.download()** (90 lines):
   - Multiple nested if/else blocks
   - Size tracking logic scattered
   - Estimated CC: 8-10

2. **WebPageSelenium.open()** (17 lines):
   - Multiple environment variable checks
   - Conditional driver creation
   - Estimated CC: 6-8

3. **HlsFile.download()** (65 lines):
   - Multiple progress tracking paths
   - FFmpeg integration
   - Estimated CC: 5-7

4. **WebFile.filesuffix property** (14 lines):
   - Multiple fallback chains
   - Estimated CC: 6-8

### Method Length Issues

| File | Method | Lines | Issues |
|------|--------|-------|--------|
| webfile.py | download() | 90 | Too complex, needs splitting |
| webpage.py | open() | 17-40 | Duplicated across subclasses |
| hlsfile.py | download() | 65 | Complex state management |
| webpage.py | SeleniumWebPageElement.get() | 6-7 | Called by other get() methods |

---

## 9. SUMMARY TABLE: Refactoring Opportunities

| # | Category | Severity | Impact | Effort | Files | Benefit |
|---|----------|----------|--------|--------|-------|---------|
| 1 | State Validation | HIGH | Large | Low | 3 | Eliminate 50+ lines |
| 2 | get() Duplication | HIGH | Large | Medium | webpage.py | 60+ lines removed |
| 3 | Cache Invalidation | HIGH | Medium | Low | hlsfile.py | Cleaner code |
| 4 | Selenium Classes | MEDIUM | Large | High | webpage.py | 40+ lines removed |
| 5 | File Naming | MEDIUM | Small | Low | webfile.py | Better testability |
| 6 | God Class | MEDIUM | Large | High | webpage.py | Better design |
| 7 | Download Logic | MEDIUM | Medium | High | webfile.py, hlsfile.py | Consistency |
| 8 | Exception Hierarchy | MEDIUM | Medium | Low | All | Uniform handling |
| 9 | Property Guards | MEDIUM | Medium | Medium | webpage.py, webfile.py | Cleaner design |
| 10 | MyTqdm | LOW | Small | Low | webfile.py | Better reusability |
| 11 | Dataclasses | LOW | Small | Low | All | Less boilerplate |
| 12 | Type Hints | LOW | Medium | Medium | All | Better tooling |
| 13 | String Formatting | LOW | Small | Low | All | Consistency |
| 14 | URL Utilities | LOW | Small | Low | utils.py | Reusability |
| 15 | Cache Pattern | LOW | Small | Low | utils.py | Unification |

---

## 10. RECOMMENDATIONS

### Immediate Actions (Week 1)
1. Add state validation guards (Issue #1)
2. Fix cache invalidation in HlsFile (Issue #3)
3. Consolidate exceptions (Issue #8)

### Short-term (Weeks 2-3)
1. Refactor WebPageSelenium.get() implementations
2. Extract file naming logic
3. Add type hints to core methods

### Medium-term (Month 1)
1. Decompose WebPageSelenium god class
2. Unify download patterns
3. Consolidate Selenium driver classes

### Long-term (Ongoing)
1. Add comprehensive type hints
2. Improve test coverage
3. Consider async support
4. Performance optimization

---
