import pytest
from pyscraper.utils import CachedGenerator, cached_generator, LazyList


class TestCachedGenerator:
    @pytest.fixture
    def cached_gen(self):
        def simple_gen():
            for i in range(5):
                yield i

        generator = simple_gen()
        return CachedGenerator(generator)

    def test_iteration(self, cached_gen):
        result = list(cached_gen)
        assert result == [0, 1, 2, 3, 4]

    def test_len(self, cached_gen):
        list(cached_gen)
        assert len(cached_gen) == 5

    def test_getitem(self, cached_gen):
        assert cached_gen[2] == 2
        assert cached_gen[4] == 4
        with pytest.raises(IndexError):
            _ = cached_gen[5]

    def test_contains(self, cached_gen):
        assert 3 in cached_gen
        assert 5 not in cached_gen

    def test_cached_generator_decorator(self):
        @cached_generator
        def simple_gen():
            for i in range(5):
                yield i

        decorated_gen = simple_gen()
        assert list(decorated_gen) == [0, 1, 2, 3, 4]
        assert len(decorated_gen) == 5


class TestLazyList:
    @pytest.fixture
    def lazy_list(self):
        def item_generator(item):
            return item * 2

        items = [1, 2, 3, 4, 5]
        return LazyList(items, item_generator)

    def test_len(self, lazy_list):
        """Test that len() returns correct length"""
        assert len(lazy_list) == 5

    def test_getitem(self, lazy_list):
        """Test that __getitem__ applies generator function"""
        assert lazy_list[0] == 2  # 1 * 2
        assert lazy_list[2] == 6  # 3 * 2
        assert lazy_list[4] == 10  # 5 * 2

    def test_getitem_negative_index(self, lazy_list):
        """Test negative indexing"""
        assert lazy_list[-1] == 10  # 5 * 2
        assert lazy_list[-2] == 8  # 4 * 2

    def test_getitem_out_of_range(self, lazy_list):
        """Test IndexError for out of range access"""
        with pytest.raises(IndexError):
            _ = lazy_list[10]

    def test_contains(self, lazy_list):
        """Test that __contains__ works with generated values"""
        assert 2 in lazy_list  # 1 * 2
        assert 6 in lazy_list  # 3 * 2
        assert 3 not in lazy_list  # 3 is not in generated values
        assert 100 not in lazy_list

    def test_iteration(self, lazy_list):
        """Test that iteration applies generator function"""
        result = list(lazy_list)
        assert result == [2, 4, 6, 8, 10]

    def test_caching(self, lazy_list):
        """Test that values are cached after first access"""
        # Access item
        first_access = lazy_list[2]

        # Item should be in cache
        assert 2 in lazy_list._cache
        assert lazy_list._cache[2] == 6

        # Second access should return cached value
        second_access = lazy_list[2]
        assert first_access == second_access

    def test_lazy_evaluation(self):
        """Test that items are only evaluated when accessed"""
        # Create new LazyList without accessing items
        call_count = {'count': 0}

        def counting_generator(item):
            call_count['count'] += 1
            return item * 2

        lazy = LazyList([1, 2, 3], counting_generator)

        # No items should be generated yet
        assert call_count['count'] == 0

        # Access first item
        _ = lazy[0]
        assert call_count['count'] == 1

        # Access same item again (should use cache)
        _ = lazy[0]
        assert call_count['count'] == 1

        # Access second item
        _ = lazy[1]
        assert call_count['count'] == 2

    def test_empty_list(self):
        """Test LazyList with empty list"""
        lazy = LazyList([], lambda x: x * 2)
        assert len(lazy) == 0
        assert list(lazy) == []

    def test_contains_caches_all_traversed_elements(self):
        gen = CachedGenerator(iter([1, 2, 3, 4, 5]))
        assert 3 in gen
        assert len(gen.cache) == 3
        assert 5 in gen
        assert len(gen.cache) == 5
