from agents.mock import _parse_pytest_summary


def test_parse_pytest_summary_all_passed():
    output = "===== 3 passed in 0.02s ====="
    assert _parse_pytest_summary(output) == (3, 0, 3)


def test_parse_pytest_summary_mixed():
    output = "===== 2 failed, 5 passed in 0.10s ====="
    assert _parse_pytest_summary(output) == (5, 2, 7)


def test_parse_pytest_summary_no_match():
    assert _parse_pytest_summary("no summary line here") == (0, 0, 0)
