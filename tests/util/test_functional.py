import pytest

from supa.util.functional import expand_ranges, to_ranges


def test_expand_ranges() -> None:  # noqa: D103
    assert expand_ranges([[1], [2], [10, 12]]) == [1, 2, 10, 11]
    assert expand_ranges([[1], [2], [10, 12]], inclusive=True) == [1, 2, 10, 11, 12]
    assert expand_ranges([[1], [2], [10, 12]], inclusive=True) == [1, 2, 10, 11, 12]
    assert expand_ranges([]) == []

    # sorted
    assert expand_ranges([[100], [1, 4]], inclusive=True) == [1, 2, 3, 4, 100]

    # deduplicated
    assert expand_ranges([[1, 5], [3, 5]], inclusive=True) == [1, 2, 3, 4, 5]

    with pytest.raises(ValueError):
        expand_ranges([[]])

    with pytest.raises(ValueError):
        expand_ranges([[2, 100, 3]])


def test_to_ranges() -> None:  # noqa: D103
    assert list(to_ranges([1, 2, 3])) == [range(1, 4)]
    assert list(to_ranges([])) == []
    assert list(to_ranges([0])) == [range(0, 1)]
    assert list(to_ranges([1, 2, 3, 7, 8, 9, 100, 200, 201, 202])) == [
        range(1, 4),
        range(7, 10),
        range(100, 101),
        range(200, 203),
    ]
