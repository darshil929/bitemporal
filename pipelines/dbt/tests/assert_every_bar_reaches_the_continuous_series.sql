-- A bar the lineage drops would shorten a history silently, which is the failure a continuous
-- series exists to prevent. Every published bar belongs to exactly one continuous series.
select
    prices.isin,
    prices.venue,
    prices.trade_date
from {{ ref('stg_price_daily') }} as prices
left join {{ ref('int_continuous_prices') }} as continuous
    on
        prices.isin = continuous.source_isin
        and prices.venue = continuous.venue
        and prices.trade_date = continuous.trade_date
where continuous.isin is null
