-- How the market's companies moved each day, each on its primary venue. A fund moves with what it
-- holds rather than with the market, so only company ISINs count.
with sessions as (
    select
        trade_date,
        max(as_of_date) as as_of_date,
        bool_and(is_complete) as is_complete
    from {{ ref('stg_trading_day') }}
    group by trade_date
),

companies as (
    select
        trade_date,
        max(as_of_date) as as_of_date,
        count(*) filter (where return_1d > 0) as advancing,
        count(*) filter (where return_1d < 0) as declining,
        count(*) filter (where return_1d = 0) as unchanged,
        count(*) filter (where is_52w_high) as new_52w_highs,
        count(*) filter (where is_52w_low) as new_52w_lows,
        percentile_cont(0.5) within group (order by return_1d) as median_return_1d
    from {{ source('features', 'mart_daily_features') }}
    where isin like 'INE%'
    group by trade_date
)

select
    companies.trade_date,
    companies.advancing,
    companies.declining,
    companies.unchanged,
    companies.new_52w_highs,
    companies.new_52w_lows,
    companies.median_return_1d,
    greatest(companies.as_of_date, sessions.as_of_date) as as_of_date,
    coalesce(sessions.is_complete, false) as is_complete
from companies
left join sessions on companies.trade_date = sessions.trade_date
