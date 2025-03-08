import logging
from functools import wraps


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/75.0.3764.0 Safari/537.36"
}


def debug(logger=None):
    if not logger:
        logger = logging.getLogger("pyscraper")

    def dectator(f):
        @wraps(f)
        def wrapper(*args, **kwds):
            if args[1:]:
                logger.debug(
                    "{}('{}')".format(
                        ".".join([args[0].__class__.__name__, f.__name__]), ",".join(args[1:])
                    )
                )
            else:
                logger.debug("{}".format(f.__name__))
            result = f(*args, **kwds)
            if args[1:]:
                logger.debug(
                    "{}('{}') -> {}".format(
                        ".".join([args[0].__class__.__name__, f.__name__]),
                        ",".join(args[1:]),
                        result,
                    )
                )
            else:
                logger.debug("{} -> {}".format(f.__name__, result))
            return result

        return wrapper

    return dectator
