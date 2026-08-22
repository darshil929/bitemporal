-- The latest version of each delivery figure known on the as-of date.
select distinct on (isin, venue, trade_date)
    isin,
    venue,
    trade_date,
    as_of_date,
    delivery_quantity
from {{ source('market', 'delivery_daily') }}
where as_of_date <= '{{ var("as_of_date", "9999-12-31") }}'
order by isin asc, venue asc, trade_date asc, as_of_date desc
