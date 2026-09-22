"""What an asset needs from outside itself: the database, and the venue adapters."""

from collections.abc import Iterator
from contextlib import contextmanager

import httpx
import psycopg
from dagster import ConfigurableResource

from pipelines.config.settings import DatabaseSettings, SourceSettings
from pipelines.sources.bse.bhavcopy import BseBhavcopy
from pipelines.sources.bse.corporate_actions import BseCorporateActions
from pipelines.sources.cache import DiskCache
from pipelines.sources.client import Throttle, ThrottledClient
from pipelines.sources.nse.bhavcopy import NseBhavcopy
from pipelines.sources.registry import SourceDefinition, load_definitions

# NSE's archive host drops a request that does not look like a browser, which the source registry
# records as an exception scoped to that venue.
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)

BHAVCOPY_SOURCES = {"BSE": "bse_bhavcopy_equity", "NSE": "nse_bhavcopy_equity"}
ACTIONS_SOURCE = "bse_corporate_actions"


class Database(ConfigurableResource[None]):
    """Connections to the schema the active data environment names."""

    @contextmanager
    def connect(self) -> Iterator[psycopg.Connection]:
        settings = DatabaseSettings()
        _, _, rest = settings.database_url.partition("://")
        with psycopg.connect(
            f"postgresql://{rest}", options=f"-csearch_path={settings.schema_name},public"
        ) as connection:
            yield connection


class Bhavcopies(ConfigurableResource[None]):
    """The price adapter for each venue, throttled at the rate its registry entry states."""

    def definition(self, venue: str) -> SourceDefinition:
        wanted = BHAVCOPY_SOURCES[venue]
        return next(item for item in load_definitions() if item.source_id == wanted)

    def adapter(self, venue: str) -> BseBhavcopy | NseBhavcopy:
        settings = SourceSettings()
        definition = self.definition(venue)
        cache = DiskCache(settings.source_cache_dir)
        agent = BROWSER_USER_AGENT if venue == "NSE" else settings.source_user_agent
        client = ThrottledClient(
            definition.source_id,
            httpx.Client(headers={"User-Agent": agent}, follow_redirects=True),
            Throttle(1 / definition.requests_per_second),
        )

        if venue == "NSE":
            return NseBhavcopy(client, cache, definition.base_url)
        return BseBhavcopy(client, cache, definition.base_url)


class CorporateActions(ConfigurableResource[None]):
    """The BSE corporate action adapter, throttled at the rate its registry entry states."""

    def definition(self) -> SourceDefinition:
        return next(item for item in load_definitions() if item.source_id == ACTIONS_SOURCE)

    def adapter(self) -> BseCorporateActions:
        settings = SourceSettings()
        definition = self.definition()
        client = ThrottledClient(
            definition.source_id,
            httpx.Client(headers={"User-Agent": settings.source_user_agent}, follow_redirects=True),
            Throttle(1 / definition.requests_per_second),
        )
        return BseCorporateActions(
            client, DiskCache(settings.source_cache_dir), definition.base_url
        )
