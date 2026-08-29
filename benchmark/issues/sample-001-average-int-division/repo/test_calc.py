from calc import average


def test_average_integers():
    assert average([1, 2, 3]) == 2


def test_average_returns_float_mean():
    assert average([1, 2]) == 1.5


def test_average_empty_raises():
    try:
        average([])
        assert False, "expected ValueError"
    except ValueError:
        pass
