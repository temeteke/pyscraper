import functools
from urllib.parse import urlparse


class CachedGenerator:
    """
    A generator wrapper that caches generated items for efficient re-access.

    Attributes:
        generator (generator): The generator to be wrapped and cached.
        cache (list): A list to store the generated items.
        index (int): The index of the next element to be returned by __next__.

    Methods:
        __iter__(): Resets the index and returns the iterator object.
        __next__(): Returns the next item from the generator, caching it if not already cached.
        __len__(): Returns the number of cached items.
        __getitem__(index): Returns the item at the specified index, generating and caching items as needed.
        __contains__(item): Checks if an item is in the cache or the generator, caching items as they are checked.
    """

    def __init__(self, generator):
        self.generator = generator
        self.cache = []  # Cache of generated items
        self.index = 0  # Index of the next element to be returned by __next__

    def __iter__(self):
        self.index = 0
        return self

    def __next__(self):
        self.index += 1
        try:
            return self.cache[self.index - 1]
        except IndexError:
            item = next(self.generator)
            self.cache.append(item)
            return item

    def __len__(self):
        return len(self.cache)

    def __getitem__(self, index):
        while len(self.cache) <= index:
            try:
                self.cache.append(next(self.generator))
            except StopIteration:
                raise IndexError("Index out of range")
        return self.cache[index]

    def __contains__(self, item):
        if item in self.cache:
            return True
        for element in self.generator:
            if element == item:
                self.cache.append(element)
                return True
            self.cache.append(element)
        return False


def cached_generator(func):
    """
    A decorator that caches the results of a generator function.

    Args:
        func (function): The generator function to be decorated.

    Returns:
        function: A wrapper function that returns a CachedGenerator instance.
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        """
        A wrapper function that creates an instance of CachedGenerator.

        Args:
            *args: Positional arguments to be passed to the generator function.
            **kwargs: Keyword arguments to be passed to the generator function.

        Returns:
            CachedGenerator: An instance of the CachedGenerator class.
        """
        return CachedGenerator(func(*args, **kwargs))

    return wrapper


class LazyList:
    """
    A list-like container that processes its elements lazily.

    Attributes:
        data (list): The list of raw data elements.
        process_func (callable): A function to process each element of the data.
        _cache (dict): A dictionary to cache the results of processed elements.

    Methods:
        __getitem__(index):
            Returns the processed element at the specified index. Supports slicing.
        __len__():
            Returns the length of the data.
        __iter__():
            Returns an iterator that yields processed elements.
    """

    def __init__(self, data, process_func):
        self.data = data
        self.process_func = process_func
        self._cache = {}  # Cache to store the results of processed elements

    def __getitem__(self, index):
        if isinstance(index, slice):
            # In the case of a slice, access each element with a list comprehension
            return [self[i] for i in range(*index.indices(len(self)))]
        # Convert negative index to positive by adding the length of the data
        if index < 0:
            index += len(self.data)
        # If already processed, return from cache
        if index in self._cache:
            return self._cache[index]
        # Execute processing on first access
        result = self.process_func(self.data[index])
        self._cache[index] = result
        return result

    def __len__(self):
        return len(self.data)

    def __iter__(self):
        for i in range(len(self)):
            yield self[i]


def get_filename_from_url(url):
    """
    Extracts the filename from a URL.

    Args:
        url (str): The URL from which to extract the filename.

    Returns:
        str: The extracted filename.
    """
    return urlparse(url).path.split("/")[-1]
