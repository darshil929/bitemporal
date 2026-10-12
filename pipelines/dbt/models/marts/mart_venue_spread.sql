select
    isin,
    trade_date,
    as_of_date,
    bse_close,
    nse_close,
    venue_spread_bps,
    comparable_turnover
from {{ ref('int_venue_spread') }}
