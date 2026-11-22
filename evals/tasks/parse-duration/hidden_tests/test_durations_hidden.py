import pytest

from durations import parse_duration


@pytest.mark.parametrize(
    "text, seconds",
    [("45s", 45), ("2h", 7200), ("1h 5m 10s", 3910), ("  10m ", 600), ("0s", 0), ("1h1s", 3601)],
)
def test_valid(text, seconds):
    assert parse_duration(text) == seconds


@pytest.mark.parametrize("text", ["", "   ", "3d", "h", "-5m", "5m1h", "1h1h", "1.5h", "m30"])
def test_invalid(text):
    with pytest.raises(ValueError):
        parse_duration(text)
