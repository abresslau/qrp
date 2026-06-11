"""B3 sector classification source tests (Story QH.1) — fake client/conn, no network."""

from __future__ import annotations

import pytest

from sym.classification.b3 import (
    B3ClassificationError,
    B3GicsSource,
    map_segment_to_gics,
    normalise_segment,
    parse_sector_rows,
)
from sym.classification.gics import SecurityIdentity, read_unclassified_identities

# --- normalisation + mapping -----------------------------------------------------------


def test_normalise_segment_strips_accents_case_and_double_spaces():
    assert normalise_segment("Cons N  Básico / Alimentos Processados") == (
        "cons n basico/alimentos processados"
    )
    # accentless and accented variants land on the same key
    assert normalise_segment("Cons N Ciclico/Agropecuária") == normalise_segment(
        "Cons N Cíclico/Agropecuaria"
    )


@pytest.mark.parametrize(
    ("segment", "expected"),
    [
        # every segment observed live (IBOV+IBXX, 2026-06-11) must map
        ("Bens Indls / Mat Transporte", "Industrials"),
        ("Bens Indls / Máqs e Equips", "Industrials"),
        ("Bens Indls / Serviços", "Industrials"),
        ("Bens Indls/Transporte", "Industrials"),
        ("Comput e Equips", "Information Technology"),
        ("Cons N  Básico / Alimentos Processados", "Consumer Staples"),
        ("Cons N Ciclico/Agropecuária", "Consumer Staples"),
        ("Cons N Cíclico / Bebidas", "Consumer Staples"),
        ("Cons N Cíclico / Comércio Distr.", "Consumer Staples"),
        ("Cons N Cíclico / Pr Pessoal Limp", "Consumer Staples"),
        ("Consumo Cíclico / Comércio", "Consumer Discretionary"),
        ("Consumo Cíclico / Tecid Vest Calç", "Consumer Discretionary"),
        ("Consumo Cíclico/Constr Civil", "Consumer Discretionary"),
        ("Consumo Cíclico/Viagens e Lazer", "Consumer Discretionary"),
        ("Diversos", "Consumer Discretionary"),
        ("Financ e Outros / Holdings Divers", "Financials"),
        ("Financ e Outros / Interms Financs", "Financials"),
        ("Financ e Outros / Previd  Seguros", "Financials"),
        ("Financeiro e Outros/Serviços Financeiros Diversos", "Financials"),
        ("Mats Básicos / Madeira e Papel", "Materials"),
        ("Mats Básicos / Mineração", "Materials"),
        ("Mats Básicos / Químicos", "Materials"),
        ("Mats Básicos / Sid Metalurgia", "Materials"),
        ("Petróleo, Gás e Biocombustíveis", "Energy"),
        ("Saúde/Comércio Distr.", "Health Care"),
        ("Saúde/SM Hosp An.Diag", "Health Care"),
        ("Tec.Informação/Programas Servs", "Information Technology"),
        ("Telecomunicação", "Communication Services"),
        ("Utilidade Públ / Energ Elétrica", "Utilities"),
        ("Utilidade Públ / Água Saneamento", "Utilities"),
    ],
)
def test_every_observed_segment_maps(segment, expected):
    assert map_segment_to_gics(segment) == expected


def test_real_estate_exception_beats_the_financials_prefix():
    # B3 files property under "Financeiro e Outros"; GICS split Real Estate out in 2016
    assert map_segment_to_gics("Financ e Outros / Explor Imóveis") == "Real Estate"
    assert map_segment_to_gics("Financ e Outros / Interms Financs") == "Financials"


def test_real_estate_exception_survives_slash_spacing_and_spelling_variants():
    # the feed mixes "X / Y" and "X/Y" and both sector spellings — a variant missing
    # the exception would be silently classified Financials (wrong write, not a report)
    assert map_segment_to_gics("Financ e Outros/Explor Imóveis") == "Real Estate"
    assert map_segment_to_gics("Financeiro e Outros / Explor Imoveis") == "Real Estate"
    assert map_segment_to_gics("Financeiro e Outros/Explor Imóveis") == "Real Estate"


def test_normalise_segment_canonicalises_slash_spacing():
    assert normalise_segment("Bens Indls / Transporte") == normalise_segment(
        "Bens Indls/Transporte"
    )


def test_unknown_segment_maps_to_none_never_guessed():
    assert map_segment_to_gics("Setor Novo / Coisa Desconhecida") is None
    assert map_segment_to_gics("") is None


