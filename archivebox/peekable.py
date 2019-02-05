from sys import maxsize
from itertools import islice
from collections import deque

_marker = object()

class Peekable(object):
    """Peekable version of a normal python generator.
       Useful when you don't want to evaluate the entire iterable to look at
       a specific item at a given idx.
    """
    def __init__(self, iterable):
        self._it = iter(iterable)
        self._cache = deque()

    def __iter__(self):
        return self

    def __bool__(self):
        try:
            self.peek()
        except StopIteration:
            return False
        return True

    def __nonzero__(self):
        # For Python 2 compatibility
        return self.__bool__()

    def peek(self, default=_marker):
        """Return the item that will be next returned from ``next()``.
        Return ``default`` if there are no items left. If ``default`` is not
        provided, raise ``StopIteration``.
        """
        if not self._cache:
            try:
                self._cache.append(next(self._it))
            except StopIteration:
                if default is _marker:
                    raise
                return default
        return self._cache[0]

    def prepend(self, *items):
        """Stack up items to be the next ones returned from ``next()`` or
        ``self.peek()``. The items will be returned in
        first in, first out order::
            >>> p = peekable([1, 2, 3])
            >>> p.prepend(10, 11, 12)
            >>> next(p)
            10
            >>> list(p)
            [11, 12, 1, 2, 3]
        It is possible, by prepending items, to "resurrect" a peekable that
        previously raised ``StopIteration``.
            >>> p = peekable([])
            >>> next(p)
            Traceback (most recent call last):
              ...
            StopIteration
            >>> p.prepend(1)
            >>> next(p)
            1
            >>> next(p)
            Traceback (most recent call last):
              ...
            StopIteration
        """
        self._cache.extendleft(reversed(items))

    def __next__(self):
        if self._cache:
            return self._cache.popleft()

        return next(self._it)

    next = __next__  # For Python 2 compatibility

    def _get_slice(self, index):
        # Normalize the slice's arguments
        step = 1 if (index.step is None) else index.step
        if step > 0:
            start = 0 if (index.start is None) else index.start
            stop = maxsize if (index.stop is None) else index.stop
        elif step < 0:
            start = -1 if (index.start is None) else index.start
            stop = (-maxsize - 1) if (index.stop is None) else index.stop
        else:
            raise ValueError('slice step cannot be zero')

        # If either the start or stop index is negative, we'll need to cache
        # the rest of the iterable in order to slice from the right side.
        if (start < 0) or (stop < 0):
            self._cache.extend(self._it)
        # Otherwise we'll need to find the rightmost index and cache to that
        # point.
        else:
            n = min(max(start, stop) + 1, maxsize)
            cache_len = len(self._cache)
            if n >= cache_len:
                self._cache.extend(islice(self._it, n - cache_len))

        return list(self._cache)[index]

    def __getitem__(self, index):
        if isinstance(index, slice):
            return self._get_slice(index)

        cache_len = len(self._cache)
        if index < 0:
            self._cache.extend(self._it)
        elif index >= cache_len:
            self._cache.extend(islice(self._it, index + 1 - cache_len))

        return self._cache[index]
