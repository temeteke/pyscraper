from fake_useragent import UserAgent
import logging
import requests


logger = logging.getLogger(__name__)

user_agent = UserAgent(platforms="desktop")


class RequestsMixin:
    def open_session(self):
        if not self.session:
            self.session = requests.Session()
            self.session.headers["User-Agent"] = user_agent.random

        if not self.session.headers.get("User-Agent"):
            self.session.headers["User-Agent"] = user_agent.random

        self.session.headers.update(self.request_headers)

        for k, v in self.request_cookies.items():
            self.session.cookies.set(k, v)

    def close_session(self):
        if self.session:
            self.session.close()
            self.session = None

    @property
    def headers(self):
        if self.session:
            return dict(self.session.headers)
        else:
            return self.request_headers

    @headers.setter
    def headers(self, headers):
        self.request_headers = headers

        # Reopen session if it was already opened
        if self.session:
            self.open_session()

    @property
    def cookies(self):
        if self.session:
            return dict(self.session.cookies)
        else:
            return self.request_cookies

    @cookies.setter
    def cookies(self, cookies):
        self.request_cookies = cookies

        # Reopen session if it was already opened
        if self.session:
            self.open_session()

    @property
    def user_agent(self):
        return self.headers.get("User-Agent")