# --- parsing ----------------------------------------------------------------------------


def test_parse_sector_rows_skips_rows_without_cod_or_segment():
    rows = [
        {"cod": "PETR4", "segment": "Petróleo, Gás e Biocombustíveis"},
        {"cod": "", "segment": "Diversos"},
        {"cod": "XXXX3"},  # no segment
        {"segment": "Diversos"},  # no cod
        {"cod": "weg e3 ", "segment": " Bens Indls / Máqs e Equips "},
    ]
    out = parse_sector_rows(rows)
    assert out == {
        "PETR4": "Petróleo, Gás e Biocombustíveis",
        "WEG E3": "Bens Indls / Máqs e Equips",
    }


# --- the source -------------------------------------------------------------------------


class FakeB3Client:
    def __init__(self, by_index: dict[str, list[dict]]):
        self.by_index = by_index
        self.calls: list[str] = []

    def portfolio_sectors(self, index_code: str) -> list[dict]:
        self.calls.append(index_code)
        return self.by_index[index_code]


def test_b3_source_classifies_sector_only_with_b3_provenance():
    client = FakeB3Client({
        "IBOV": [{"cod": "PETR4", "segment": "Petróleo, Gás e Biocombustíveis"}],
        "IBXX": [{"cod": "WEGE3", "segment": "Bens Indls / Máqs e Equips"}],
    })
    source = B3GicsSource(client)
    identities = [
        SecurityIdentity("FIGI_PETR0000", ticker="PETR4"),
        SecurityIdentity("FIGI_WEGE0000", ticker="WEGE3"),
        SecurityIdentity("FIGI_OTHER000", ticker="AAPL"),  # not a B3 constituent
    ]
    found = source.fetch(identities)
    assert set(found) == {"FIGI_PETR0000", "FIGI_WEGE0000"}
    petr = found["FIGI_PETR0000"]
    assert petr.sector_name == "Energy"
    assert petr.source == "b3"
    # sector level ONLY — the depth-honesty rule
    assert petr.industry_group_name is None
    assert petr.industry_name is None
    assert petr.sub_industry_name is None
    assert petr.sector_code is None
    assert client.calls == ["IBOV", "IBXX"]


def test_b3_source_reports_unmapped_segments_instead_of_guessing():
    client = FakeB3Client({
        "IBOV": [
            {"cod": "PETR4", "segment": "Petróleo, Gás e Biocombustíveis"},
            {"cod": "NEWX3", "segment": "Setor Novo / Inclassificável"},
        ],
        "IBXX": [],
    })
    source = B3GicsSource(client)
    identities = [
        SecurityIdentity("FIGI_PETR0000", ticker="PETR4"),
        SecurityIdentity("FIGI_NEWX0000", ticker="NEWX3"),
    ]
    found = source.fetch(identities)
    assert set(found) == {"FIGI_PETR0000"}  # the unmapped name is NOT classified
    assert source.last_unmapped == {"NEWX3": "Setor Novo / Inclassificável"}


def test_b3_source_resets_unmapped_between_fetches():
    client = FakeB3Client({
        "IBOV": [{"cod": "PETR4", "segment": "Petróleo, Gás e Biocombustíveis"}],
        "IBXX": [],
    })
    source = B3GicsSource(client)
    source.last_unmapped = {"STALE": "left over"}
    source.fetch([SecurityIdentity("FIGI_PETR0000", ticker="PETR4")])
    assert source.last_unmapped == {}


def test_b3_source_empty_portfolios_raise_loudly():
    client = FakeB3Client({"IBOV": [], "IBXX": []})
    source = B3GicsSource(client)
    with pytest.raises(B3ClassificationError, match="zero constituents"):
        source.fetch([SecurityIdentity("FIGI_PETR0000", ticker="PETR4")])


def test_b3_source_ignores_identities_without_tickers():
    client = FakeB3Client({
        "IBOV": [{"cod": "PETR4", "segment": "Petróleo, Gás e Biocombustíveis"}],
        "IBXX": [],
    })
    found = B3GicsSource(client).fetch([SecurityIdentity("FIGI_NOTICK00", ticker=None)])
    assert found == {}


