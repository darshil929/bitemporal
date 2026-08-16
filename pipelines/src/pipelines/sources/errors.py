"""Exceptions raised by the ingestion layer."""


class SourceError(Exception):
    """Base for every failure originating in a source adapter."""


class NotPublished(SourceError):
    """The source has no data for the requested partition.

    Raised for a holiday, a non-trading day, or a file the venue has not released yet. A caller
    records the partition as unpublished and moves on.
    """


class SourceUnavailable(SourceError):
    """The source could not be reached, or answered with an error after every retry."""


class UnknownSchemaVersion(SourceError):
    """No registered schema version covers the requested date."""


class SchemaDrift(SourceError):
    """The response no longer carries the columns the parser reads."""
