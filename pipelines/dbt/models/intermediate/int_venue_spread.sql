-- The gap between the two venues' closes for a dual-listed instrument, in basis points against
-- their midpoint, beside the turnover on the thinner side. A gap means something only where both
-- venues traded enough for their prices to be held together.
with by_venue as (
    select
        isin,
        trade_date,
        max(as_of_date) as as_of_date,
        max(close) filter (where venue = 'BSE') as bse_close,
        max(close) filter (where venue = 'NSE') as nse_close,
        max(turnover) filter (where venue = 'BSE') as bse_turnover,
        max(turnover) filter (where venue = 'NSE') as nse_turnover
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
    ) as venue_spread_bps,
    least(bse_turnover, nse_turnover) as comparable_turnover
from by_venue
where bse_close is not null and nse_close is not null
