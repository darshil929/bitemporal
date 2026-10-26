"""The migrations build the identity and fact tables and enforce their invariants."""

from datetime import date

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from fixtures.database import MIGRATION_SCHEMA

IDENTITY_TABLES = frozenset({"instrument_master", "listing", "listing_suspension"})
FACT_TABLES = frozenset(
    {"price_daily", "corporate_action", "instrument_name", "instrument_face_value", "ingestion_log"}
)
REGISTRY_TABLES = frozenset({"source_registry", "source_schema_version"})
DERIVED_TABLES = frozenset({"daily_features_a", "daily_features_b", "feature_release"})
ACCOUNT_TABLES = frozenset({"app_user", "app_session", "app_setting", "user_setting"})
MANAGED_TABLES = IDENTITY_TABLES | FACT_TABLES | REGISTRY_TABLES | DERIVED_TABLES | ACCOUNT_TABLES

BAR_COLUMNS = "isin, venue, trade_date, as_of_date, local_symbol, open, high, low, close, volume"
FEATURE_ROW = (
    "insert into {} (isin, trade_date, as_of_date, primary_venue, close, is_day_complete,"
    " is_diverging) values ('INE002A01018', %s, %s, 'NSE', 1500, true, false)"
)


def _connect(dsn: str) -> psycopg.Connection:
    return psycopg.connect(dsn, options=f"-csearch_path={MIGRATION_SCHEMA},public")


def _tables(dsn: str) -> set[str]:
    with _connect(dsn) as connection:
        rows = connection.execute(
            "select table_name from information_schema.tables where table_schema = %s",
            (MIGRATION_SCHEMA,),
        ).fetchall()
    return {str(row[0]) for row in rows}


def _add_instrument(connection: psycopg.Connection, isin: str) -> None:
    connection.execute(
        "insert into instrument_master (isin, name, country, instrument_type)"
        " values (%s, %s, %s, %s)",
        (isin, "Test Instrument", "IN", "equity"),
    )


def _add_bar(
    connection: psycopg.Connection,
    isin: str,
    as_of_date: str,
    close: str,
    high: str = "110",
) -> None:
    connection.execute(
        f"insert into price_daily ({BAR_COLUMNS}) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (isin, "NSE", "2026-07-31", as_of_date, "TESTCO", "100", high, "95", close, 1000),
    )


def test_upgrade_creates_every_managed_table(migrated: Config, postgres_dsn: str) -> None:
    assert MANAGED_TABLES <= _tables(postgres_dsn)


def test_migration_matches_the_model_definitions(migrated: Config) -> None:
    """Guards against the hand-written migration and the models drifting apart."""
    command.check(migrated)


def test_designated_venue_stretches_are_no_longer_stored(
    migrated: Config, postgres_dsn: str
) -> None:
    assert "instrument_primary_venue" not in _tables(postgres_dsn)


def test_downgrade_removes_every_table_it_created(migrated: Config, postgres_dsn: str) -> None:
    command.downgrade(migrated, "base")
    assert not MANAGED_TABLES & _tables(postgres_dsn)


def test_an_isin_that_is_not_an_isin_is_rejected(migrated: Config, postgres_dsn: str) -> None:
    with _connect(postgres_dsn) as connection, pytest.raises(psycopg.errors.CheckViolation):
        _add_instrument(connection, "RELIANCE")


def test_a_closed_listing_must_say_why_it_closed(migrated: Config, postgres_dsn: str) -> None:
    with _connect(postgres_dsn) as connection:
        _add_instrument(connection, "INE002A01018")

        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "insert into listing"
                " (isin, exchange, local_symbol, listing_date, delisting_date)"
                " values (%s, %s, %s, %s, %s)",
                ("INE002A01018", "NSE", "RELIANCE", "2020-01-01", "2024-01-01"),
            )


