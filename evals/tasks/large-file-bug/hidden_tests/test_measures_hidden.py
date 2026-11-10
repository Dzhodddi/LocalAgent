import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
ORIGINAL_OTHER = "0620eb6428ff0a118fe2276b6232767546f6d43e0107d9ededfe554b25209f35"


def test_triangle_area():
    from measures import triangle_area

    assert triangle_area(10, 5) == 25


def test_rest_of_file_untouched():
    text = (ROOT / "measures.py").read_text()
    rest = re.sub(r"def triangle_area.*?(?=\n\n\ndef )", "", text, flags=re.S)
    assert hashlib.sha256(rest.encode()).hexdigest() == ORIGINAL_OTHER
