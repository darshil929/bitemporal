"""The price, adjusted series, spread and delivery marts the application reads."""

import psycopg
import pytest
from psycopg import sql

# Rows in the mart, and rows found on one side and not the other, duplicates counted.
UNMATCHED = sql.SQL(
    "select (select count(*) from {mart}),"
    " (select count(*) from ((table {mart} except all table {model})"
    " union all (table {model} except all table {mart})) as unmatched)"
)


@pytest.mark.parametrize(
    ("mart", "model"),
    [
        ("mart_price_daily", "stg_price_daily"),
        ("mart_adjusted_prices", "int_continuous_prices"),
        ("mart_venue_spread", "int_venue_spread"),
        ("mart_delivery_daily", "int_delivery_participation"),
    ],
)
def test_a_mart_presents_every_row_of_its_model(
    seeded_models: psycopg.Connection, mart: str, model: str
) -> None:
    query = UNMATCHED.format(mart=sql.Identifier(mart), model=sql.Identifier(model))
    counts = seeded_models.execute(query).fetchone()

    assert counts is not None
    presented, unmatched = counts
    assert presented > 0
    assert unmatched == 0