def test_b3_source_never_matches_foreign_mic_identities():
    # B3 tickers are exchange-local strings — a foreign security sharing one must
    # never receive a Brazilian sector
    client = FakeB3Client({
        "IBOV": [{"cod": "PETR4", "segment": "Petróleo, Gás e Biocombustíveis"}],
        "IBXX": [],
    })
    source = B3GicsSource(client)
    found = source.fetch([
        SecurityIdentity("FIGI_LONDON00", ticker="PETR4", mic="XLON"),  # collision
        SecurityIdentity("FIGI_NOMIC000", ticker="PETR4", mic=None),  # mic-less: trusted
    ])
    assert set(found) == {"FIGI_NOMIC000"}


def test_b3_source_matches_bvmf_mic_identities():
    client = FakeB3Client({
        "IBOV": [{"cod": "PETR4", "segment": "Petróleo, Gás e Biocombustíveis"}],
        "IBXX": [],
    })
    found = B3GicsSource(client).fetch(
        [SecurityIdentity("FIGI_PETR0000", ticker="PETR4", mic="BVMF")]
    )
    assert set(found) == {"FIGI_PETR0000"}


def test_b3_source_records_unmapped_even_for_constituents_outside_the_request():
    # drift visibility: a new B3 abbreviation must surface even when the constituent
    # is already classified by the primary source (and thus not in the fill scope)
    client = FakeB3Client({
        "IBOV": [{"cod": "NEWX3", "segment": "Setor Novo / Inclassificável"}],
        "IBXX": [{"cod": "PETR4", "segment": "Petróleo, Gás e Biocombustíveis"}],
    })
    source = B3GicsSource(client)
    source.fetch([SecurityIdentity("FIGI_PETR0000", ticker="PETR4", mic="BVMF")])
    assert source.last_unmapped == {"NEWX3": "Setor Novo / Inclassificável"}


def test_b3_source_skips_cross_view_conflicts_instead_of_last_wins():
    client = FakeB3Client({
        "IBOV": [
            {"cod": "CONF3", "segment": "Saúde/SM Hosp An.Diag"},
            {"cod": "AGRE3", "segment": "Bens Indls / Transporte"},
        ],
        "IBXX": [
            {"cod": "CONF3", "segment": "Mats Básicos / Químicos"},  # different GICS!
            {"cod": "AGRE3", "segment": "Bens Indls/Transporte"},  # same after normalise
        ],
    })
    source = B3GicsSource(client)
    found = source.fetch([
        SecurityIdentity("FIGI_CONF0000", ticker="CONF3", mic="BVMF"),
        SecurityIdentity("FIGI_AGRE0000", ticker="AGRE3", mic="BVMF"),
    ])
    # the genuinely-conflicting name is skipped + reported; the spelling variant is not
    assert set(found) == {"FIGI_AGRE0000"}
    assert source.last_conflicts == {
        "CONF3": ("Saúde/SM Hosp An.Diag", "Mats Básicos / Químicos")
    }


def test_b3_source_attributes_in_scope_identities_it_could_not_fill():
    client = FakeB3Client({
        "IBOV": [{"cod": "PETR4", "segment": "Petróleo, Gás e Biocombustíveis"}],
        "IBXX": [],
    })
    source = B3GicsSource(client)
    source.fetch([
        SecurityIdentity("FIGI_PETR0000", ticker="PETR4", mic="BVMF"),
        SecurityIdentity("FIGI_GONE0000", ticker="GONE3", mic="BVMF"),  # not a constituent
    ])
    assert source.last_unmatched == ["GONE3"]  # attributed, never fabricated


# --- the fill-only scope query ----------------------------------------------------------


class _Cursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _RecordingConn:
    def __init__(self, rows):
        self.sql: str | None = None
        self._rows = rows

    def execute(self, sql, params=None):
        self.sql = sql
        return _Cursor(self._rows)


def test_read_unclassified_identities_scopes_to_active_without_current_gics():
    conn = _RecordingConn([("FIGI_A0000000", "BVMF", None, "ABEV3")])
    out = read_unclassified_identities(conn)
    assert out == [SecurityIdentity("FIGI_A0000000", None, "ABEV3", "BVMF")]
    # the fill-only guarantee lives in this SQL: active scope + no currently-effective row
    assert "s.status = 'active'" in conn.sql
    assert "NOT EXISTS" in conn.sql
    assert "gics_scd" in conn.sql
    assert "valid_to IS NULL" in conn.sql
    assert "s.mic" in conn.sql  # exchange scope for exchange-local sources
