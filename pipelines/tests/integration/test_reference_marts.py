"""The instrument, listing, trading day and source marts the application reads."""

from collections.abc import Sequence
from typing import Any

import psycopg
import pytest
from psycopg import sql

from pipelines.sources.registry import load_definitions

BAJAJ_FINANCE_BEFORE_SPLIT = "INE296A01024"
BAJAJ_FINANCE = "INE296A01032"
HDFC_BANK = "INE040A01034"


def rows(
    connection: psycopg.Connection, query: sql.Composed | str, parameters: Sequence[Any] = ()
) -> list[tuple[Any, ...]]:
    return connection.execute(query, parameters).fetchall()


@pytest.mark.parametrize(
    ("mart", "model"),
    [("mart_listings", "stg_listings"), ("mart_trading_days", "stg_trading_day")],
)
def test_a_mart_presents_every_row_of_its_model(
    seeded_models: psycopg.Connection, mart: str, model: str
) -> None:
    ordered = sql.SQL("select * from {} order by 1, 2, 3")
    presented = rows(seeded_models, ordered.format(sql.Identifier(mart)))

    assert presented
    assert presented == rows(seeded_models, ordered.format(sql.Identifier(model)))


def test_every_instrument_appears_once_under_its_display_name(
    seeded_models: psycopg.Connection,
) -> None:
    named = rows(seeded_models, "select isin, display_name from mart_instruments order by isin")

    assert [isin for isin, _ in named] == [
        isin for (isin,) in rows(seeded_models, "select isin from stg_instruments order by isin")
    ]
    assert named == rows(
        seeded_models,
        "select isin, display_name from int_instrument_display_names order by isin",
    )


def test_an_isin_replaced_at_a_split_points_to_the_isin_trading_now(
    seeded_models: psycopg.Connection,
) -> None:
    current = dict(
        rows(
            seeded_models,
            "select isin, current_isin from mart_instruments where isin = any(%s)",
            ([BAJAJ_FINANCE_BEFORE_SPLIT, BAJAJ_FINANCE, HDFC_BANK],),
        )
    )

    assert current == {
        BAJAJ_FINANCE_BEFORE_SPLIT: BAJAJ_FINANCE,
        BAJAJ_FINANCE: BAJAJ_FINANCE,
        HDFC_BANK: HDFC_BANK,
    }


def test_the_sources_are_those_configured(seeded_models: psycopg.Connection) -> None:
    sources = rows(
        seeded_models,
        "select source_id, tier, sebi_curation_ref, base_url from mart_sources order by source_id",
    )

    assert sources == sorted(
        (source.source_id, source.tier, source.sebi_curation_ref, source.base_url)
        for source in load_definitions()
    )
