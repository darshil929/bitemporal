"""Parsers for the delivery files both venues publish beside the bhavcopy.

Neither file names an instrument by ISIN. NSE keys on ticker and series, BSE on scrip code, so a
row carries the venue-local identifier and is resolved through the listing in force on its date.
"""

import csv
import io
import logging
import re
import zipfile
from collections.abc import Sequence
from datetime import date, datetime

from pydantic import BaseModel

from pipelines.models.market import DeliveryRecord
from pipelines.sources.errors import MalformedRow, SchemaDrift, SourceUnavailable, WrongDay
from pipelines.sources.payload import decoded

logger = logging.getLogger(__name__)

NSE_COLUMNS = frozenset({"SYMBOL", "SERIES", "DATE1", "TTL_TRD_QNTY", "DELIV_QTY"})
BSE_COLUMNS = frozenset({"DATE", "SCRIP CODE", "DELIVERY QTY"})

NSE_DATE_FORMAT = "%d-%b-%Y"
BSE_DATE_FORMAT = "%d%m%Y"

# The position file states its day once, above the rows, as Trade Date <14-AUG-2026>, and marks
# each security's row with the record type 20.
POSITION_TRADE_DATE = re.compile(r"Trade Date <(\d{2}-[A-Za-z]{3}-\d{4})>")
POSITION_RECORD = "20"
POSITION_FIELDS = 7

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
    reader = csv.DictReader(io.StringIO(decoded(payload, "nse delivery")))
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


def parse_nse_position(payload: bytes) -> tuple[DeliveryRow, ...]:
    """Read the NSE security-wise delivery position file, which carries the full file's figures."""
    text = decoded(payload, "nse delivery position")
    stated = POSITION_TRADE_DATE.search(text)
    if stated is None:
        raise SchemaDrift("nse delivery position file states no trade date")
    trade_date = _parse_day(stated.group(1), NSE_DATE_FORMAT)

    rows = []
    for line in text.splitlines():
        fields = [field.strip() for field in line.split(",")]
        if fields[0] != POSITION_RECORD:
            continue
        if len(fields) != POSITION_FIELDS:
            raise MalformedRow(f"nse delivery position row has {len(fields)} fields: {line[:80]}")
        quantity = fields[5]
        if quantity == NOT_DELIVERABLE:
            continue
        if not quantity.isdigit():
            raise MalformedRow(f"nse delivery position quantity is not a count: {line[:80]}")
        rows.append(
            DeliveryRow(venue_key=fields[2], trade_date=trade_date, delivery_quantity=int(quantity))
        )

    if not rows:
        raise SchemaDrift("nse delivery position file holds no rows")
    return tuple(rows)


def held_to(rows: Sequence[DeliveryRow], day: date, venue: str) -> Sequence[DeliveryRow]:
    """The rows of a file describing the day it was asked for.

    NSE answers some days it held no session on, and some it did, with the file of another day.
    """
    served = {row.trade_date for row in rows}
    if served and served != {day}:
        raise WrongDay(f"{venue} delivery for {day} describes {sorted(served)[:3]}")
    return rows


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
            return decoded(opened.read(names[0]), "bse delivery")
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
