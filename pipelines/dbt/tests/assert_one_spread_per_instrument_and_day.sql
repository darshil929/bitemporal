select
    isin,
    trade_date,
    count(*) as rows_for_day
from {{ ref('int_venue_spread') }}
group by isin, trade_date
having count(*) > 1
