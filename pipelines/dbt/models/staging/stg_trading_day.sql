-- The latest verdict on each venue day known on the as-of date. A day revalidated after a
-- correction appends a row, so without this both verdicts appear.
select distinct on (venue, trade_date)
    venue,
    trade_date,
    as_of_date,
    is_complete,
    bars,
    divergent_instruments,
    detail
from {{ source('market', 'trading_day') }}
where as_of_date <= '{{ var("as_of_date", "9999-12-31") }}'
order by venue asc, trade_date asc, as_of_date desc
