import unittest
from pyscraper.utils import CachedGenerator, cached_generator


class TestCachedGenerator(unittest.TestCase):
    def setUp(self):
        def simple_gen():
            for i in range(5):
                yield i

        self.generator = simple_gen()
        self.cached_gen = CachedGenerator(self.generator)

    def test_iteration(self):
        result = list(self.cached_gen)
        self.assertEqual(result, [0, 1, 2, 3, 4])

    def test_len(self):
        list(self.cached_gen)
        self.assertEqual(len(self.cached_gen), 5)

    def test_getitem(self):
        self.assertEqual(self.cached_gen[2], 2)
        self.assertEqual(self.cached_gen[4], 4)
        with self.assertRaises(IndexError):
            _ = self.cached_gen[5]

    def test_contains(self):
        self.assertIn(3, self.cached_gen)
        self.assertNotIn(5, self.cached_gen)

    def test_cached_generator_decorator(self):
        @cached_generator
        def simple_gen():
            for i in range(5):
                yield i

        decorated_gen = simple_gen()
        self.assertEqual(list(decorated_gen), [0, 1, 2, 3, 4])
        self.assertEqual(len(decorated_gen), 5)


if __name__ == "__main__":
    unittest.main()
