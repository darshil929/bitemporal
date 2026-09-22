"""Reading a venue's response as text."""

from pipelines.sources.errors import SchemaDrift

# A zip, and so any spreadsheet, begins with these two bytes.
ARCHIVE_MAGIC = b"PK"


def decoded(payload: bytes, label: str) -> str:
    """Return the response as text, refusing one that is not text at all.

    A venue answers the same address with another format from time to time: NSE served a
    spreadsheet in place of the delivery file on 2022-08-08. Reporting that as a source failure
    leaves the caller free to record the day and carry on, where a decoding error would end a run
    reading years of them.
    """
    try:
        return payload.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        shape = "an archive" if payload[:2] == ARCHIVE_MAGIC else "not text"
        raise SchemaDrift(f"{label} response is {shape}") from error
