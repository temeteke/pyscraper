import unittest
from pyscraper.utils import CachedGenerator, cached_generator, LazyList


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


class TestLazyList(unittest.TestCase):
    def setUp(self):
        def item_generator(item):
            return item * 2

        self.items = [1, 2, 3, 4, 5]
        self.lazy_list = LazyList(self.items, item_generator)

    def test_len(self):
        """Test that len() returns correct length"""
        self.assertEqual(len(self.lazy_list), 5)

    def test_getitem(self):
        """Test that __getitem__ applies generator function"""
        self.assertEqual(self.lazy_list[0], 2)  # 1 * 2
        self.assertEqual(self.lazy_list[2], 6)  # 3 * 2
        self.assertEqual(self.lazy_list[4], 10)  # 5 * 2

    def test_getitem_negative_index(self):
        """Test negative indexing"""
        self.assertEqual(self.lazy_list[-1], 10)  # 5 * 2
        self.assertEqual(self.lazy_list[-2], 8)  # 4 * 2

    def test_getitem_out_of_range(self):
        """Test IndexError for out of range access"""
        with self.assertRaises(IndexError):
            _ = self.lazy_list[10]

    def test_contains(self):
        """Test that __contains__ works with generated values"""
        self.assertIn(2, self.lazy_list)  # 1 * 2
        self.assertIn(6, self.lazy_list)  # 3 * 2
        self.assertNotIn(3, self.lazy_list)  # 3 is not in generated values
        self.assertNotIn(100, self.lazy_list)

    def test_iteration(self):
        """Test that iteration applies generator function"""
        result = list(self.lazy_list)
        self.assertEqual(result, [2, 4, 6, 8, 10])

    def test_caching(self):
        """Test that values are cached after first access"""
        # Access item
        first_access = self.lazy_list[2]

        # Item should be in cache
        self.assertIn(2, self.lazy_list._cache)
        self.assertEqual(self.lazy_list._cache[2], 6)

        # Second access should return cached value
        second_access = self.lazy_list[2]
        self.assertEqual(first_access, second_access)

    def test_lazy_evaluation(self):
        """Test that items are only evaluated when accessed"""
        # Create new LazyList without accessing items
        call_count = {'count': 0}

        def counting_generator(item):
            call_count['count'] += 1
            return item * 2

        lazy = LazyList([1, 2, 3], counting_generator)

        # No items should be generated yet
        self.assertEqual(call_count['count'], 0)

        # Access first item
        _ = lazy[0]
        self.assertEqual(call_count['count'], 1)

        # Access same item again (should use cache)
        _ = lazy[0]
        self.assertEqual(call_count['count'], 1)

        # Access second item
        _ = lazy[1]
        self.assertEqual(call_count['count'], 2)

    def test_empty_list(self):
        """Test LazyList with empty list"""
        lazy = LazyList([], lambda x: x * 2)
        self.assertEqual(len(lazy), 0)
        self.assertEqual(list(lazy), [])


if __name__ == "__main__":
    unittest.main()
