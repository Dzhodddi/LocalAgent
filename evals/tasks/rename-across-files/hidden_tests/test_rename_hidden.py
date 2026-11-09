import subprocess
from pathlib import Path

from shop import pricing

ROOT = Path(__file__).parent.parent


def test_new_name_works():
    assert pricing.compute_total([1, 2], 0.5) == 4.5


def test_old_name_gone():
    assert not hasattr(pricing, "calc_total")
    leftovers = subprocess.run(["grep", "-rn", "calc_total", "shop"], check=False, cwd=ROOT, capture_output=True, text=True)
    assert leftovers.stdout == ""
