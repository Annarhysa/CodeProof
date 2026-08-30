def average(numbers):
    """Return the arithmetic mean of a list of numbers."""
    if not numbers:
        raise ValueError("average() requires a non-empty list")
    total = sum(numbers)
    # BUG: integer division truncates the result instead of computing
    # a true float average (e.g. average([1, 2]) returns 1 instead of 1.5).
    return total // len(numbers)
