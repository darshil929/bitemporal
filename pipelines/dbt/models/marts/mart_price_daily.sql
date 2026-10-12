select
    isin,
    venue,
    trade_date,
    as_of_date,
    local_symbol,
    scrip_code,
    open,
    high,
    low,
    previous_close,
    volume,
    turnover,
    trade_count,
    close
from {{ ref('stg_price_daily') }}
