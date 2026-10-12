select
    venue,
    trade_date,
    as_of_date,
    is_complete,
    bars,
    divergent_instruments,
    detail
from {{ ref('stg_trading_day') }}
