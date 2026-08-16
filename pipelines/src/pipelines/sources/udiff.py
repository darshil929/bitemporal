"""Parser for the UDiFF bhavcopy, published in the same format by BSE and NSE."""

import csv
import io
from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import ConfigDict, Field

from pipelines.models.market import PriceBar
from pipelines.sources.bhavcopy import BhavcopyRow, BlankAsNone
from pipelines.sources.errors import SchemaDrift


class UdiffRow(BhavcopyRow):
    """One row of a UDiFF bhavcopy, aliased to the column names the file uses."""

    model_config = ConfigDict(populate_by_name=True)

    trade_date: date = Field(alias="TradDt")
    instrument_id: str = Field(alias="FinInstrmId")
    isin: str = Field(alias="ISIN")
    ticker_symbol: str = Field(alias="TckrSymb")
    security_series: str = Field(alias="SctySrs")
    open: Decimal = Field(alias="OpnPric")
    high: Decimal = Field(alias="HghPric")
    low: Decimal = Field(alias="LwPric")
    close: Decimal = Field(alias="ClsPric")
    previous_close: Annotated[Decimal | None, BlankAsNone] = Field(
        default=None, alias="PrvsClsgPric"
    )
    volume: int = Field(alias="TtlTradgVol")
    turnover: Annotated[Decimal | None, BlankAsNone] = Field(default=None, alias="TtlTrfVal")
    trade_count: Annotated[int | None, BlankAsNone] = Field(default=None, alias="TtlNbOfTxsExctd")

    @property
    def series(self) -> str:
        return self.security_series

    def to_bar(self, venue: str) -> PriceBar:
        return PriceBar(
            isin=self.isin,
            venue=venue,
            trade_date=self.trade_date,
            as_of_date=self.trade_date,
            local_symbol=self.ticker_symbol,
            scrip_code=self.instrument_id if venue == "BSE" else None,
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            previous_close=self.previous_close,
            volume=self.volume,
            turnover=self.turnover,
            trade_count=self.trade_count,
        )


REQUIRED_COLUMNS = frozenset(field.alias for field in UdiffRow.model_fields.values() if field.alias)


def parse_udiff(payload: bytes) -> tuple[UdiffRow, ...]:
    """Read a bhavcopy into validated rows, performing no input or output."""
    reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig")))
    missing = REQUIRED_COLUMNS - set(reader.fieldnames or ())
    if missing:
        raise SchemaDrift(f"udiff bhavcopy is missing {sorted(missing)}")

    return tuple(UdiffRow.model_validate(row) for row in reader)
