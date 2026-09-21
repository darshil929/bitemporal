-- A gap this wide, where both venues traded heavily, is a corporate action handled at one venue
-- and not the other. A thinly traded instrument closes wherever its last trade put it, so it is
-- left out rather than read as disagreement.
select
    isin,
    trade_date,
    bse_close,
    nse_close,
    venue_spread_bps,
    comparable_turnover
from {{ ref('int_venue_spread') }}
where
    venue_spread_bps > 500
    and comparable_turnover >= 2500000
