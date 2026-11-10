Running the stock report crashes:

```
$ python -c "from inventory.report import summary; from inventory.storage import load; print(summary(load('stock.csv')))"
Traceback (most recent call last):
  File "<string>", line 1, in <module>
  File "inventory/storage.py", line 9, in load
    return [_item(row) for row in csv.DictReader(f)]
  File "inventory/storage.py", line 13, in _item
    return Item(row["name"], int(row["quantity"]), float(row["price"]))
ValueError: could not convert string to float: '$1,200.00'
```

Prices in the CSV files can look like `3.5`, `$2.50` or `$1,200.00`. Fix the cause so
such files load, and add a test for it.
