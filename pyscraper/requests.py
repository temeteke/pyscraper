from abc import ABC, abstractmethod
from fake_useragent import UserAgent
import logging
import requests


logger = logging.getLogger(__name__)

user_agent = UserAgent(platforms="desktop")


class RequestsMixin(ABC):
    @property
    def session(self):
        if not getattr(self, "_session", None):
            self._session = requests.Session()
            self._session.headers["User-Agent"] = user_agent.random
        return self._session

    @session.setter
    def session(self, session):
        if session:
            self._session = session
            if not session.headers.get("User-Agent"):
                self._session.headers["User-Agent"] = user_agent.random
        self.clear_cache()

    @property
    def headers(self):
        return dict(self.session.headers)

    @headers.setter
    def headers(self, headers):
        self.session.headers.update(headers)
        self.clear_cache()

    @property
    def cookies(self):
        return dict(self.session.cookies)

    @cookies.setter
    def cookies(self, cookies):
        for k, v in cookies.items():
            self.session.cookies.set(k, v)
        self.clear_cache()

    @property
    def timeout(self):
        if not getattr(self, "_timeout", None):
            self._timeout = 10
        return self._timeout

    @timeout.setter
    def timeout(self, value):
        self._timeout = value

    @property
    def user_agent(self):
        return self.session.headers["User-Agent"]

    @abstractmethod
    def clear_cache(self):
        pass
