-- A bar appearing twice means version resolution let a correction through beside its original.
select
    isin,
    venue,
    trade_date,
    count(*) as versions
from {{ ref('stg_price_daily') }}
group by isin, venue, trade_date
having count(*) > 1
