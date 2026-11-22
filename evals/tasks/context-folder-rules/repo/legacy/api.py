import warnings


def warn_legacy(name):
    warnings.warn(f"legacy.{name} is deprecated", DeprecationWarning, stacklevel=3)
