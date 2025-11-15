# PyScraper Module Structure Overview

## Visual Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        pyscraper/__init__.py                            │
│                    (Public API - Exports Main Classes)                  │
└──────────┬──────────────┬──────────────┬─────────────────┬──────────────┘
           │              │              │                 │
           ▼              ▼              ▼                 ▼
      webpage.py     webfile.py      hlsfile.py      constants.py
      (692 lines)    (423 lines)     (249 lines)      (3 lines)
           │              │              │
           │              │              │
           ▼              ▼              ▼
      ┌────────────────────────────────────────┐
      │        requests.py (RequestsMixin)      │
      │        (Session & Header Management)   │
      └────────────────────────────────────────┘
                         │
                         ▼
                     utils.py
               (CachedGenerator, LazyList)
```

## Module Dependencies

```
Dependency Chain:
=================

pyscraper/
├── __init__.py
│   └─→ Imports: (WebPageRequests, WebPageFirefox, WebPageChrome, WebPageCurl,
│                  WebFile, HlsFile, HEADERS, Exceptions)
│
├── webpage.py (LARGEST MODULE - 692 lines)
│   ├─→ Imports: lxml, selenium, retry, requests.py
│   ├─→ Exports: WebPageError, WebPageTimeoutError, WebPageNoSuchElementError,
│   │             WebPageElement, SeleniumWebPageElement, WebPage,
│   │             WebPageRequests, WebPageSelenium, WebPageFirefox,
│   │             WebPageChrome, WebPageCurl
│   └─→ Used by: Tests
│
├── webfile.py (423 lines)
│   ├─→ Imports: requests, lxml, tqdm, requests.py, utils.py
│   ├─→ Exports: FileIOBase, WebFileMixin, WebFileMixin, MyTqdm,
│   │             WebFile, WebFileError & variants
│   └─→ Used by: hlsfile.py, Tests
│
├── hlsfile.py (249 lines)
│   ├─→ Imports: m3u8, ffmpy, requests.py, webfile.py, utils.py
│   ├─→ Exports: HlsFileMixin, HlsFile, HlsFileError
│   └─→ Used by: Tests
│
├── requests.py (70 lines) ★ CROSS-MODULE MIXIN
│   ├─→ Imports: requests, fake_useragent
│   ├─→ Exports: RequestsMixin
│   └─→ Used by: WebPageRequests, WebFile, HlsFile
│
├── utils.py (147 lines)
│   ├─→ Imports: functools, urllib.parse
│   ├─→ Exports: CachedGenerator, LazyList, cached_generator(), get_filename_from_url()
│   └─→ Used by: HlsFile, WebFile
│
└── constants.py (3 lines)
    ├─→ Imports: None
    ├─→ Exports: HEADERS dict
    └─→ Used by: __init__.py
```

## Class Hierarchy

### WebPage Classes (webpage.py)
```
                           WebPageError
                                │
                    ┌───────────┼───────────┐
                    │           │           │
          WebPageTimeoutError    │  WebPageNoSuchElementError
                                │
                      WebPageParserMixin (ABC)
                                │
                            WebPage (Base)
                    ┌───────────┴───────────┐
                    │                       │
            WebPageRequests         WebPageSelenium (ABC)
         (requests library)         ┌──────────┬──────────┐
                                   │          │          │
                            WebPageFirefox WebPageChrome WebPageCurl

Element Wrappers:
                        WebPageElement
                              │
                        ┌──────┴──────┐
                        │             │
                   (HTML parsing)  SeleniumWebPageElement
                                      (WebDriver integration)
```

### File Classes (webfile.py)
```
                      FileIOBase (Position tracking)
                              │
              ┌───────────────┴───────────────┐
              │                               │
        WebFileError                    WebFileMixin
        (Base exception)         (Common file attributes)
        │   │   │   │   │                 │
        │   │   │   │   │             WebFile
        │   │   │   │   │        (Full file handling)
        │   │   │   │   │               │
        └─►Connection, Timeout,    MyTqdm (Progress)
           Client, Server, Seek
           errors
```

### HLS Classes (hlsfile.py)
```
                    HlsFileMixin
                    (extends WebFileMixin)
                            │
                        HlsFile
                    (HLS streaming)
                       │   │
                       │   └─→ WebFile (Segment downloads)
                       └─→ LazyList (Segment management)
```

## External Dependencies Graph

```
pyscraper
│
├─→ requests (HTTP client)
│   Used by: RequestsMixin, WebFile, HlsFile (via WebFile)
│
├─→ selenium (WebDriver)
│   Used by: WebPageFirefox, WebPageChrome
│
├─→ lxml (HTML parsing)
│   Used by: WebPageElement, WebPageParserMixin
│
├─→ fake_useragent (User-Agent)
│   Used by: RequestsMixin, HlsFile
│
├─→ tqdm (Progress bars)
│   Used by: MyTqdm (custom wrapper in WebFile)
│
├─→ m3u8 (HLS playlist parsing)
│   Used by: HlsFile.m3u8_obj
│
├─→ ffmpy (FFmpeg wrapper)
│   Used by: HlsFile.download()
│
└─→ retry (Retry decorator)
    Used by: WebPageParserMixin.get_with_retry()
```

## Code Statistics

### Lines of Code per Module
```
webpage.py      692 lines  (28%)  ← Most Complex
webfile.py      423 lines  (17%)
hlsfile.py      249 lines  (10%)
requests.py      70 lines  (3%)
utils.py        147 lines  (6%)
constants.py      3 lines  (<1%)
__init__.py      42 lines  (2%)
────────────────────────────
tests/          858 lines  (35%)
────────────────────────────
Total          2,446 lines

