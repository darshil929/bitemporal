"""Source definitions load from configuration and select a parser by partition date."""

from datetime import date

import pytest

from pipelines.sources.errors import UnknownSchemaVersion
from pipelines.sources.registry import SourceDefinition, load_definitions

BHAVCOPY_SOURCES = ("bse_bhavcopy_equity", "nse_bhavcopy_equity")
LAST_LEGACY_DAY = date(2024, 7, 5)
FIRST_UDIFF_DAY = date(2024, 7, 8)


@pytest.fixture(scope="module")
def definitions() -> dict[str, SourceDefinition]:
    return {definition.source_id: definition for definition in load_definitions()}


def test_every_definition_carries_a_tier_and_accounts_for_its_curation(
    definitions: dict[str, SourceDefinition],
) -> None:
    """SEBI curates the exchanges' bulk reports, so an exchange file names the row that lists it.

    A source outside that list is an exchange endpoint rather than a report, below the first tier,
    and its notes say why no row names it.
    """
    for definition in definitions.values():
        assert 1 <= definition.tier <= 4
        if definition.sebi_curation_ref is None:
            assert definition.tier >= 2, f"{definition.source_id} is a report with no curation row"
            assert definition.owner_notes and "curation" in definition.owner_notes, (
                f"{definition.source_id} names no curation row and does not say why"
            )


@pytest.mark.parametrize("source_id", BHAVCOPY_SOURCES)
def test_both_venues_switch_to_udiff_on_the_same_day(
    definitions: dict[str, SourceDefinition], source_id: str
) -> None:
    """BSE and NSE replaced their bhavcopy with the same format on the same date."""
    definition = definitions[source_id]

    assert definition.version_for(FIRST_UDIFF_DAY) == "udiff"
    assert definition.version_for(LAST_LEGACY_DAY).endswith("legacy")


def test_a_date_before_any_registered_version_is_an_error(
    definitions: dict[str, SourceDefinition],
) -> None:
    with pytest.raises(UnknownSchemaVersion):
        definitions["bse_bhavcopy_equity"].version_for(date(1990, 1, 1))


def test_a_version_without_an_end_date_covers_every_later_partition(
    definitions: dict[str, SourceDefinition],
) -> None:
    for source_id in BHAVCOPY_SOURCES:
        assert definitions[source_id].version_for(date(2030, 1, 1)) == "udiff"
