"""Stub tests for src.persistence."""

import src.persistence


def test_load_cache_exists():
    assert callable(src.persistence.load_cache)


def test_merge_run_exists():
    assert callable(src.persistence.merge_run)
