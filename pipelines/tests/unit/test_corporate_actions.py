"""Reading BSE corporate actions and turning their purpose text into terms."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from pipelines.sources.bse.corporate_actions import normalize, parse_actions, parse_purpose
from pipelines.sources.errors import SchemaDrift

CASSETTES = Path(__file__).resolve().parents[1] / "fixtures" / "cassettes"
BSE_ACTIONS = CASSETTES / "bse_corporate_actions"

RELIANCE = "INE002A01018"
SHRIRAM = "INE721A01047"
TATA_MOTORS_PV = "INE155A01022"

SCRIP_TO_ISIN = {"500325": RELIANCE, "511218": SHRIRAM, "500570": TATA_MOTORS_PV}
REPORTED_ON = date(2026, 8, 16)


def payload(scrip_code: str) -> bytes:
    return (BSE_ACTIONS / f"{scrip_code}.json").read_bytes()


def test_a_one_for_one_bonus_doubles_the_share_count() -> None:
    assert parse_purpose("Bonus issue 1:1") == ("bonus", "ordinary", Decimal(1), Decimal(2), None)


def test_a_one_for_two_bonus_takes_two_shares_to_three() -> None:
    """The terms are shares received to shares held, so the count goes from two to three."""
    assert parse_purpose("Bonus issue 1:2") == ("bonus", "ordinary", Decimal(2), Decimal(3), None)


def test_a_split_reads_its_terms_from_the_face_values() -> None:
    """The purpose text carries a double space that must not defeat the match."""
    assert parse_purpose("Stock  Split From Rs.10/- to Rs.2/-") == (
        "split",
        "ordinary",
        Decimal(1),
        Decimal(5),
        None,
    )


def test_a_rise_in_face_value_is_a_consolidation() -> None:
    action_type, _, ratio_from, ratio_to, _ = parse_purpose("Stock Split From Rs.1/- to Rs.10/-")

    assert action_type == "consolidation"
    assert ratio_from == Decimal(10)
    assert ratio_to == Decimal(1)


def test_a_dividend_reads_its_amount() -> None:
    assert parse_purpose("Final Dividend - Rs. - 10.0000") == (
        "dividend",
        "final",
        None,
        None,
        Decimal("10.0000"),
    )


def test_an_ordinary_and_a_special_dividend_on_one_day_stay_apart() -> None:
    """BSE reports both on the same ex-date, so the kind belongs in the key."""
    ordinary = parse_purpose("Dividend - Rs. - 8.7500")
    special = parse_purpose("Special Dividend - Rs. - 0.7500")

    assert ordinary[1] == "ordinary"
    assert special[1] == "special"


def test_an_action_whose_terms_are_not_in_the_text_is_reported_unhandled() -> None:
    """A spin off changes value by an amount the purpose text does not carry."""
    assert parse_purpose("Spin Off")[0] == "unhandled"
    assert parse_purpose("Scheme of Arrangement")[0] == "unhandled"


def test_a_response_that_is_not_a_list_is_rejected() -> None:
    with pytest.raises(SchemaDrift):
        parse_actions(b'{"error": "no data"}')


def test_a_record_missing_its_ex_date_is_rejected() -> None:
    with pytest.raises(SchemaDrift) as failure:
        parse_actions(b'[{"scrip_code": 500325, "Purpose": "Bonus issue 1:1"}]')

    assert "exdate" in str(failure.value)


def test_the_recorded_reliance_bonus_normalizes() -> None:
    actions = normalize(parse_actions(payload("500325")), SCRIP_TO_ISIN, REPORTED_ON)
    bonus = [item for item in actions if item.action_type == "bonus"]

    assert len(bonus) == 1
    assert bonus[0].ex_date == date(2024, 10, 28)
    assert bonus[0].ratio_from == Decimal(1)
    assert bonus[0].ratio_to == Decimal(2)
    assert bonus[0].isin == RELIANCE


def test_the_recorded_shriram_split_normalizes() -> None:
    actions = normalize(parse_actions(payload("511218")), SCRIP_TO_ISIN, REPORTED_ON)
    splits = [item for item in actions if item.action_type == "split"]

    assert len(splits) == 1
    assert splits[0].ex_date == date(2025, 1, 10)
    assert splits[0].ratio_from == Decimal(1)
    assert splits[0].ratio_to == Decimal(5)


def test_a_spin_off_is_left_out_rather_than_guessed(caplog: pytest.LogCaptureFixture) -> None:
    actions = normalize(parse_actions(payload("500570")), SCRIP_TO_ISIN, REPORTED_ON)

    assert all(item.action_type != "unhandled" for item in actions)
    assert not [item for item in actions if item.ex_date == date(2025, 10, 14)]


def test_a_scrip_outside_the_mapping_is_skipped() -> None:
    assert normalize(parse_actions(payload("500325")), {}, REPORTED_ON) == ()
