-- The latest version of each bar known on the as-of date. A venue republishing a corrected file
-- appends a row, so without this a bar appears once per correction.
select distinct on (isin, venue, trade_date)
    isin,
    venue,
    trade_date,
    as_of_date,
    open,
    high,
    low,
    close,
    previous_close,
    volume,
    turnover,
    trade_count
from {{ source('market', 'price_daily') }}
where as_of_date <= '{{ var("as_of_date", "9999-12-31") }}'
order by isin asc, venue asc, trade_date asc, as_of_date desc
