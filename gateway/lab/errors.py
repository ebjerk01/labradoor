"""The gateway's HTTP error (here so route mixins such as login_api.py can raise it without importing server.py)."""


class HTTPError(Exception):
    def __init__(self, code, msg, **extra):
        super().__init__(msg)
        self.code, self.msg, self.extra = code, msg, extra
