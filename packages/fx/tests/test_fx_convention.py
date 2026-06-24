"""FX quoting convention — the seniority ranking that sets each pair's conventional base."""

from __future__ import annotations

from fx.convention import conventional_pair, quote_rank


def test_majors_outrank_usd_quote():
    # EUR/GBP/AUD/NZD outrank USD -> they are the base (XXX/USD)
    assert conventional_pair("USD", "EUR") == ("EUR", "USD")
    assert conventional_pair("GBP", "USD") == ("GBP", "USD")
    assert conventional_pair("USD", "AUD") == ("AUD", "USD")
    assert conventional_pair("NZD", "USD") == ("NZD", "USD")


def test_usd_is_base_below_it():
    # USD outranks JPY/CAD/CHF/CNY/BRL -> USD/XXX
    assert conventional_pair("JPY", "USD") == ("USD", "JPY")
    assert conventional_pair("USD", "CAD") == ("USD", "CAD")
    assert conventional_pair("CHF", "USD") == ("USD", "CHF")
    assert conventional_pair("USD", "BRL") == ("USD", "BRL")  # standard: USD base for BRL


def test_cross_pairs_follow_rank():
    assert conventional_pair("JPY", "EUR") == ("EUR", "JPY")  # EUR/JPY
    assert conventional_pair("CHF", "GBP") == ("GBP", "CHF")  # GBP/CHF
    assert conventional_pair("JPY", "AUD") == ("AUD", "JPY")  # AUD/JPY


def test_added_majors_rank_below_usd():
    # the broader majors (Scandies, HKD/SGD/MXN) are quoted USD/XXX, EUR/XXX
    assert conventional_pair("SEK", "USD") == ("USD", "SEK")
    assert conventional_pair("NOK", "EUR") == ("EUR", "NOK")
    assert conventional_pair("USD", "HKD") == ("USD", "HKD")
    assert conventional_pair("MXN", "GBP") == ("GBP", "MXN")


def test_unknown_currency_sinks_to_quote_deterministically():
    assert quote_rank("ZZZ") > quote_rank("USD")
    assert conventional_pair("USD", "ZZZ") == ("USD", "ZZZ")  # known currency is the base
    # two unknowns -> alphabetical, stable
    assert conventional_pair("ZZZ", "AAA") == ("AAA", "ZZZ")
