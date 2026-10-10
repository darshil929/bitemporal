-- Two bars for an instrument at a venue on one day would give its series two prices for the day.
select
    isin,
    venue,
    trade_date,
    count(*) as bars
from {{ ref('int_continuous_prices') }}
group by isin, venue, trade_date
having count(*) > 1
