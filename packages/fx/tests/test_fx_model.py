"""FX canonical-direction rule (Epic FX, FX1). DB-free."""

from __future__ import annotations

import pytest

from fx.model import canonical_pair, is_canonical_direction


def test_usd_is_always_base():
    assert canonical_pair("USD", "BRL") == ("USD", "BRL")
    assert canonical_pair("BRL", "USD") == ("USD", "BRL")  # order-independent
    assert canonical_pair("USD", "EUR") == ("USD", "EUR")
    assert canonical_pair("GBP", "USD") == ("USD", "GBP")


def test_non_usd_cross_sorts_alphabetically():
    assert canonical_pair("EUR", "GBP") == ("EUR", "GBP")
    assert canonical_pair("GBP", "EUR") == ("EUR", "GBP")  # only one legal direction
    assert canonical_pair("JPY", "BRL") == ("BRL", "JPY")


def test_self_pair_has_no_stored_rate():
    with pytest.raises(ValueError, match="self-pair"):
        canonical_pair("USD", "USD")
    with pytest.raises(ValueError, match="self-pair"):
        canonical_pair("EUR", "EUR")


def test_is_canonical_direction_mirrors_the_sql_check():
    # Legal stored directions
    assert is_canonical_direction("USD", "BRL")
    assert is_canonical_direction("EUR", "GBP")
    # Illegal: inverse of USD-base, both-direction cross, USD-as-quote, self-pair
    assert not is_canonical_direction("BRL", "USD")
    assert not is_canonical_direction("GBP", "EUR")
    assert not is_canonical_direction("BRL", "USD")
    assert not is_canonical_direction("EUR", "USD")
    assert not is_canonical_direction("USD", "USD")
    assert not is_canonical_direction("EUR", "EUR")


def test_canonical_pair_output_is_always_canonical():
    for a, b in [("USD", "JPY"), ("JPY", "USD"), ("EUR", "GBP"), ("GBP", "EUR"), ("CHF", "AUD")]:
        base, quote = canonical_pair(a, b)
        assert is_canonical_direction(base, quote)