### Module Complexity Ranking (by lines & duplication)
1. webpage.py    - HIGH    (692L, 150L duplication, 22%)
2. webfile.py    - MEDIUM  (423L, minimal duplication)
3. hlsfile.py    - MEDIUM  (249L, 15L duplication)
4. requests.py   - LOW     (70L, reusable mixin)
5. utils.py      - LOW     (147L, utility functions)
```

## Data Flow Patterns

### Reading Web Content (WebPageRequests)
```
User Code
   │
   ▼
WebPageRequests.__enter__()
   │
   ├─→ open()
   │  ├─→ open_session()   [RequestsMixin]
   │  └─→ open_response()
   │     ├─→ session.get(url)
   │     └─→ raise_for_status()
   │
   ├─→ User calls get(xpath)
   │  └─→ WebPageParserMixin.get()
   │     ├─→ lxml_html.xpath()
   │     └─→ [WebPageElement, WebPageElement, ...]
   │
   └─→ WebPageRequests.__exit__()
      └─→ close()
         ├─→ close_response()
         └─→ close_session()  [RequestsMixin]
```

### Downloading Files (WebFile)
```
User Code
   │
   ▼
WebFile(url).__enter__()
   │
   ├─→ open()
   │  ├─→ open_session()   [RequestsMixin]
   │  └─→ open_response()
   │     └─→ session.get(url, stream=True)
   │
   ├─→ download(directory, filename)
   │  ├─→ Determine filename/extension
   │  ├─→ Check for resumed download
   │  ├─→ Create temp file (.part)
   │  ├─→ read() in chunks (8KB)
   │  ├─→ Update progress via MyTqdm
   │  ├─→ Call progress_callback()
   │  ├─→ Verify downloaded size
   │  └─→ Rename temp → final file
   │
   └─→ WebFile.__exit__()
      └─→ close()
         ├─→ close_response()
         └─→ close_session()
```

### Downloading HLS Streams (HlsFile)
```
User Code
   │
   ▼
HlsFile(m3u8_url).__init__()
   │
   ├─→ download()
   │  ├─→ Parse m3u8 playlist
   │  │  ├─→ m3u8_obj property [cached]
   │  │  │  ├─→ WebFile(m3u8_url).read()
   │  │  │  ├─→ m3u8.loads()
   │  │  │  └─→ Recursively select best quality
   │  │  │
   │  │  ├─→ Create web_files [LazyList]
   │  │  │  └─→ Lazy-load WebFile per segment
   │  │  │
   │  │  ├─→ Download all segments
   │  │  │  └─→ For each segment: WebFile.download()
   │  │  │
   │  │  ├─→ Create m3u8 manifest (local paths)
   │  │  │
   │  │  ├─→ Call FFmpeg to merge segments
   │  │  │  └─→ ffmpy.FFmpeg(...).run()
   │  │  │
   │  │  └─→ Clean up temp directory
   │  │
   │  └─→ Return final MP4 file path
   │
   └─→ HlsFile.unlink()
      └─→ Delete downloaded file & temp dir
```

## Key Design Patterns Used

### 1. Mixin Pattern (RequestsMixin)
- Shared HTTP session management
- Reused by WebPageRequests, WebFile, HlsFile
- Provides: open_session(), close_session(), headers, cookies, user_agent

### 2. Context Manager Pattern
- All main classes implement `__enter__` / `__exit__`
- Ensures proper resource cleanup
- Example: `with WebFile(url) as wf: wf.read()`

### 3. Template Method Pattern
- WebPageParserMixin defines abstract html property
- Subclasses implement with different backends
- Mixin provides get(), xpath(), get_html() etc.

### 4. Lazy Evaluation Pattern
- @cached_property for expensive computations
- LazyList for segment enumeration in HlsFile
- CachedGenerator for re-iterable generators

### 5. Strategy Pattern (Implicit)
- Different get() implementations for requests/selenium/element
- Different drivers for Firefox/Chrome
- Different download strategies for WebFile/HlsFile

## Common Code Patterns & Issues

### Pattern 1: State Checking (ANTI-PATTERN)
```python
def method(self):
    if self.response is None:
        raise WebFileError("Response not opened")
    # ... actual logic
```
Occurs 28+ times. Should use guard clause:
```python
def method(self):
    self._ensure_open()
    # ... actual logic
```

### Pattern 2: Property with Side Effects (ANTI-PATTERN)
```python
@property
def url(self):
    return self.request_url

@url.setter
def url(self, value):
    self.request_url = value
    if self.response is not None:
        self.open_response()  # ← Unexpected side effect!
```

### Pattern 3: Cache Invalidation (ANTI-PATTERN - hlsfile.py)
```python
def clear_cache(self):
    try:
        del self.m3u8_obj
    except AttributeError:
        pass
    # ... repeated 4 more times
```
Should use loop or CacheManager class.

## Recommended Module Improvements

### Short-term (Easy wins)
1. Extract state validation to `_ensure_open()` methods
2. Fix HlsFile cache invalidation (loop pattern)
3. Consolidate exception hierarchies

### Medium-term (Design improvements)
1. Consolidate get() implementations
2. Extract file naming logic
3. Add property guard pattern

### Long-term (Major refactoring)
1. Decompose WebPageSelenium god class
2. Consolidate Selenium drivers
3. Add comprehensive type hints
4. Consider async support
