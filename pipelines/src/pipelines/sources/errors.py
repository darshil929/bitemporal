"""Exceptions raised by the ingestion layer."""


class SourceError(Exception):
    """Base for every failure originating in a source adapter."""


class UnknownSchemaVersion(SourceError):
    """No registered schema version covers the requested date."""
