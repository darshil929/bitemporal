-- The share of a day's volume that settled rather than closing out intraday. A high share means
-- buyers took the stock; a low one means the day was traded round.
select
    p.isin,
    p.venue,
    p.trade_date,
    p.volume,
    d.delivery_quantity,
    greatest(p.as_of_date, d.as_of_date) as as_of_date,
    round(100.0 * d.delivery_quantity / nullif(p.volume, 0), 4) as delivery_percentage
from {{ ref('stg_price_daily') }} as p
inner join {{ ref('stg_delivery_daily') }} as d
    on
        p.isin = d.isin
        and p.venue = d.venue
        and p.trade_date = d.trade_date
