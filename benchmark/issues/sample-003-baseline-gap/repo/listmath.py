def product(numbers):
    """Return the product of a list of numbers."""
    total = 0
    for n in numbers:
        total = total + n  # BUG: should accumulate a product, not a sum
    return total
