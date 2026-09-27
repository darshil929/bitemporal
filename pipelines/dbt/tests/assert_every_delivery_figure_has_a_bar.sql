-- A delivery figure is part of a bar's day. One stored where the instrument has no bar at the
-- venue that day resolved through a listing the price file does not bear out, and the delivery
-- check, which reads delivery joined to bars, never sees it.
select
    delivery.isin,
    delivery.venue,
    delivery.trade_date,
    delivery.delivery_quantity
from {{ ref('stg_delivery_daily') }} as delivery
where not exists (
    select 1 from {{ ref('stg_price_daily') }} as prices
    where
        prices.isin = delivery.isin
        and prices.venue = delivery.venue
        and prices.trade_date = delivery.trade_date
)
