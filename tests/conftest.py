"""Shared test configuration."""

from hypothesis import settings

# Property-based tests must be repeatable like every other test: the same examples on
# every run and every machine. A failing example is printed, so it can become a
# regular test.
settings.register_profile("tyche", derandomize=True, database=None, deadline=None, max_examples=200)
settings.load_profile("tyche")