def test_a_rename_keeps_the_superseded_symbol(migrated: Config, postgres_dsn: str) -> None:
    """The symbol in force on a past date has to stay recoverable after a rename."""
    with _connect(postgres_dsn) as connection:
        _add_instrument(connection, "INE009A01021")
        connection.execute(
            "insert into listing"
            " (isin, exchange, local_symbol, listing_date, delisting_date, closure_reason)"
            " values (%s, %s, %s, %s, %s, %s)",
            ("INE009A01021", "NSE", "INFOSYSTCH", "2000-01-01", "2011-06-16", "renamed"),
        )
        connection.execute(
            "insert into listing (isin, exchange, local_symbol, listing_date)"
            " values (%s, %s, %s, %s)",
            ("INE009A01021", "NSE", "INFY", "2011-06-17"),
        )

        symbols = connection.execute(
            "select local_symbol from listing where listing_date <= %s"
            " and (delisting_date is null or delisting_date >= %s)",
            ("2010-01-01", "2010-01-01"),
        ).fetchall()

    assert [row[0] for row in symbols] == ["INFOSYSTCH"]


@pytest.mark.parametrize("table", ["price_daily", "daily_features_a", "daily_features_b"])
def test_a_daily_table_is_partitioned_on_trade_date(
    migrated: Config, postgres_dsn: str, table: str
) -> None:
    with _connect(postgres_dsn) as connection:
        dimensions = connection.execute(
            "select column_name from timescaledb_information.dimensions"
            " where hypertable_schema = %s and hypertable_name = %s",
            (MIGRATION_SCHEMA, table),
        ).fetchall()

    assert [row[0] for row in dimensions] == ["trade_date"]


def test_a_republished_bar_is_stored_beside_the_original(
    migrated: Config, postgres_dsn: str
) -> None:
    """A correction must not destroy what the close was believed to be beforehand."""
    with _connect(postgres_dsn) as connection:
        _add_instrument(connection, "INE002A01018")
        _add_bar(connection, "INE002A01018", as_of_date="2026-07-31", close="105")
        _add_bar(connection, "INE002A01018", as_of_date="2026-08-01", close="108")

        known_on_the_day = connection.execute(
            "select distinct on (isin, venue, trade_date) close from price_daily"
            " where as_of_date <= %s"
            " order by isin, venue, trade_date, as_of_date desc",
            ("2026-07-31",),
        ).fetchone()
        known_later = connection.execute(
            "select distinct on (isin, venue, trade_date) close from price_daily"
            " where as_of_date <= %s"
            " order by isin, venue, trade_date, as_of_date desc",
            ("2026-08-02",),
        ).fetchone()

    assert known_on_the_day is not None and float(known_on_the_day[0]) == 105
    assert known_later is not None and float(known_later[0]) == 108


def test_a_price_bar_cannot_be_updated(migrated: Config, postgres_dsn: str) -> None:
    with _connect(postgres_dsn) as connection:
        _add_instrument(connection, "INE002A01018")
        _add_bar(connection, "INE002A01018", as_of_date="2026-07-31", close="105")

        with pytest.raises(psycopg.errors.RestrictViolation):
            connection.execute("update price_daily set close = 999")


def test_a_corporate_action_cannot_be_updated(migrated: Config, postgres_dsn: str) -> None:
    with _connect(postgres_dsn) as connection:
        _add_instrument(connection, "INE002A01018")
        connection.execute(
            "insert into corporate_action"
            " (isin, action_type, ex_date, source_id, as_of_date, ratio_from, ratio_to)"
            " values (%s, 'split', %s, %s, %s, 1, 5)",
            ("INE002A01018", "2026-06-01", "bse_corporate_actions", "2026-05-20"),
        )

        with pytest.raises(psycopg.errors.RestrictViolation):
            connection.execute("update corporate_action set ratio_to = 10")


def test_an_instrument_name_cannot_be_updated(migrated: Config, postgres_dsn: str) -> None:
    with _connect(postgres_dsn) as connection:
        _add_instrument(connection, "INE002A01018")
        connection.execute(
            "insert into instrument_name (isin, source_id, as_of_date, name)"
            " values (%s, %s, %s, %s)",
            ("INE002A01018", "bse_scrip_list", "2026-10-02", "Reliance Industries Ltd"),
        )

        with pytest.raises(psycopg.errors.RestrictViolation):
            connection.execute("update instrument_name set name = 'Reliance'")


