-- The gap between the two venues' closes for a dual-listed instrument, in basis points against
-- their midpoint. A gap beyond tolerance usually means an unhandled corporate action at one venue.
with by_venue as (
    select
        isin,
        trade_date,
        max(as_of_date) as as_of_date,
        max(close) filter (where venue = 'BSE') as bse_close,
        max(close) filter (where venue = 'NSE') as nse_close
    from {{ ref('stg_price_daily') }}
    group by isin, trade_date
)

select
    isin,
    trade_date,
    as_of_date,
    bse_close,
    nse_close,
    round(
        10000 * abs(bse_close - nse_close) / ((bse_close + nse_close) / 2), 4
    ) as venue_spread_bps
from by_venue
where bse_close is not null and nse_close is not null
