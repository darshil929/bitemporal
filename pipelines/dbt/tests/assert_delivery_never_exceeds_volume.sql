-- Delivery is a part of the day's volume. More than all of it means the two files were joined
-- across different securities, which the venue-local identifiers make possible to get wrong.
select
    isin,
    venue,
    trade_date,
    volume,
    delivery_quantity
from {{ ref('int_delivery_participation') }}
where delivery_quantity > volume
