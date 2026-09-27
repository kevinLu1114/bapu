"""Bapu: make AI-assisted changes prove themselves before anyone has to trust them.

Three command-line tools, each usable offline with no dependencies:

* ``bapu-gate``     checks OpenSpec delta specs clause by clause before code is written;
* ``bapu-seedred``  proves each test by planting the defect it guards and requiring it to fail;
* ``bapu-findings`` checks that review findings quote their evidence verbatim.

``bapu-gate`` and ``bapu-findings`` have an optional online mode that asks TypeSafe's System One
model (Jev) for bounded judgments. It is used only when requested and only when the
``TYPESAFE_API_KEY`` environment variable is set.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
