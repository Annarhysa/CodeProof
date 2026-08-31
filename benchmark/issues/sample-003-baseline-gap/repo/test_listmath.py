from listmath import product


def test_product_of_three():
    assert product([2, 3, 4]) == 24


def test_product_with_one():
    assert product([1, 5]) == 5


def test_product_empty_is_one():
    assert product([]) == 1
