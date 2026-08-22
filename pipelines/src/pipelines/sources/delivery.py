"""Parsers for the delivery files both venues publish beside the bhavcopy.

Neither file names an instrument by ISIN. NSE keys on ticker and series, BSE on scrip code, so a
row carries the venue-local identifier and is resolved through the listing in force on its date.
"""

import csv
import io
import logging
import zipfile
from collections.abc import Sequence
from datetime import date, datetime

from pydantic import BaseModel

from pipelines.models.market import DeliveryRecord
from pipelines.sources.errors import SchemaDrift, SourceUnavailable

logger = logging.getLogger(__name__)

NSE_COLUMNS = frozenset({"SYMBOL", "SERIES", "DATE1", "TTL_TRD_QNTY", "DELIV_QTY"})
BSE_COLUMNS = frozenset({"DATE", "SCRIP CODE", "DELIVERY QTY"})

NSE_DATE_FORMAT = "%d-%b-%Y"
BSE_DATE_FORMAT = "%d%m%Y"

# A series that settles no delivery reports a dash rather than a zero.
NOT_DELIVERABLE = "-"


class DeliveryRow(BaseModel):
    """One venue's delivery figure, still named the way the venue names it."""

    venue_key: str
    trade_date: date
    delivery_quantity: int


def _parse_day(value: str, fmt: str) -> date:
    return datetime.strptime(value.strip(), fmt).date()  # noqa: DTZ007


def parse_nse_delivery(payload: bytes) -> tuple[DeliveryRow, ...]:
    """Read the NSE security-wise file, whose header pads every name with a space."""
    reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig")))
    present = {name.strip() for name in reader.fieldnames or ()}
    missing = NSE_COLUMNS - present
    if missing:
        raise SchemaDrift(f"nse delivery file is missing {sorted(missing)}")

    rows = []
    for record in reader:
        stripped = {key.strip(): (value or "").strip() for key, value in record.items() if key}
        quantity = stripped["DELIV_QTY"]
        if quantity == NOT_DELIVERABLE:
            continue
        rows.append(
            DeliveryRow(
                venue_key=stripped["SYMBOL"],
                trade_date=_parse_day(stripped["DATE1"], NSE_DATE_FORMAT),
                delivery_quantity=int(quantity),
            )
        )
    return tuple(rows)


def parse_bse_delivery(payload: bytes) -> tuple[DeliveryRow, ...]:
    """Read the BSE gross file, which is pipe delimited with zero padded quantities."""
    text = _extract(payload)
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        raise SchemaDrift("bse delivery file is empty")

    header = [name.strip() for name in lines[0].split("|")]
    missing = BSE_COLUMNS - set(header)
    if missing:
        raise SchemaDrift(f"bse delivery file is missing {sorted(missing)}")

    index = {name: position for position, name in enumerate(header)}
    rows = []
    for line in lines[1:]:
        fields = [field.strip() for field in line.split("|")]
        if len(fields) < len(header):
            continue
        rows.append(
            DeliveryRow(
                venue_key=fields[index["SCRIP CODE"]].lstrip("0") or "0",
                trade_date=_parse_day(fields[index["DATE"]], BSE_DATE_FORMAT),
                delivery_quantity=int(fields[index["DELIVERY QTY"]]),
            )
        )
    return tuple(rows)


def _extract(archive: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as opened:
            names = opened.namelist()
            if len(names) != 1:
                raise SourceUnavailable(f"archive holds {len(names)} entries, expected one")
            return opened.read(names[0]).decode("utf-8")
    except zipfile.BadZipFile as error:
        raise SourceUnavailable("archive is not a zip file") from error


def normalize(
    rows: Sequence[DeliveryRow], venue: str, isin_for_key: dict[str, str]
) -> tuple[DeliveryRecord, ...]:
    """Resolve each row to an ISIN through the venue-local identifier it carries."""
    records = []
    unresolved: set[str] = set()

    for row in rows:
        isin = isin_for_key.get(row.venue_key)
        if isin is None:
            unresolved.add(row.venue_key)
            continue
        records.append(
            DeliveryRecord(
                isin=isin,
                venue=venue,
                trade_date=row.trade_date,
                as_of_date=row.trade_date,
                delivery_quantity=row.delivery_quantity,
            )
        )

    if unresolved:
        logger.info(
            "delivery rows outside the tracked universe",
            extra={"venue": venue, "unresolved": len(unresolved), "kept": len(records)},
        )

    return tuple(records)
