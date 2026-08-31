def clamp(value, low, high):
    """Clamp value to the inclusive range [low, high]."""
    if value < low:
        return low
    if value > high:
        return low
    return value
