"""Tests for membership projection reconciliation (Story V5). DB-free pure logic."""

from __future__ import annotations

from datetime import date

from sym.validate.projection import reconcile


def test_in_sync_no_diffs():
    stored = {"F1": {(date(2020, 1, 1), None)}}
    projected = {"F1": {(date(2020, 1, 1), None)}}
    assert reconcile(stored, projected) == []


def test_missing_interval_in_stored():
    stored = {"F1": set()}
    projected = {"F1": {(date(2020, 1, 1), None)}}
    diffs = reconcile(stored, projected)
    assert len(diffs) == 1 and "F1" in diffs[0]


def test_extra_interval_in_stored():
    stored = {"F1": {(date(2020, 1, 1), date(2021, 1, 1))}}
    projected = {"F1": {(date(2020, 1, 1), None)}}
    assert len(reconcile(stored, projected)) == 1


def test_figi_only_in_one_side():
    assert len(reconcile({"F1": {(date(2020, 1, 1), None)}}, {})) == 1
    assert len(reconcile({}, {"F2": {(date(2020, 1, 1), None)}})) == 1
