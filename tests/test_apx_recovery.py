"""Include the APX recovery suite in the standard product test collection."""
from pathlib import Path
from runpy import run_path
from unittest import TestCase


_suite = Path(__file__).resolve().parents[1] / 'app/uncrash-recovery/tests/test_server.py'
_namespace = run_path(str(_suite))
for _name, _value in _namespace.items():
    if isinstance(_value, type) and issubclass(_value, TestCase) and _value is not TestCase:
        globals()[_name] = _value
del _name, _value
