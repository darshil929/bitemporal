"""Parsers for the bhavcopy formats both venues published before 8 July 2024."""

import csv
import io
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import ConfigDict, Field, field_validator

from pipelines.models.market import PriceBar
from pipelines.sources.bhavcopy import BhavcopyRow, BlankAsNone
from pipelines.sources.errors import SchemaDrift

# BSE dates its legacy rows 15-Jan-24 and NSE dates its own 15-JAN-2024.
BSE_DATE_FORMAT = "%d-%b-%y"
NSE_DATE_FORMAT = "%d-%b-%Y"


def _parse_day(value: str | date, fmt: str) -> date:
    """A trade date names a calendar day at the venue and carries no time or offset."""
    if isinstance(value, date):
        return value
    return datetime.strptime(value.strip(), fmt).date()  # noqa: DTZ007


class BseLegacyRow(BhavcopyRow):
    """One row of the BSE bhavcopy that carries an ISIN column.

    BSE published two legacy files per day. Only this one names the instrument by ISIN; the
    other identifies it by scrip code alone and cannot be joined without the instrument master.

    The format carries no ticker, so a bar reports the scrip code as the venue-local symbol. BSE
    began publishing a ticker with the UDiFF cutover.
    """

    model_config = ConfigDict(populate_by_name=True)

    scrip_code: str = Field(alias="SC_CODE")
    name: str = Field(alias="SC_NAME")
    group: str = Field(alias="SC_GROUP")
    open: Decimal = Field(alias="OPEN")
    high: Decimal = Field(alias="HIGH")
    low: Decimal = Field(alias="LOW")
    close: Decimal = Field(alias="CLOSE")
    previous_close: Annotated[Decimal | None, BlankAsNone] = Field(default=None, alias="PREVCLOSE")
    trade_count: Annotated[int | None, BlankAsNone] = Field(default=None, alias="NO_TRADES")
    volume: int = Field(alias="NO_OF_SHRS")
    turnover: Annotated[Decimal | None, BlankAsNone] = Field(default=None, alias="NET_TURNOV")
    isin: str = Field(alias="ISIN_CODE")
    trade_date: date = Field(alias="TRADING_DATE")

    @field_validator("trade_date", mode="before")
    @classmethod
    def _parse_date(cls, value: str | date) -> date:
        return _parse_day(value, BSE_DATE_FORMAT)

    @field_validator("group", "scrip_code", "isin", "name", mode="before")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value

    @property
    def series(self) -> str:
        return self.group

    @property
    def security_name(self) -> str:
        return self.name

    def to_bar(self, venue: str) -> PriceBar:
        return PriceBar(
            isin=self.isin,
            venue=venue,
            trade_date=self.trade_date,
            as_of_date=self.trade_date,
            local_symbol=self.scrip_code,
            scrip_code=self.scrip_code,
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            previous_close=self.previous_close,
            volume=self.volume,
            turnover=self.turnover,
            trade_count=self.trade_count,
        )


class NseLegacyRow(BhavcopyRow):
    """One row of the NSE bhavcopy published before the UDiFF cutover."""

    model_config = ConfigDict(populate_by_name=True)

    symbol: str = Field(alias="SYMBOL")
    security_series: str = Field(alias="SERIES")
    open: Decimal = Field(alias="OPEN")
    high: Decimal = Field(alias="HIGH")
    low: Decimal = Field(alias="LOW")
    close: Decimal = Field(alias="CLOSE")
    previous_close: Annotated[Decimal | None, BlankAsNone] = Field(default=None, alias="PREVCLOSE")
    volume: int = Field(alias="TOTTRDQTY")
    turnover: Annotated[Decimal | None, BlankAsNone] = Field(default=None, alias="TOTTRDVAL")
    trade_date: date = Field(alias="TIMESTAMP")
    trade_count: Annotated[int | None, BlankAsNone] = Field(default=None, alias="TOTALTRADES")
    isin: str = Field(alias="ISIN")

    @field_validator("trade_date", mode="before")
    @classmethod
    def _parse_date(cls, value: str | date) -> date:
        return _parse_day(value, NSE_DATE_FORMAT)

    @property
    def series(self) -> str:
        return self.security_series

    @property
    def security_name(self) -> str:
        return self.symbol

    def to_bar(self, venue: str) -> PriceBar:
        return PriceBar(
            isin=self.isin,
            venue=venue,
            trade_date=self.trade_date,
            as_of_date=self.trade_date,
            local_symbol=self.symbol,
            scrip_code=None,
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            previous_close=self.previous_close,
            volume=self.volume,
            turnover=self.turnover,
            trade_count=self.trade_count,
        )


BSE_LEGACY_COLUMNS = frozenset(
    field.alias for field in BseLegacyRow.model_fields.values() if field.alias
)
NSE_LEGACY_COLUMNS = frozenset(
    field.alias for field in NseLegacyRow.model_fields.values() if field.alias
)


def _read(payload: bytes, required: frozenset[str], label: str) -> csv.DictReader[str]:
    reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig")))
    present = {name.strip() for name in reader.fieldnames or ()}
    missing = required - present
    if missing:
        raise SchemaDrift(f"{label} bhavcopy is missing {sorted(missing)}")
    return reader


def parse_bse_legacy(payload: bytes) -> tuple[BseLegacyRow, ...]:
    reader = _read(payload, BSE_LEGACY_COLUMNS, "bse legacy")
    return tuple(BseLegacyRow.model_validate(row) for row in reader)


def parse_nse_legacy(payload: bytes) -> tuple[NseLegacyRow, ...]:
    reader = _read(payload, NSE_LEGACY_COLUMNS, "nse legacy")
    return tuple(NseLegacyRow.model_validate(row) for row in reader)
