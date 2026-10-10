"""What every stored daily feature row has to satisfy, counted in one pass over the table."""

from collections.abc import Iterator

from dagster import AssetCheckResult, AssetCheckSpec, multi_asset_check

from pipelines.assets.features.daily import daily_features
from pipelines.resources import Database

# Each rule's description and the condition a row breaking it meets.
RULES: dict[str, tuple[str, str]] = {
    "rsi_runs_from_0_to_100": (
        "RSI lies between 0 and 100.",
        "features.rsi_14 < 0 or features.rsi_14 > 100",
    ),
    "no_quantity_is_negative": (
        "Volatility, traded value, the volume ratio and the delivery shares are not negative.",
        (
            "least(features.volatility_20d, features.adtv_20d, features.volume_ratio_20d,"
            " features.delivery_pct_1d, features.delivery_pct_20d) < 0"
        ),
    ),
    "delivery_stays_within_volume": (
        (
            "A day's delivery share is at most 100 but on a venue day reviewed for counting more"
            " shares in its delivery file than in its bhavcopy."
        ),
        "features.delivery_pct_1d > 100 and reviewed.venue is null",
    ),
    "the_bands_hold_the_average": (
        "The 20-day bands lie either side of the 20-day average.",
        (
            "features.bollinger_20_lower > features.sma_20"
            " or features.sma_20 > features.bollinger_20_upper"
        ),
    ),
    "the_close_sits_at_or_below_the_52_week_high": (
        "The distance from the 52-week high lies above -1 and at or below 0.",
        "features.from_52w_high <= -1 or features.from_52w_high > 0",
    ),
    "averages_are_positive": (
        "Every moving average is above 0.",
        (
            "least(features.sma_20, features.sma_50, features.sma_200, features.ema_20,"
            " features.ema_50) <= 0"
        ),
    ),
    "a_diverging_day_is_incomplete": (
        "An instrument whose venues diverge falls on a day its venue judged incomplete.",
        "features.is_diverging and features.is_day_complete",
    ),
}

BREACHES = (
    "select "
    + ", ".join(f"count(*) filter (where {condition})" for _, condition in RULES.values())
    + " from mart_daily_features as features"
    " left join venue_delivery_discrepancies as reviewed"
    " on features.primary_venue = reviewed.venue and features.trade_date = reviewed.trade_date"
)


@multi_asset_check(
    specs=[
        AssetCheckSpec(name, asset=daily_features, description=description, blocking=True)
        for name, (description, _) in RULES.items()
    ]
)
def daily_feature_ranges(database: Database) -> Iterator[AssetCheckResult]:
    with database.connect() as connection:
        counts = connection.execute(BREACHES).fetchone()

    for (name, _), breaking in zip(RULES.items(), counts or [0] * len(RULES), strict=True):
        yield AssetCheckResult(
            check_name=name,
            asset_key=daily_features.key,
            passed=breaking == 0,
            metadata={"rows_breaking": int(breaking)},
        )
