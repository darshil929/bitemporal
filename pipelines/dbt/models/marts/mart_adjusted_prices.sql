select
    isin,
    source_isin,
    venue,
    trade_date,
    as_of_date,
    close_as_traded,
    turnover,
    adjustment_factor,
    open,
    high,
    low,
    close,
    volume,
    delivery_quantity
from {{ ref('int_continuous_prices') }}
