from functools import wraps
import logging

logger = logging.getLogger(__name__)

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:56.0) Gecko/20100101 Firefox/56.0'}

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
