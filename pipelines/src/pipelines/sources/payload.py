"""Reading a venue's response as text, and the figures it states."""

from decimal import Decimal, InvalidOperation

from pipelines.sources.errors import SchemaDrift

# A zip, and so any spreadsheet, begins with these two bytes.
ARCHIVE_MAGIC = b"PK"


def decoded(payload: bytes, label: str) -> str:
    """Return the response as text, refusing one that is not text at all.

    A venue answers the same address with another format from time to time, such as a spreadsheet in
    place of a delivery file. Reporting that as a source failure leaves the caller free to record
    the day and carry on, where a decoding error would end a run reading years of them.
    """
    try:
        return payload.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        shape = "an archive" if payload[:2] == ARCHIVE_MAGIC else "not text"
        raise SchemaDrift(f"{label} response is {shape}") from error


def stated_face_value(text: object) -> Decimal | None:
    """The face value in rupees a record states, absent where it states none."""
    try:
        value = Decimal(str(text or "").strip())
    except InvalidOperation:
        return None
    return value if value > 0 else None
