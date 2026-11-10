from durations import parse_duration


def test_hours_and_minutes():
    assert parse_duration("1h30m") == 5400


def test_plain_seconds():
    assert parse_duration("90") == 90
