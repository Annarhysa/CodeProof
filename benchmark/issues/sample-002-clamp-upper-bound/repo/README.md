# mathutils

A tiny utility module.

## Known issue

`clamp(value, low, high)` returns the wrong value when `value` is above
`high` — it returns `low` instead of `high`. Run `pytest` to see the
failing test.
