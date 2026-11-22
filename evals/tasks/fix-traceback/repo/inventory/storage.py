"""Load stock from CSV files with name, quantity and price columns."""

import csv

from inventory.models import Item


def load(path):
    with open(path, newline="") as f:
        return [_item(row) for row in csv.DictReader(f)]


def _item(row):
    return Item(row["name"], int(row["quantity"]), float(row["price"]))
