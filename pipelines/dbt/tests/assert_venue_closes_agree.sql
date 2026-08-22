-- A gap this wide is a corporate action handled at one venue and not the other, not liquidity.
-- Observed spreads sit under 25 basis points at the ninety ninth percentile.
select
    isin,
    trade_date,
    bse_close,
    nse_close,
    venue_spread_bps
from {{ ref('int_venue_spread') }}
where venue_spread_bps > 500
