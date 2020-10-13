import pytest

from supa.util.vlan import VlanRanges


def test_vlanranges_instantiation() -> None:  # noqa: D103
    assert VlanRanges() == VlanRanges([])
    assert VlanRanges(None) == VlanRanges([])
    assert VlanRanges("") == VlanRanges([])
    assert VlanRanges(4) == VlanRanges("4")
    assert VlanRanges("0") == VlanRanges([(0, 0)]) == VlanRanges([[0]])
    assert VlanRanges("2,4,8") == VlanRanges([(2, 2), (4, 4), (8, 8)]) == VlanRanges([[2], [4], [8]])
    assert VlanRanges("80-120") == VlanRanges([(80, 120)]) == VlanRanges([[80, 120]])
    assert VlanRanges("10,12-16") == VlanRanges([(10, 10), (12, 16)]) == VlanRanges([[10], [12, 16]])

    # String interpretation is quite flexible,
    # allowing extra whitespace
    assert VlanRanges("  4   , 6-   10") == VlanRanges("4,6-10")

    # Overlapping ranges will be normalized
    assert VlanRanges("4,6-9,7-10") == VlanRanges("4,6-10")
    assert VlanRanges([[4], [6, 9], [7, 10]]) == VlanRanges([[4], [6, 10]])

    # Not all non-ranges are an error perse
    assert VlanRanges("10-1") == VlanRanges("")


def test_vlanranges_str_repr() -> None:  # noqa: D103
    vr = VlanRanges("10-14,4,200-256")

    # `str` version of VlanRanges should be suitable value for constructor,
    # resulting in equivalent object
    assert vr == VlanRanges(str(vr))

    # `repr` version of VlanRanges should be valid Python code r
    # esulting in an equivalent object
    vr_from_repr = eval(repr(vr), globals(), locals())  # noqa: S307 Use of possibly insecure function
    assert vr_from_repr == vr


def test_vlanranges_in() -> None:  # noqa: D103
    vr = VlanRanges("10-20")
    assert 10 in vr
    assert 20 in vr
    assert 9 not in vr
    assert 21 not in vr
    assert 0 not in vr


def test_vlanranges_substract() -> None:  # noqa: D103
    vr = VlanRanges("10-20")
    assert vr - VlanRanges("8-9") == VlanRanges("10-20")
    assert vr - VlanRanges("9-10") == VlanRanges("11-20")
    assert vr - VlanRanges("21-23") == VlanRanges("10-20")
    assert vr - VlanRanges("20-23") == VlanRanges("10-19")
    assert vr - VlanRanges("10-20") == VlanRanges("")
    assert vr - VlanRanges("11-19") == VlanRanges("10,20")

    assert vr - VlanRanges("0-3,10,20,21-28") == VlanRanges("11-19")
    assert vr - VlanRanges("0-3,20") == VlanRanges("10-19")
    assert vr - VlanRanges("0-3,9,21,22-30") == VlanRanges("10-20")


def test_vlanranges_intersection_operator() -> None:  # noqa: D103
    vr = VlanRanges("10-20")
    assert vr & VlanRanges("8-9") == VlanRanges("")
    assert vr & VlanRanges("9-10") == VlanRanges("10")
    assert vr & VlanRanges("21-23") == VlanRanges("")
    assert vr & VlanRanges("20-23") == VlanRanges("20")
    assert vr & VlanRanges("10-20") == VlanRanges("10-20")
    assert vr & VlanRanges("11-19") == VlanRanges("11-19")

    assert vr & VlanRanges("0-3,10,20,21-28") == VlanRanges("10,20")
    assert vr & VlanRanges("0-3,20") == VlanRanges("20")
    assert vr & VlanRanges("0-3,9,21,22-30") == VlanRanges("")


def test_vlanranges_union_operator() -> None:  # noqa: D103
    vr = VlanRanges("10-20")
    assert vr | VlanRanges("8-9") == VlanRanges("8-20")
    assert vr | VlanRanges("9-10") == VlanRanges("9-20")
    assert vr | VlanRanges("21-23") == VlanRanges("10-23")
    assert vr | VlanRanges("20-23") == VlanRanges("10-23")
    assert vr | VlanRanges("10-20") == VlanRanges("10-20")
    assert vr | VlanRanges("11-19") == VlanRanges("10-20")

    assert vr | VlanRanges("0-3,10,20,21-28") == VlanRanges("0-3,10-28")
    assert vr | VlanRanges("0-3,20") == VlanRanges("0-3,10-20")
    assert vr | VlanRanges("0-3,9,21,22-30") == VlanRanges("0-3,9-30")


def test_vlanranges_union() -> None:  # noqa: D103
    vr = VlanRanges("10-20")
    # with iterable
    assert vr == VlanRanges().union(VlanRanges("10-15"), {16, 17, 18}, {19}, VlanRanges(20))

    # single arg
    assert vr == VlanRanges("10-19").union(VlanRanges(20))


def test_vlanranges_symmetric_difference_operator() -> None:  # noqa: D103
    vr = VlanRanges("10-20")
    assert vr ^ VlanRanges("8-9") == VlanRanges("8-20")
    assert vr ^ VlanRanges("9-10") == VlanRanges("9,11-20")
    assert vr ^ VlanRanges("21-23") == VlanRanges("10-23")
    assert vr ^ VlanRanges("20-23") == VlanRanges("10-19,21-23")
    assert vr ^ VlanRanges("10-20") == VlanRanges("")
    assert vr ^ VlanRanges("11-19") == VlanRanges("10,20")

    assert vr ^ VlanRanges("0-3,10,20,21-28") == VlanRanges("0-3,11-19,21-28")
    assert vr ^ VlanRanges("0-3,20") == VlanRanges("0-3,10-19")
    assert vr ^ VlanRanges("0-3,9,21,22-30") == VlanRanges("0-3,9-30")


def test_vlanranges_subset_operator() -> None:  # noqa: D103
    vr = VlanRanges("10-20")
    assert not VlanRanges("8-9") < vr
    assert not VlanRanges("9-10") < vr
    assert not VlanRanges("21-23") < vr
    assert not VlanRanges("20-23") < vr
    assert not VlanRanges("10-20") < vr
    assert VlanRanges("11-19") < vr

    assert not VlanRanges("0-3,10,20,21-28") < vr
    assert not VlanRanges("0-3,20") < vr
    assert not VlanRanges("0-3,9,21,22-30") < vr


def test_vlanranges_hash() -> None:  # noqa: D103
    vr = VlanRanges("10-14,4,200-256")
    # Just making sure it doesn't raise an exception.
    # Which, BTW will be raised,
    # should the internal representation be changed to a mutable data structure.
    assert hash(vr)


def test_vlanranges_repr() -> None:  # noqa: D103
    vr = VlanRanges("3,4-10")
    vr2 = VlanRanges(str(vr))
    assert vr == vr2


def test_vlanranges_non_sensical_values() -> None:  # noqa: D103
    # Negative values, however, are an error
    with pytest.raises(ValueError):
        VlanRanges("-10")

    with pytest.raises(ValueError):
        VlanRanges("fubar")
