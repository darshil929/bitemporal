select
    isin,
    venue,
    trade_date,
    volume,
    delivery_quantity,
    as_of_date,
    delivery_percentage
from {{ ref('int_delivery_participation') }}
