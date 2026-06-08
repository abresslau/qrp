"""Tests for referential-integrity invariants (Story V2). DB-free pure logic."""

from __future__ import annotations

from sym.validate.integrity import find_orphans


def test_no_orphans():
    assert find_orphans({"A", "B"}, {"A", "B", "C"}) == set()


def test_orphans_detected():
    assert find_orphans({"A", "X"}, {"A", "B"}) == {"X"}


def test_ignores_empty_and_null_keys():
    assert find_orphans({"", "A"}, {"A"}) == set()


def test_empty_child_is_clean():
    assert find_orphans(set(), {"A"}) == set()
