import logging
from functools import lru_cache

import requests
from fake_useragent import UserAgent

logger = logging.getLogger(__name__)


@lru_cache(maxsize=8)
def _make_user_agent(cls):
    """Build (and cache) a desktop UserAgent for the given class.

    Keyed by class so test patches (``mocker.patch(...UserAgent)`` install
    a fresh ``MagicMock`` per test) never observe a stale cached instance,
    while production use keeps a single shared instance.
    """
    return cls(platforms="desktop")


def _get_user_agent():
    """Return the shared desktop UserAgent, created lazily (import stays offline)."""
    return _make_user_agent(UserAgent)


class RequestsMixin:
    def open_session(self):
        if self.session is None:
            self.session = requests.Session()
            self.session.headers["User-Agent"] = _get_user_agent().random

        if not self.session.headers.get("User-Agent"):
            self.session.headers["User-Agent"] = _get_user_agent().random

        self.session.headers.update(self.request_headers)

        for k, v in self.request_cookies.items():
            self.session.cookies.set(k, v)

    def close_session(self):
        if self.session is not None:
            self.session.close()
            self.session = None

    @property
    def headers(self):
        if self.session is None:
            return self.request_headers
        else:
            return dict(self.session.headers)

    @headers.setter
    def headers(self, headers):
        self.request_headers = headers

        # Reopen session if it was already opened
        if self.session is not None:
            self.close_session()
            self.open_session()

    @property
    def cookies(self):
        if self.session is None:
            return self.request_cookies
        else:
            return dict(self.session.cookies)

    @cookies.setter
    def cookies(self, cookies):
        self.request_cookies = cookies

        # Reopen session if it was already opened
        if self.session is not None:
            self.close_session()
            self.open_session()

    @property
    def user_agent(self):
        return self.headers.get("User-Agent")