def test_an_instrument_face_value_cannot_be_updated(migrated: Config, postgres_dsn: str) -> None:
    with _connect(postgres_dsn) as connection:
        _add_instrument(connection, "INE002A01018")
        connection.execute(
            "insert into instrument_face_value (isin, source_id, as_of_date, face_value)"
            " values (%s, %s, %s, %s)",
            ("INE002A01018", "bse_scrip_list", "2026-10-02", "10"),
        )

        with pytest.raises(psycopg.errors.RestrictViolation):
            connection.execute("update instrument_face_value set face_value = 5")


def test_a_face_value_of_nothing_is_rejected(migrated: Config, postgres_dsn: str) -> None:
    with _connect(postgres_dsn) as connection:
        _add_instrument(connection, "INE002A01018")

        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "insert into instrument_face_value (isin, source_id, as_of_date, face_value)"
                " values ('INE002A01018', 'nse_equity_list', '2026-10-02', 0)"
            )


def test_a_bar_whose_high_is_below_its_open_is_rejected(
    migrated: Config, postgres_dsn: str
) -> None:
    with _connect(postgres_dsn) as connection:
        _add_instrument(connection, "INE002A01018")

        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                f"insert into price_daily ({BAR_COLUMNS})"
                " values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    "INE002A01018",
                    "NSE",
                    "2026-07-31",
                    "2026-07-31",
                    "TESTCO",
                    "120",
                    "110",
                    "95",
                    "100",
                    1,
                ),
            )


def test_a_close_outside_the_traded_range_is_accepted(migrated: Config, postgres_dsn: str) -> None:
    """BSE computes the close from the last half hour, so a thin day closes outside high and low."""
    with _connect(postgres_dsn) as connection:
        _add_instrument(connection, "INE002A01018")

        _add_bar(connection, "INE002A01018", as_of_date="2026-07-31", close="120", high="110")

        assert connection.execute("select count(*) from price_daily").fetchone() == (1,)

        # The downgrade of this migration reimposes the stricter constraint, which no row may
        # then violate.
        connection.execute("delete from price_daily")


def test_a_listing_can_close_as_superseded(migrated: Config, postgres_dsn: str) -> None:
    """A change of ISIN ends a stretch without the instrument leaving the venue."""
    with _connect(postgres_dsn) as connection:
        _add_instrument(connection, "INE721A01013")

        connection.execute(
            "insert into listing"
            " (isin, exchange, local_symbol, scrip_code, listing_date, delisting_date,"
            " closure_reason) values (%s, 'BSE', 'SHRIRAMFIN', '511218', %s, %s, 'superseded')",
            ("INE721A01013", "2024-01-02", "2025-01-09"),
        )

        assert connection.execute(
            "select count(*) from listing where closure_reason = 'superseded'"
        ).fetchone() == (1,)

        # The downgrade of this migration takes a superseded stretch back to delisted, and the
        # tests after this one read a table holding only what they insert.
        connection.execute("delete from listing")


def test_an_unhandled_action_is_recorded_with_its_text(migrated: Config, postgres_dsn: str) -> None:
    """A spin off carries no terms, so the text is what records that anything happened."""
    with _connect(postgres_dsn) as connection:
        _add_instrument(connection, "INE155A01022")

        connection.execute(
            "insert into corporate_action"
            " (isin, action_type, ex_date, source_id, as_of_date, qualifier, purpose)"
            " values (%s, 'unhandled', %s, %s, %s, %s, %s)",
            (
                "INE155A01022",
                "2025-10-14",
                "bse_corporate_actions",
                "2025-12-31",
                "spin off",
                "Spin Off",
            ),
        )

        assert connection.execute(
            "select count(*) from corporate_action where action_type = 'unhandled'"
        ).fetchone() == (1,)

        # The downgrade of this migration drops every unhandled action, and the test after it
        # reads a table holding only what it inserts.
        connection.execute("delete from corporate_action")


