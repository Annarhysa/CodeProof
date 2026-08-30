"""Standalone reproduction script for the reported issue:
average([1, 2]) should return 1.5 but returns 1 due to integer division."""
from calc import average

result = average([1, 2])
print(f"average([1, 2]) = {result}")
assert result == 1.5, f"BUG REPRODUCED: expected 1.5, got {result}"
print("OK")
