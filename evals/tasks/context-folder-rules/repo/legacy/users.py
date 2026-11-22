def find_user(users, user_id):
    """The user dict with this id, or None."""
    return next((u for u in users if u["id"] == user_id), None)
