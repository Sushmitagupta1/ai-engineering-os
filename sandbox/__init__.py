"""sandbox — M4 isolated test execution (docker-first, local fallback)."""

__version__ = "0.1.0"

from sandbox.runner import backend, copy_repo, run_pytest  # noqa: F401