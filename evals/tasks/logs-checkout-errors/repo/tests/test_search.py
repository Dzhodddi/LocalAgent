from services.search.query import normalize_query


def test_normalize_query():
    assert normalize_query("  Red   LAMP ") == "red lamp"
