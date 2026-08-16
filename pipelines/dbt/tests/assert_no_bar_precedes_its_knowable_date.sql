-- as_of_date records when a bar became knowable; a bar knowable before the day it describes
-- would let a backtest read the future.
select
    isin,
    venue,
    trade_date,
    as_of_date
from {{ ref('stg_price_daily') }}
where as_of_date < trade_date
