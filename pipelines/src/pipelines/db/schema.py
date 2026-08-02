"""Table definitions for instrument identity."""

from datetime import date

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKey,
    Identity,
    MetaData,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Named constraints so a downgrade can drop what an upgrade created.
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
        # A closed row must say why it closed, because a rename and a delisting are the same
        # shape otherwise and only one of them means the instrument stopped trading.
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

    Recomputed on a schedule from trailing turnover. Each recomputation inserts rather than
    replaces, so a past decision stays readable.
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
