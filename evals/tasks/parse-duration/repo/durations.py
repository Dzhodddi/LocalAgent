def parse_duration(text: str) -> int:
    """Parse a duration like "1h30m", "45s", "2h", "1h 5m 10s" or "90" into seconds.

    - Units are h (hours), m (minutes) and s (seconds), each used at most once, in that order.
    - Parts may be separated by spaces. Surrounding whitespace is ignored.
    - A plain number without a unit means seconds.
    - Raise ValueError for anything else: an empty string, an unknown unit ("3d"),
      a unit without a number ("h"), negative numbers, or units out of order ("5m1h").
    """
    raise NotImplementedError
