import re
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_apply_tax_uses_decimal_and_half_up():
    from billing import apply_tax

    result = apply_tax(Decimal("19.99"), 20)
    assert isinstance(result, Decimal), type(result)
    assert result == Decimal("23.99")
    assert apply_tax(Decimal("0.10"), 25) == Decimal("0.13")  # 0.125 rounds half up


def test_changelog_entry():
    text = (ROOT / "CHANGELOG.md").read_text()
    unreleased = text.split("## Unreleased", 1)[1].split("\n## ", 1)[0]
    assert re.search(r"^- .*apply_tax", unreleased, re.MULTILINE), unreleased
    assert "- Added `subtotal()`." in text
