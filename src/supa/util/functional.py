#  Copyright 2020 SURF.
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
"""Assorted helper functions for representing the same data in different ways."""
import itertools
from typing import Iterable, List, Sequence, Set

import structlog

logger = structlog.get_logger(__name__)


def expand_ranges(ranges: Sequence[Sequence[int]], inclusive: bool = False) -> List[int]:
    """Expand sequence of range definitions into sorted and deduplicated list of individual values.

    A range definition is either a:

    * one element sequence -> an individual value.
    * two element sequence -> a range of values (either inclusive or exclusive).

    >>> expand_ranges([[1], [2], [10, 12]])
    [1, 2, 10, 11]
    >>> expand_ranges([[1], [2], [10, 12]], inclusive=True)
    [1, 2, 10, 11, 12]
    >>> expand_ranges([[]])
    Traceback (most recent call last):
        ...
    ValueError: Expected 1 or 2 element list for range definition. Got f0 element list instead.

    Resulting list is sorted::

        >>> expand_ranges([[100], [1, 4]], inclusive=True)
        [1, 2, 3, 4, 100]

    Args:
        ranges: sequence of range definitions
        inclusive: are the stop values of the range definition inclusive or exclusive.

    Returns:
        Sorted deduplicated list of individual values.

    Raises:
        ValueError: if range definition is not a one or two element sequence.

    """
    values: Set[int] = set()
    for r in ranges:
        if (r_len := len(r)) == 2:
            values.update(range(r[0], r[1] + (1 if inclusive else 0)))
        elif r_len == 1:
            values.add(r[0])
        else:
            raise ValueError(f"Expected 1 or 2 element list for range definition. Got f{len(r)} element list instead.")
    return sorted(values)


def to_ranges(i: Iterable[int]) -> Iterable[range]:
    """Convert a sorted iterable of ints to an iterable of range objects.

    .. note:: The iterable passed in should be sorted and not contain duplicate elements.

    Examples::
        >>> list(to_ranges([2, 3, 4, 5, 7, 8, 9, 45, 46, 47, 49, 51, 53, 54, 55, 56, 57, 58, 59, 60, 61]))
        [range(2, 6), range(7, 10), range(45, 48), range(49, 50), range(51, 52), range(53, 62)]

    Args:
        i: sorted iterable

    Yields:
        range object for each consecutive set of integers

    """
    # The trick here is the key function (the lambda one)
    # that calculates the difference between an element of the iterable `i` and its corresponding enumeration value.
    # For consecutive values in the iterable,
    # this difference will be the same!
    # All these values (those with the same difference) are grouped by the `groupby` function.
    # We return the first and last element to construct a `range` object
    for _, g in itertools.groupby(enumerate(i), lambda t: t[1] - t[0]):
        group = list(g)
        yield range(group[0][1], group[-1][1] + 1)
