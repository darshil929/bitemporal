"""Reading a CSV out of a zipped venue response."""

import io
import zipfile

from pipelines.sources.errors import SourceUnavailable


def extract_csv(archive: bytes) -> bytes:
    """Return the single CSV the archive carries."""
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as opened:
            names = [name for name in opened.namelist() if name.lower().endswith(".csv")]
            if len(names) != 1:
                raise SourceUnavailable(f"archive holds {len(names)} csv entries, expected one")
            return opened.read(names[0])
    except zipfile.BadZipFile as error:
        raise SourceUnavailable("archive is not a zip file") from error
