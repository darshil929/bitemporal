"""Table definitions for instrument identity and the market facts keyed on it."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    MetaData,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Deterministic constraint names, required for a downgrade to drop them by name.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s",
    "pk": "pk_%(table_name)s",
}

# ISO 6166: two-letter country prefix, nine alphanumeric characters, one check digit.
ISIN_PATTERN = "^[A-Z]{2}[A-Z0-9]{9}[0-9]$"
VENUE_PATTERN = "^[A-Z][A-Z0-9]{1,11}$"

INSTRUMENT_TYPES = ("equity", "preference_share", "debt", "etf", "warrant", "right")
CLOSURE_REASONS = ("delisted", "renamed", "merged")
ACTION_TYPES = ("split", "bonus", "consolidation", "rights", "dividend")
INGESTION_OUTCOMES = ("succeeded", "not_published", "failed")

PRICE = Numeric(18, 4)
RATIO = Numeric(18, 6)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _in_list(column: str, values: tuple[str, ...]) -> str:
    rendered = ", ".join(f"'{value}'" for value in values)
    return f"{column} in ({rendered})"


class InstrumentMaster(Base):
    __tablename__ = "instrument_master"

    isin: Mapped[str] = mapped_column(String(12), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    sector: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str] = mapped_column(String(2))
    instrument_type: Mapped[str] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(f"isin ~ '{ISIN_PATTERN}'", name="isin_format"),
        CheckConstraint("country ~ '^[A-Z]{2}$'", name="country_format"),
        CheckConstraint(_in_list("instrument_type", INSTRUMENT_TYPES), name="instrument_type"),
    )


class Listing(Base):
    """One row per symbol an instrument has traded under at a venue.

    A rename closes the current row and opens a new one, so the symbol in force on a past date
    stays recoverable.
    """

    __tablename__ = "listing"

    listing_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    isin: Mapped[str] = mapped_column(String(12), ForeignKey("instrument_master.isin"))
    exchange: Mapped[str] = mapped_column(String(12))
    local_symbol: Mapped[str] = mapped_column(Text)
    scrip_code: Mapped[str | None] = mapped_column(Text)
    listing_date: Mapped[date] = mapped_column(Date)
    delisting_date: Mapped[date | None] = mapped_column(Date)
    closure_reason: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("isin", "exchange", "local_symbol", "listing_date"),
        CheckConstraint(f"exchange ~ '{VENUE_PATTERN}'", name="exchange_format"),
        CheckConstraint(
            "delisting_date is null or delisting_date >= listing_date",
            name="closes_after_it_opens",
        ),
        # A rename and a delisting produce the same shape without a stated reason.
        CheckConstraint(
            "(delisting_date is null) = (closure_reason is null)",
            name="closure_reason_accompanies_delisting_date",
        ),
        CheckConstraint(
            f"closure_reason is null or {_in_list('closure_reason', CLOSURE_REASONS)}",
            name="closure_reason",
        ),
    )


class ListingSuspension(Base):
    """Periods during which a listing was suspended from trading."""

    __tablename__ = "listing_suspension"

    listing_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("listing.listing_id"), primary_key=True
    )
    suspended_from: Mapped[date] = mapped_column(Date, primary_key=True)
    as_of_date: Mapped[date] = mapped_column(Date, primary_key=True)
    suspended_to: Mapped[date | None] = mapped_column(Date)

    __table_args__ = (
        CheckConstraint(
            "suspended_to is null or suspended_to >= suspended_from",
            name="ends_after_it_starts",
        ),
    )


class InstrumentPrimaryVenue(Base):
    """The venue an instrument's series is computed from, over a span of dates.

    Recomputed on a schedule from trailing turnover. Each recomputation inserts a row rather than
    replacing one, leaving every earlier assignment readable.
    """

    __tablename__ = "instrument_primary_venue"

    isin: Mapped[str] = mapped_column(
        String(12), ForeignKey("instrument_master.isin"), primary_key=True
    )
    effective_from: Mapped[date] = mapped_column(Date, primary_key=True)
    as_of_date: Mapped[date] = mapped_column(Date, primary_key=True)
    effective_to: Mapped[date | None] = mapped_column(Date)
    venue: Mapped[str] = mapped_column(String(12))

    __table_args__ = (
        CheckConstraint(f"venue ~ '{VENUE_PATTERN}'", name="venue_format"),
        CheckConstraint(
            "effective_to is null or effective_to > effective_from",
            name="ends_after_it_starts",
        ),
    )


class PriceDaily(Base):
    """One bar per instrument, venue, trading day and the date that bar became knowable.

    A venue republishing a corrected file inserts a further row rather than replacing the first.
    The close believed to hold on any past date is therefore still recoverable. Reads go through
    the staging model that resolves the latest version at or before the query date.

    Columns hold the figures exactly as published. An adjusted series is derived rather than
    stored, because a corporate action years later changes every earlier adjusted price and this
    table admits no update.
    """

    __tablename__ = "price_daily"

    isin: Mapped[str] = mapped_column(
        String(12), ForeignKey("instrument_master.isin"), primary_key=True
    )
    venue: Mapped[str] = mapped_column(String(12), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    as_of_date: Mapped[date] = mapped_column(Date, primary_key=True)

    open: Mapped[Decimal] = mapped_column(PRICE)
    high: Mapped[Decimal] = mapped_column(PRICE)
    low: Mapped[Decimal] = mapped_column(PRICE)
    close: Mapped[Decimal] = mapped_column(PRICE)
    previous_close: Mapped[Decimal | None] = mapped_column(PRICE)
    volume: Mapped[int] = mapped_column(BigInteger)
    turnover: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    trade_count: Mapped[int | None] = mapped_column(BigInteger)

    __table_args__ = (
        CheckConstraint(f"venue ~ '{VENUE_PATTERN}'", name="venue_format"),
        # The close is not constrained to the traded range: BSE computes it from the last half
        # hour of trading, so on a thin day it falls outside the day's high and low.
        CheckConstraint(
            "high >= low and high >= open and low <= open",
            name="bar_is_internally_consistent",
        ),
        CheckConstraint(
            "open >= 0 and high >= 0 and low >= 0 and close >= 0 and volume >= 0",
            name="quantities_are_not_negative",
        ),
        # The hypertable is created without default indexes, so this one is declared here.
        Index("ix_price_daily_trade_date", "trade_date"),
    )


class DeliveryDaily(Base):
    """Shares that settled rather than closing out intraday, for one instrument, venue and day.

    A venue publishes this in a file of its own, hours after the bhavcopy and sometimes not at
    all, so it is a fact in its own right rather than a column on the bar. Neither file names an
    instrument by ISIN, so a row is resolved through the listing in force on its trade date.
    """

    __tablename__ = "delivery_daily"

    isin: Mapped[str] = mapped_column(
        String(12), ForeignKey("instrument_master.isin"), primary_key=True
    )
    venue: Mapped[str] = mapped_column(String(12), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    as_of_date: Mapped[date] = mapped_column(Date, primary_key=True)
    delivery_quantity: Mapped[int] = mapped_column(BigInteger)

    __table_args__ = (
        CheckConstraint(f"venue ~ '{VENUE_PATTERN}'", name="venue_format"),
        CheckConstraint("delivery_quantity >= 0", name="quantity_is_not_negative"),
        Index("ix_delivery_daily_trade_date", "trade_date"),
    )


class CorporateAction(Base):
    """Actions that change the share count or pay out value, as reported on a given date.

    `ratio_from` and `ratio_to` are the share count before and after: a one-for-five split is
    1 to 5, a one-for-two bonus is 2 to 3. Both collapse to the same adjustment factor, so
    adjustment never branches on action type.

    `source_id` forms part of the key, so two venues reporting the same action with different
    terms are stored as separate rows for the cross-check to compare.
    """

    __tablename__ = "corporate_action"

    isin: Mapped[str] = mapped_column(
        String(12), ForeignKey("instrument_master.isin"), primary_key=True
    )
    action_type: Mapped[str] = mapped_column(Text, primary_key=True)
    ex_date: Mapped[date] = mapped_column(Date, primary_key=True)
    source_id: Mapped[str] = mapped_column(Text, primary_key=True)
    as_of_date: Mapped[date] = mapped_column(Date, primary_key=True)
    # An ordinary and a special dividend share an ex-date, so the kind belongs in the key.
    qualifier: Mapped[str] = mapped_column(Text, primary_key=True, server_default="ordinary")

    ratio_from: Mapped[Decimal | None] = mapped_column(RATIO)
    ratio_to: Mapped[Decimal | None] = mapped_column(RATIO)
    dividend_amount: Mapped[Decimal | None] = mapped_column(PRICE)

    __table_args__ = (
        CheckConstraint(_in_list("action_type", ACTION_TYPES), name="action_type"),
        CheckConstraint(
            "(action_type = 'dividend') = (dividend_amount is not null)",
            name="a_dividend_pays_an_amount",
        ),
        CheckConstraint(
            "(action_type <> 'dividend') = (ratio_from is not null)",
            name="everything_else_changes_a_ratio",
        ),
        CheckConstraint("(ratio_from is null) = (ratio_to is null)", name="ratio_has_both_sides"),
        CheckConstraint(
            "(ratio_from is null or ratio_from > 0) and (ratio_to is null or ratio_to > 0)",
            name="ratio_sides_are_positive",
        ),
    )


class SourceRegistry(Base):
    """Every external source the ingestion layer reads, with the trust tier it carries.

    Tiers 1 and 2 are exchange-published files and official endpoints. Tier 3 wraps them without
    permission and tier 4 is a third party; neither may be the sole provider of a field in a mart.
    """

    __tablename__ = "source_registry"

    source_id: Mapped[str] = mapped_column(Text, primary_key=True)
    tier: Mapped[int] = mapped_column(SmallInteger)
    base_url: Mapped[str] = mapped_column(Text)
    requests_per_second: Mapped[Decimal] = mapped_column(Numeric(6, 3))
    cache_policy: Mapped[str] = mapped_column(Text)
    sebi_curation_ref: Mapped[str | None] = mapped_column(Text)
    owner_notes: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("tier between 1 and 4", name="tier_range"),
        CheckConstraint("requests_per_second > 0", name="rate_is_positive"),
    )


class SourceSchemaVersion(Base):
    """The parser version covering a span of partition dates for one source.

    An open `effective_to` marks the version in force. A partition falling in no span is an error
    rather than a default, so a format change that nobody registered stops ingestion.
    """

    __tablename__ = "source_schema_version"

    source_id: Mapped[str] = mapped_column(
        Text, ForeignKey("source_registry.source_id"), primary_key=True
    )
    effective_from: Mapped[date] = mapped_column(Date, primary_key=True)
    version: Mapped[str] = mapped_column(Text)
    effective_to: Mapped[date | None] = mapped_column(Date)

    __table_args__ = (
        CheckConstraint(
            "effective_to is null or effective_to >= effective_from",
            name="ends_after_it_starts",
        ),
    )


class TradingDay(Base):
    """Whether a venue's day passed validation, and what it failed on if it did not.

    Downstream reads consume complete days only. A day revalidated after a correction appends a
    row rather than replacing one, so the verdict that stood on a past date stays readable.
    """

    __tablename__ = "trading_day"

    venue: Mapped[str] = mapped_column(String(12), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    as_of_date: Mapped[date] = mapped_column(Date, primary_key=True)
    is_complete: Mapped[bool] = mapped_column(Boolean)
    bars: Mapped[int] = mapped_column(Integer)
    divergent_instruments: Mapped[int] = mapped_column(Integer)
    detail: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(f"venue ~ '{VENUE_PATTERN}'", name="venue_format"),
        CheckConstraint("bars >= 0", name="bars_is_not_negative"),
        CheckConstraint("(is_complete) = (detail is null)", name="detail_explains_a_failure"),
    )


class IngestionLog(Base):
    """One row per attempt to fetch a slice of a source."""

    __tablename__ = "ingestion_log"

    ingestion_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    source_id: Mapped[str] = mapped_column(Text)
    partition_key: Mapped[str] = mapped_column(Text)
    schema_version: Mapped[str] = mapped_column(Text)
    outcome: Mapped[str] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    row_count: Mapped[int | None] = mapped_column(Integer)
    detail: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(_in_list("outcome", INGESTION_OUTCOMES), name="outcome"),
        CheckConstraint(
            "(outcome = 'succeeded') = (row_count is not null)",
            name="a_success_counts_its_rows",
        ),
    )
