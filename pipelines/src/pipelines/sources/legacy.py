"""Parsers for the bhavcopy formats both venues published before 8 July 2024."""

import csv
import io
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import ConfigDict, Field, field_validator

from pipelines.models.market import PriceBar
from pipelines.sources.bhavcopy import BhavcopyRow, BlankAsNone, validated
from pipelines.sources.errors import SchemaDrift, WrongDay

# BSE dates its legacy rows 15-Jan-24 and NSE dates its own 15-JAN-2024.
BSE_DATE_FORMAT = "%d-%b-%y"
NSE_DATE_FORMAT = "%d-%b-%Y"


def _parse_day(value: object, fmt: str) -> date:
    """A trade date names a calendar day at the venue and carries no time or offset.

    A line carrying fewer fields than the header leaves this one absent rather than wrong, and
    csv presents that as None. Refusing it here reports the line as unreadable instead of
    raising out of the validator.
    """
    if isinstance(value, date):
        return value
    if value is None:
        raise ValueError("trade date is absent")
    return datetime.strptime(str(value).strip(), fmt).date()  # noqa: DTZ007


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
    def _parse_date(cls, value: object) -> date:
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
    def _parse_date(cls, value: object) -> date:
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

# BSE published this file without a trade date column until 23 June 2017, and once afterwards on
# 14 December 2017. The layouts are otherwise the same, the column standing where TRADING_DATE
# does now, so the day the file was asked for supplies what it does not carry.
BSE_DATED_COLUMN = "TRADING_DATE"
BSE_UNDATED_COLUMNS = BSE_LEGACY_COLUMNS - {BSE_DATED_COLUMN}
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


def parse_bse_legacy(payload: bytes, partition: date | None = None) -> tuple[BseLegacyRow, ...]:
    """Read a BSE legacy bhavcopy, dating its rows from the request when the file does not.

    A file that carries its own trade date is held to it: every one of the 1,735 dated days read
    so far describes the day it was asked for, so one that disagrees is the wrong file rather
    than a surprise.
    """
    reader = _read(payload, BSE_UNDATED_COLUMNS, "bse legacy")
    undated = BSE_DATED_COLUMN not in {name.strip() for name in reader.fieldnames or ()}

    if undated and partition is None:
        raise SchemaDrift(f"bse legacy bhavcopy is missing ['{BSE_DATED_COLUMN}']")

    rows = ({**row, BSE_DATED_COLUMN: partition} for row in reader) if undated else reader
    parsed = validated(BseLegacyRow, rows, "bse legacy")

    if not undated and partition is not None:
        served = {row.trade_date for row in parsed}
        if served and served != {partition}:
            raise WrongDay(f"bse legacy bhavcopy for {partition} describes {sorted(served)[:3]}")

    return parsed


def parse_nse_legacy(payload: bytes) -> tuple[NseLegacyRow, ...]:
    reader = _read(payload, NSE_LEGACY_COLUMNS, "nse legacy")
    return validated(NseLegacyRow, reader, "nse legacy")
