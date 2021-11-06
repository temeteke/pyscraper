from functools import wraps
import logging
import requests

logger = logging.getLogger(__name__)

HEADERS = {'User-Agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/75.0.3764.0 Safari/537.36"}

def debug(f):
    @wraps(f)
    def wrapper(*args, **kwds):
        if args[1:]:
            logger.debug("{}('{}')".format('.'.join([args[0].__class__.__name__, f.__name__]), ','.join(args[1:])))
        else:
            logger.debug("{}".format(f.__name__))
        result = f(*args, **kwds)
        if args[1:]:
            logger.debug("{}('{}') -> {}".format('.'.join([args[0].__class__.__name__, f.__name__]), ','.join(args[1:]), result))
        else:
            logger.debug("{} -> {}".format(f.__name__, result))
        return result
    return wrapper


class RequestsMixin():
    def init_session(self, session, headers, cookies):
        if session:
            self.session = session
        else:
            self.session = requests.Session()

        self.session.headers.update(HEADERS)
        self.session.headers.update(headers)

        for k, v in cookies.items():
            self.session.cookies.set(k, v)
