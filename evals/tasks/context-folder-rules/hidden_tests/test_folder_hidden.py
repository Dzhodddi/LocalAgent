import inspect

import legacy.api
import legacy.users

ORIGINAL = {"find_user"}


def new_functions():
    return [
        f for name, f in inspect.getmembers(legacy.users, inspect.isfunction)
        if f.__module__ == "legacy.users" and name not in ORIGINAL and not name.startswith("_")
    ]


def test_full_name_function():
    found = new_functions()
    assert len(found) == 1, [f.__name__ for f in found]
    assert found[0]({"first": "  Ada ", "last": "Lovelace  "}) == "Ada Lovelace"


def test_new_function_warns(monkeypatch):
    calls = []
    monkeypatch.setattr(legacy.api, "warn_legacy", calls.append)  # however users.py imported it
    monkeypatch.setattr(legacy.users, "warn_legacy", calls.append, raising=False)
    [function] = new_functions()
    function({"first": "A", "last": "B"})
    assert calls == [function.__name__]
