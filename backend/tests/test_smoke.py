import sys

import cardplatform


def test_package_imports():
    assert cardplatform.__version__ == "0.1.0"


def test_running_on_python_312():
    assert sys.version_info[:2] == (3, 12)
