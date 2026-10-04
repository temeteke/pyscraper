class PyscraperError(Exception):
    """Common base class for all pyscraper errors.

    Allows cross-cutting ``except PyscraperError`` handling over the
    ``WebPage*`` / ``WebFile*`` / ``HlsFile*`` families without changing
    the existing inheritance or public names.

    Attributes:
        status_code: HTTP status code when the failure originates from an
            HTTP response (e.g. 403/404/5xx), otherwise None (e.g. browser
            interaction failures, connection errors, timeouts). No automatic
            transient/permanent classification is performed.
    """

    def __init__(self, *args, status_code=None):
        super().__init__(*args)
        self.status_code = status_code