def test_an_unhandled_action_without_its_text_is_rejected(
    migrated: Config, postgres_dsn: str
) -> None:
    with _connect(postgres_dsn) as connection:
        _add_instrument(connection, "INE155A01022")

        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "insert into corporate_action"
                " (isin, action_type, ex_date, source_id, as_of_date, qualifier)"
                " values (%s, 'unhandled', %s, %s, %s, %s)",
                ("INE155A01022", "2025-10-14", "bse_corporate_actions", "2025-12-31", "spin off"),
            )


def test_a_split_without_a_ratio_is_rejected(migrated: Config, postgres_dsn: str) -> None:
    with _connect(postgres_dsn) as connection:
        _add_instrument(connection, "INE002A01018")

        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "insert into corporate_action"
                " (isin, action_type, ex_date, source_id, as_of_date)"
                " values (%s, 'split', %s, %s, %s)",
                ("INE002A01018", "2026-06-01", "bse_corporate_actions", "2026-05-20"),
            )


def test_a_daily_feature_row_names_bse_or_nse(migrated: Config, postgres_dsn: str) -> None:
    with _connect(postgres_dsn) as connection:
        _add_instrument(connection, "INE002A01018")

        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "insert into mart_daily_features (isin, trade_date, as_of_date, primary_venue,"
                " close, is_day_complete, is_diverging)"
                " values ('INE002A01018', '2025-12-31', '2025-12-31', 'MCX', 1500, true, false)"
            )


def test_stored_features_become_the_first_release(migrated: Config, postgres_dsn: str) -> None:
    command.downgrade(migrated, "0016")
    with _connect(postgres_dsn) as connection:
        _add_instrument(connection, "INE002A01018")
        for day in ("2025-12-30", "2025-12-31"):
            connection.execute(FEATURE_ROW.format("mart_daily_features"), (day, day))
    command.upgrade(migrated, "head")

    with _connect(postgres_dsn) as connection:
        releases = connection.execute(
            "select table_name, trade_date, row_count, run_id from feature_release"
        ).fetchall()
        shown = connection.execute("select count(*) from mart_daily_features").fetchone()
    assert releases == [("daily_features_a", date(2025, 12, 31), 2, None)]
    assert shown == (2,)


def test_an_installation_without_features_has_no_release(
    migrated: Config, postgres_dsn: str
) -> None:
    with _connect(postgres_dsn) as connection:
        assert connection.execute("select count(*) from feature_release").fetchone() == (0,)


def test_a_downgrade_keeps_the_published_computation(migrated: Config, postgres_dsn: str) -> None:
    with _connect(postgres_dsn) as connection:
        _add_instrument(connection, "INE002A01018")
        connection.execute(FEATURE_ROW.format("daily_features_b"), ("2025-12-31", "2025-12-31"))
        connection.execute(
            "create or replace view mart_daily_features as select * from daily_features_b"
        )
    command.downgrade(migrated, "0016")

    with _connect(postgres_dsn) as connection:
        kept = connection.execute("select trade_date from mart_daily_features").fetchall()
        kind = connection.execute(
            "select table_type from information_schema.tables"
            " where table_schema = %s and table_name = 'mart_daily_features'",
            (MIGRATION_SCHEMA,),
        ).fetchone()
    assert kept == [(date(2025, 12, 31),)]
    assert kind == ("BASE TABLE",)
    assert not {"daily_features_a", "daily_features_b"} & _tables(postgres_dsn)


def test_a_release_cannot_be_updated(migrated: Config, postgres_dsn: str) -> None:
    with _connect(postgres_dsn) as connection:
        connection.execute(
            "insert into feature_release (table_name, row_count) values ('daily_features_b', 0)"
        )

        with pytest.raises(psycopg.errors.RestrictViolation):
            connection.execute("update feature_release set row_count = 1")
