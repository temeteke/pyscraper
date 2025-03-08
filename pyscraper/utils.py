import functools


class CachedGenerator:
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
