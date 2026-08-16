"""Parser for the UDiFF bhavcopy, published in the same format by BSE and NSE."""

import csv
import io
import logging
from collections import Counter
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from pipelines.models.market import PriceBar
from pipelines.sources.errors import SchemaDrift

logger = logging.getLogger(__name__)

# Series that trade as ordinary equity. Every other series in the file is a bond, an exchange
# traded fund, a government security or a trust unit. A new equity series must be added here or
# its instruments are skipped.
EQUITY_SERIES: dict[str, frozenset[str]] = {
    "BSE": frozenset({"A", "B", "M", "MS", "MT", "P", "R", "T", "TS", "X", "XT", "Z", "ZP", "ZY"}),
    "NSE": frozenset({"EQ", "BE", "BZ", "SM", "ST"}),
}


def _blank_to_none(value: Any) -> Any:
    return None if value == "" else value


BlankAsNone = BeforeValidator(_blank_to_none)


class UdiffRow(BaseModel):
    """One row of a UDiFF bhavcopy, aliased to the column names the file uses."""

    model_config = ConfigDict(populate_by_name=True)

    trade_date: date = Field(alias="TradDt")
    instrument_id: str = Field(alias="FinInstrmId")
    isin: str = Field(alias="ISIN")
    ticker_symbol: str = Field(alias="TckrSymb")
    series: str = Field(alias="SctySrs")
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


REQUIRED_COLUMNS = frozenset(field.alias for field in UdiffRow.model_fields.values() if field.alias)


def parse_udiff(payload: bytes) -> tuple[UdiffRow, ...]:
    """Read a bhavcopy into validated rows, performing no input or output."""
    reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig")))
    present = set(reader.fieldnames or ())

    missing = REQUIRED_COLUMNS - present
    if missing:
        raise SchemaDrift(f"bhavcopy is missing {sorted(missing)}")

    return tuple(UdiffRow.model_validate(row) for row in reader)


def normalize(rows: Sequence[UdiffRow], venue: str) -> tuple[PriceBar, ...]:
    """Map the equity rows onto canonical bars, keyed on ISIN."""
    equity_series = EQUITY_SERIES[venue]
    skipped: Counter[str] = Counter()
    bars = []

    for row in rows:
        if row.series not in equity_series:
            skipped[row.series] += 1
            continue
        bars.append(
            PriceBar(
                isin=row.isin,
                venue=venue,
                trade_date=row.trade_date,
                as_of_date=row.trade_date,
                local_symbol=row.ticker_symbol,
                scrip_code=row.instrument_id if venue == "BSE" else None,
                open=row.open,
                high=row.high,
                low=row.low,
                close=row.close,
                previous_close=row.previous_close,
                volume=row.volume,
                turnover=row.turnover,
                trade_count=row.trade_count,
            )
        )

    if skipped:
        logger.info(
            "non-equity series skipped",
            extra={"venue": venue, "skipped": dict(skipped), "kept": len(bars)},
        )

    return tuple(bars)
