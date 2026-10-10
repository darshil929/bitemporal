{{ config(meta = {'dagster': {'ref': {'name': 'int_continuous_prices'}}}) }}

-- A bar the lineage drops would shorten a history silently, which is the failure a continuous
-- series exists to prevent. Every published bar reaches its instrument's continuous series, or
-- gives way there to another line of the instrument at the venue that day.
select
    prices.isin,
    prices.venue,
    prices.trade_date
from {{ ref('stg_price_daily') }} as prices
left join {{ ref('int_instrument_lineage') }} as lineage
    on prices.isin = lineage.isin
left join {{ ref('int_continuous_prices') }} as continuous
    on
        lineage.current_isin = continuous.isin
        and prices.venue = continuous.venue
        and prices.trade_date = continuous.trade_date
where continuous.isin is null
